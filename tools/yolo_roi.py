#!/usr/bin/env python3
"""
Thin YOLO-in-ROI detect API for Swipe Lab (Tools lock).

Peer fusion/scorer imports this — do not embed a full YOLO scorer in swipe_ui.

  from yolo_roi import YoloRoiDetector, Detection, bbox_center_delta

Backends (optional deps — UI runs without them; void vision score if required):
  - ultralytics (YOLOv8)
  - onnxruntime (+ opencv DNN or raw ORT)

Flow: snap T0 in ROI → 360 → snap T1 → math-compare bbox centers (delta).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BackendName = Literal["ultralytics", "onnx", "none"]

# Prefer these model ids when cycling detectors in the UI
DETECTOR_CYCLE: tuple[tuple[BackendName, str], ...] = (
    ("ultralytics", "yolov8n"),
    ("onnx", "yolov8n.onnx"),
    ("none", ""),
)


@dataclass
class Roi:
    x: int
    y: int
    w: int
    h: int

    def clamp(self, frame_w: int, frame_h: int) -> Roi:
        x = max(0, min(int(self.x), max(0, frame_w - 1)))
        y = max(0, min(int(self.y), max(0, frame_h - 1)))
        w = max(1, min(int(self.w), frame_w - x))
        h = max(1, min(int(self.h), frame_h - y))
        return Roi(x, y, w, h)

    def as_dict(self) -> dict[str, int]:
        return {"x": int(self.x), "y": int(self.y), "w": int(self.w), "h": int(self.h)}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Roi | None:
        if not d:
            return None
        try:
            return cls(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Detection:
    """One detection; coordinates are full-frame pixels (ROI offset applied)."""

    cls: str | int
    conf: float
    # Prefer xyxy; cxcywh filled when useful
    xyxy: tuple[float, float, float, float] | None = None
    cxcywh: tuple[float, float, float, float] | None = None

    def center(self) -> tuple[float, float] | None:
        if self.cxcywh is not None:
            return float(self.cxcywh[0]), float(self.cxcywh[1])
        if self.xyxy is not None:
            x0, y0, x1, y1 = self.xyxy
            return (x0 + x1) / 2.0, (y0 + y1) / 2.0
        return None

    def to_schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"cls": self.cls, "conf": float(self.conf)}
        if self.xyxy is not None:
            out["xyxy"] = [float(v) for v in self.xyxy]
        if self.cxcywh is not None:
            out["cxcywh"] = [float(v) for v in self.cxcywh]
        return out


@dataclass
class YoloConfig:
    backend: BackendName = "none"
    model: str = "yolov8n"
    conf: float = 0.25

    def to_schema(self) -> dict[str, Any]:
        return {"backend": self.backend, "model": self.model, "conf": float(self.conf)}


def backends_available() -> dict[str, bool]:
    out = {"ultralytics": False, "onnxruntime": False, "opencv": False}
    try:
        import ultralytics  # noqa: F401

        out["ultralytics"] = True
    except Exception:
        pass
    try:
        import onnxruntime  # noqa: F401

        out["onnxruntime"] = True
    except Exception:
        pass
    try:
        import cv2  # noqa: F401

        out["opencv"] = True
    except Exception:
        pass
    return out


def bbox_center_delta(
    t0: Detection | dict[str, Any] | None,
    t1: Detection | dict[str, Any] | None,
    *,
    px_per_deg: float | None = None,
) -> dict[str, Any]:
    """
    Math-compare bbox centers T0→T1 after a 360.

    Returns schema delta: {dx_px, dy_px, d_px, yaw_deg_est?}
    Missing dets → empty/partial with nulls.
    """
    c0 = _center_of(t0)
    c1 = _center_of(t1)
    if c0 is None or c1 is None:
        return {
            "dx_px": None,
            "dy_px": None,
            "d_px": None,
            "yaw_deg_est": None,
            "ok": False,
        }
    dx = float(c1[0] - c0[0])
    dy = float(c1[1] - c0[1])
    d = math.hypot(dx, dy)
    yaw = None
    if px_per_deg and px_per_deg > 0:
        # Horizontal shift as crude yaw residual after intended 360
        yaw = dx / float(px_per_deg)
    return {
        "dx_px": dx,
        "dy_px": dy,
        "d_px": d,
        "yaw_deg_est": yaw,
        "ok": True,
    }


def _center_of(det: Detection | dict[str, Any] | None) -> tuple[float, float] | None:
    if det is None:
        return None
    if isinstance(det, Detection):
        return det.center()
    if isinstance(det, dict):
        if det.get("cxcywh"):
            c = det["cxcywh"]
            return float(c[0]), float(c[1])
        if det.get("xyxy"):
            x0, y0, x1, y1 = det["xyxy"]
            return (float(x0) + float(x1)) / 2.0, (float(y0) + float(y1)) / 2.0
    return None


def crop_roi(frame: Any, roi: Roi) -> tuple[Any, Roi]:
    """Return (crop, clamped_roi). frame is HxWxC ndarray."""
    h, w = frame.shape[:2]
    r = roi.clamp(w, h)
    crop = frame[r.y : r.y + r.h, r.x : r.x + r.w]
    return crop, r


class YoloRoiDetector:
    """
    Optional YOLO detector scoped to an ROI.

    If backend deps missing, available=False and detect() returns [].
    """

    def __init__(self, config: YoloConfig | None = None) -> None:
        self.config = config or YoloConfig()
        self._model: Any = None
        self._err: str | None = None
        self._load()

    @property
    def available(self) -> bool:
        return self._model is not None and self.config.backend != "none"

    @property
    def error(self) -> str | None:
        return self._err

    def _load(self) -> None:
        self._model = None
        self._err = None
        b = self.config.backend
        if b == "none" or not self.config.model:
            self._err = "backend=none"
            return
        if b == "ultralytics":
            try:
                from ultralytics import YOLO

                self._model = YOLO(self.config.model)
            except Exception as exc:  # noqa: BLE001
                self._err = f"ultralytics: {exc}"
            return
        if b == "onnx":
            try:
                import onnxruntime as ort

                self._model = ort.InferenceSession(
                    self.config.model, providers=["CPUExecutionProvider"]
                )
            except Exception as exc:  # noqa: BLE001
                self._err = f"onnxruntime: {exc}"
            return
        self._err = f"unknown backend {b}"

    def set_backend(self, backend: BackendName, model: str, conf: float | None = None) -> None:
        self.config.backend = backend
        self.config.model = model
        if conf is not None:
            self.config.conf = float(conf)
        self._load()

    def cycle(self) -> YoloConfig:
        """Advance DETECTOR_CYCLE; returns new config."""
        cur = (self.config.backend, self.config.model)
        opts = list(DETECTOR_CYCLE)
        try:
            idx = next(
                i
                for i, (b, m) in enumerate(opts)
                if b == cur[0] and (m == cur[1] or (b == "none" and cur[0] == "none"))
            )
        except StopIteration:
            idx = -1
        nxt = opts[(idx + 1) % len(opts)]
        self.set_backend(nxt[0], nxt[1])
        return self.config

    def detect(self, frame: Any, roi: Roi | None = None) -> list[Detection]:
        """
        Run detector. If roi given, crop first and offset boxes back to full frame.
        Returns [] if unavailable (caller should void vision score if detector required).
        """
        if not self.available or frame is None:
            return []
        offset_x = offset_y = 0
        view = frame
        if roi is not None:
            view, r = crop_roi(frame, roi)
            offset_x, offset_y = r.x, r.y
        if self.config.backend == "ultralytics":
            return self._detect_ultralytics(view, offset_x, offset_y)
        if self.config.backend == "onnx":
            return self._detect_onnx(view, offset_x, offset_y)
        return []

    def _detect_ultralytics(self, view: Any, ox: int, oy: int) -> list[Detection]:
        try:
            results = self._model.predict(
                view, conf=self.config.conf, verbose=False
            )
        except Exception:
            return []
        out: list[Detection] = []
        if not results:
            return out
        r0 = results[0]
        names = getattr(r0, "names", {}) or {}
        boxes = getattr(r0, "boxes", None)
        if boxes is None:
            return out
        try:
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            clss = boxes.cls.cpu().numpy()
        except Exception:
            return out
        for i in range(len(xyxy)):
            x0, y0, x1, y1 = [float(v) for v in xyxy[i]]
            x0, x1 = x0 + ox, x1 + ox
            y0, y1 = y0 + oy, y1 + oy
            cid = int(clss[i])
            label: str | int = names.get(cid, cid) if isinstance(names, dict) else cid
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            bw = x1 - x0
            bh = y1 - y0
            out.append(
                Detection(
                    cls=label,
                    conf=float(confs[i]),
                    xyxy=(x0, y0, x1, y1),
                    cxcywh=(cx, cy, bw, bh),
                )
            )
        return out

    def _detect_onnx(self, view: Any, ox: int, oy: int) -> list[Detection]:
        """
        Minimal ONNX path — expects a YOLOv8-like end-to-end model.
        If session/IO layout unknown, return [] (peer can specialize).
        """
        # Intentionally thin: full letterbox/NMS left to peer or ultralytics path.
        _ = (view, ox, oy)
        return []

    def snap(
        self, frame: Any, roi: Roi | None = None, *, pick: str = "top"
    ) -> list[dict[str, Any]]:
        """Detect and return schema list for yolo_t0 / yolo_t1."""
        dets = self.detect(frame, roi)
        if pick == "top" and dets:
            dets = sorted(dets, key=lambda d: d.conf, reverse=True)[:1]
        return [d.to_schema() for d in dets]


def schema_yolo_block(
    *,
    roi: Roi | dict[str, Any] | None,
    yolo: YoloConfig | dict[str, Any] | None,
    yolo_t0: list[Any] | None = None,
    yolo_t1: list[Any] | None = None,
    delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Schema v2 fragment for ROI/YOLO T0→T1 compare."""
    roi_d = roi.as_dict() if isinstance(roi, Roi) else roi
    yolo_d = yolo.to_schema() if isinstance(yolo, YoloConfig) else yolo
    t0 = []
    for item in yolo_t0 or []:
        t0.append(item.to_schema() if isinstance(item, Detection) else item)
    t1 = []
    for item in yolo_t1 or []:
        t1.append(item.to_schema() if isinstance(item, Detection) else item)
    return {
        "roi": roi_d,
        "yolo": yolo_d,
        "yolo_t0": t0,
        "yolo_t1": t1,
        "delta": delta,
    }


if __name__ == "__main__":
    import json

    print("backends:", backends_available())
    print("cycle:", DETECTOR_CYCLE)
    d = bbox_center_delta(
        {"cxcywh": [100, 200, 40, 40]},
        {"cxcywh": [110, 198, 40, 40]},
        px_per_deg=10.0,
    )
    print(json.dumps(d, indent=2))
