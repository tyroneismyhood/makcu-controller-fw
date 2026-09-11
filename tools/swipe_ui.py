#!/usr/bin/env python3
"""
swipe_ui.py — Swipe Lab flagship UI (peer-owned).

Imports Tools locks (do not rewrite):
  swipe_preflight, elgato_capture, swipe_keybinds, swipe_acceptance,
  swipe_core (FusionSignals/fuse_verdict), yolo_roi, swipe_results_lib

Owns: OpenCV HUD, YOLO ROI T0/T1 wiring, binary-search T* on yolo metrics,
Run All → schema v2 JSON. Secondary fusion via swipe_scorer.

Usage:
  python tools/swipe_ui.py --preflight-only
  python tools/swipe_ui.py --port COM5 --lab
  python tools/swipe_ui.py --port COM5          # OpenCV lab if DISPLAY; else tk preflight
  MAKCU_HEADLESS=1 python tools/swipe_ui.py --preflight-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
sys.path.insert(0, os.path.join(_TOOLS, "..", "accessibility"))

from swipe_preflight import (  # noqa: E402
    LagCalibration,
    PreflightState,
    apply_elgato_pin,
    check_void_gates,
    load_preflight_state,
    mark_flash_sheet_green,
    preflight_schema_fields,
    save_preflight_state,
    score_allowed,
)
from elgato_capture import (  # noqa: E402
    is_frame_black,
    list_devices,
    open_capture as elgato_open_capture,
    pin_elgato as elgato_resolve,
)
from swipe_keybinds import action_for_waitkey, keybind_help_lines  # noqa: E402
from swipe_core import (  # noqa: E402
    DEFAULT_TOTAL_ADS,
    DEFAULT_TOTAL_HIP,
    TICK_MS,
    hip_ads_ratio_ok,
)
from swipe_results_lib import (  # noqa: E402
    add_test,
    apply_preflight,
    apply_yolo_block,
    compute_overall,
    new_report,
    results_dir,
    set_calibration,
    set_idle_dz,
    write_results,
)
from yolo_roi import (  # noqa: E402
    Roi,
    YoloConfig,
    YoloRoiDetector,
    schema_yolo_block,
)
from swipe_scorer import (  # noqa: E402
    FusionScorer,
    binary_search_T_yolo,
    exposure_hint,
    fuse_yolo_primary,
    yolo_close_metrics,
)

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore

try:
    from makcu_access import Makcu, load_config
except ImportError:
    Makcu = None  # type: ignore
    load_config = None  # type: ignore


# ---------------------------------------------------------------------------
# CLI helpers (Bench gated paths — preserved)
# ---------------------------------------------------------------------------

def run_swipe_test(port: str, extra: list[str]) -> int:
    script = os.path.join(_TOOLS, "swipe_test.py")
    env = os.environ.copy()
    if "--360" in extra:
        env["SWIPE_REQUIRE_PREFLIGHT"] = "1"
    cmd = [sys.executable, script, port, *extra]
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


def print_void(state: PreflightState) -> int:
    vr = check_void_gates(state)
    print(json.dumps(preflight_schema_fields(state, vr), indent=2))
    print(f"score_allowed={score_allowed(state)} void={vr.void} reason={vr.void_reason or '-'}")
    return 0 if score_allowed(state) else 1


# ---------------------------------------------------------------------------
# OpenCV Lab
# ---------------------------------------------------------------------------

class SwipeLab:
    WIN = "MAKCU Swipe Lab"

    def __init__(
        self,
        port: str,
        *,
        elgato_name: str = "",
        elgato_index: int | None = None,
        fov_deg: float | None = None,
        total_hip: int = DEFAULT_TOTAL_HIP,
        total_ads: int = DEFAULT_TOTAL_ADS,
        chunk_dx: int = 120,
    ) -> None:
        self.port = port
        self.fov_deg = fov_deg
        self.total_hip = int(total_hip)
        self.total_ads = int(total_ads)
        self.chunk_dx = int(chunk_dx)
        self.state = load_preflight_state()
        self.mk: Any = None
        self.version = ""
        self.cap = None
        self.devices = list_devices()
        self.pinned = None
        self._init_capture(elgato_name, elgato_index)
        self.roi: Roi | None = None
        self._roi_drag: tuple[int, int] | None = None
        self._drawing_roi = False
        self.detector = YoloRoiDetector(YoloConfig(backend="ultralytics", model="yolov8n"))
        if not self.detector.available:
            self.detector = YoloRoiDetector(YoloConfig(backend="none", model=""))
        self.yolo_t0: list[dict[str, Any]] = []
        self.yolo_t1: list[dict[str, Any]] = []
        self.locked_cls: str | None = None
        self.locked_xy: tuple[float, float] | None = None
        self.t0_frame = None
        self.last_frame = None
        self.status = "ready"
        self.last_verdict: dict[str, Any] | None = None
        self.idle_dz_suggested: int | None = None
        self.idle_dz_applied: int | None = None
        self.report = None
        self.live_dets: list[Any] = []
        self._connect_makcu()

    def _init_capture(self, name: str, index: int | None) -> None:
        needle: int | str | None = None
        if name:
            needle = name
        elif index is not None:
            needle = index
        elif self.state.capture_device_name:
            needle = self.state.capture_device_name
        elif self.state.capture_index is not None:
            needle = int(self.state.capture_index)
        pinned = elgato_resolve(needle, devices=self.devices)
        self.pinned = pinned
        if pinned is None:
            self.status = "no Elgato pinned — pass --elgato-name / --camera"
            self.cap = None
            return
        ok, detail = apply_elgato_pin(
            self.state,
            device_name=str(pinned.get("name") or name or "Elgato"),
            device_index=int(pinned["index"]),
        )
        save_preflight_state(self.state)
        cap, info = elgato_open_capture(int(pinned["index"]))
        self.cap = cap
        self.status = detail if ok else (info.get("reason") or detail)

    def _connect_makcu(self) -> None:
        if Makcu is None:
            self.status = "makcu_access missing"
            return
        try:
            self.mk = Makcu(self.port)
            self.version = self.mk.version().strip()
            self.mk.steady(False)
            self.mk.trim(0, 0)
            self.mk.idle_dz(0)
            self.status = f"link {self.version}"
        except Exception as exc:
            self.mk = None
            self.status = f"serial fail: {exc}"

    def _read_frame(self):
        if self.cap is None:
            return None
        ok, frame = self.cap.read()
        if not ok:
            return None
        self.last_frame = frame
        return frame

    def _px_per_deg(self, frame_w: int) -> float | None:
        if self.fov_deg and self.fov_deg > 0:
            return float(frame_w) / float(self.fov_deg)
        return None

    def _gate_360(self) -> tuple[bool, str]:
        self.state = load_preflight_state()
        if not score_allowed(self.state):
            vr = check_void_gates(self.state)
            return False, f"VOID {vr.void_reason}: {vr.detail}"
        if self.last_frame is not None and is_frame_black(self.last_frame):
            return False, "VOID black_hdcp_or_exclusive_lock"
        return True, "ok"

    def _send_pulse(self, total: int, *, hold_ads: bool) -> dict[str, Any]:
        if self.mk is None:
            return {"sent": 0, "error": "no makcu"}
        if hold_ads:
            self.mk._send("km.right(1)")
            time.sleep(0.08)
        scorer = FusionScorer(
            roi=(self.roi.x, self.roi.y, self.roi.w, self.roi.h) if self.roi else None
        )
        frame0 = self._read_frame()
        if frame0 is not None:
            scorer.begin(frame0)
        remaining = int(total)
        chunk = max(1, self.chunk_dx)
        sent = 0
        try:
            while remaining > 0:
                dx = chunk if remaining >= chunk else remaining
                self.mk.move(dx, 0)
                sent += dx
                remaining -= dx
                fr = self._read_frame()
                if fr is not None:
                    scorer.update(fr)
                time.sleep(TICK_MS / 1000.0)
        finally:
            if hold_ads:
                self.mk._send("km.right(0)")
            time.sleep(0.08)
        secondary = scorer.finish()
        return {"sent": sent, "secondary": secondary, "total": total, "hold_ads": hold_ads}

    def snap_t0(self) -> None:
        fr = self._read_frame()
        if fr is None:
            self.status = "no frame for T0"
            return
        self.t0_frame = fr.copy()
        dets = self.detector.detect(fr, self.roi)
        if self.locked_xy is not None and dets:
            lx, ly = self.locked_xy
            dets = sorted(
                dets,
                key=lambda d: ((d.center() or (0, 0))[0] - lx) ** 2
                + ((d.center() or (0, 0))[1] - ly) ** 2,
            )
        self.yolo_t0 = [d.to_schema() for d in (dets[:1] if dets else [])]
        if not self.yolo_t0:
            self.status = "T0: no detection — click target or widen ROI"
        else:
            self.status = f"T0 locked {self.yolo_t0[0].get('cls')} conf={self.yolo_t0[0].get('conf'):.2f}"
        self._save_snap_png(fr, self.yolo_t0, "t0")

    def snap_t1(self) -> None:
        fr = self._read_frame()
        if fr is None:
            self.status = "no frame for T1"
            return
        dets = self.detector.detect(fr, self.roi)
        if self.yolo_t0 and dets:
            cls0 = self.yolo_t0[0].get("cls")
            same = [d for d in dets if d.cls == cls0]
            pool = same or dets
            c0 = None
            if self.yolo_t0[0].get("cxcywh"):
                c0 = self.yolo_t0[0]["cxcywh"][:2]
            elif self.yolo_t0[0].get("xyxy"):
                x0, y0, x1, y1 = self.yolo_t0[0]["xyxy"]
                c0 = ((x0 + x1) / 2, (y0 + y1) / 2)
            if c0:
                pool = sorted(
                    pool,
                    key=lambda d: ((d.center() or (0, 0))[0] - c0[0]) ** 2
                    + ((d.center() or (0, 0))[1] - c0[1]) ** 2,
                )
            dets = pool[:1]
        self.yolo_t1 = [d.to_schema() for d in dets]
        self._save_snap_png(fr, self.yolo_t1, "t1")
        self.status = f"T1 dets={len(self.yolo_t1)}"

    def _save_snap_png(self, frame, dets_schema, tag: str) -> None:
        if cv2 is None:
            return
        vis = frame.copy()
        if self.roi:
            cv2.rectangle(
                vis,
                (self.roi.x, self.roi.y),
                (self.roi.x + self.roi.w, self.roi.y + self.roi.h),
                (0, 255, 255),
                2,
            )
        for d in dets_schema:
            xy = d.get("xyxy")
            if not xy:
                continue
            x1, y1, x2, y2 = map(int, xy)
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
        path = os.path.join(results_dir(), f"yolo_{tag}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        cv2.imwrite(path, vis)

    def run_360_mode(self, mode: str) -> None:
        ok, reason = self._gate_360()
        if not ok:
            self.status = reason
            self.last_verdict = {"overall": "VOID", "detail": reason}
            return
        if self.idle_dz_applied is None and self.idle_dz_suggested is None:
            self.status = "refuse score: idle_dz unset — press i (rest) then y (apply)"
            return
        hold = mode == "ads"
        total = self.total_ads if hold else self.total_hip
        self.snap_t0()
        if not self.yolo_t0:
            self.status = "T0 empty — pick target before 360"
            return
        pulse = self._send_pulse(total, hold_ads=hold)
        self.snap_t1()
        fr = self.last_frame
        fw = int(fr.shape[1]) if fr is not None else 1920
        yolo_m = yolo_close_metrics(
            self.yolo_t0,
            self.yolo_t1,
            frame_w=fw,
            px_per_deg=self._px_per_deg(fw),
        )
        secondary = pulse.get("secondary")
        if secondary is None:
            from swipe_core import FusionSignals

            secondary = FusionSignals()
        ratio_ok = hip_ads_ratio_ok(self.total_hip, self.total_ads)
        verdict = fuse_yolo_primary(
            secondary,
            yolo_m,
            matrix_ok=ratio_ok,
            hip_total=self.total_hip,
            ads_total=self.total_ads,
        )
        self.last_verdict = verdict
        self.status = (
            f"{mode} TOTAL={total} yolo={yolo_m.get('band')} "
            f"overall={verdict.get('overall')} "
            f"Δpx={(yolo_m.get('delta') or {}).get('d_px')}"
        )

    def binary_search_mode(self, mode: str) -> None:
        ok, reason = self._gate_360()
        if not ok:
            self.status = reason
            return

        def evaluate(total: int) -> dict[str, Any]:
            self.snap_t0()
            self._send_pulse(total, hold_ads=(mode == "ads"))
            self.snap_t1()
            fr = self.last_frame
            fw = int(fr.shape[1]) if fr is not None else 1920
            return yolo_close_metrics(
                self.yolo_t0,
                self.yolo_t1,
                frame_w=fw,
                px_per_deg=self._px_per_deg(fw),
            )

        t_lo = max(1, (min(self.total_hip, self.total_ads) // self.chunk_dx) // 2)
        t_hi = max(t_lo + 2, (max(self.total_hip, self.total_ads) * 2) // self.chunk_dx)
        result = binary_search_T_yolo(
            evaluate=evaluate, t_lo=t_lo, t_hi=t_hi, chunk_dx=self.chunk_dx
        )
        if mode == "hip":
            self.total_hip = int(result["total"])
        else:
            self.total_ads = int(result["total"])
        self.last_verdict = {"binsearch": result}
        self.status = f"binsearch {mode} → T={result.get('T')} TOTAL={result.get('total')} {result.get('status')}"

    def run_objective(self) -> None:
        if not self.port:
            self.status = "no port"
            return
        code = run_swipe_test(self.port, [])
        self.status = f"objective exit={code}"

    def rest_idle_dz(self) -> None:
        if self.mk is None:
            self.status = "no makcu"
            return
        # thin rest sample via swipe_test path or inline
        self.mk.telem(1)
        time.sleep(0.05)
        rx, ry = [], []
        gen = self.mk.read_telem()
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            try:
                d = next(gen)
            except StopIteration:
                break
            if d.get("_kind") == "kms":
                rx.append(abs(int(d["rx"])))
                ry.append(abs(int(d["ry"])))
        self.mk.telem(0)
        if not rx:
            self.idle_dz_suggested = 0
        else:
            rx.sort()
            ry.sort()
            p99 = max(rx[int(0.99 * (len(rx) - 1))], ry[int(0.99 * (len(ry) - 1))])
            self.idle_dz_suggested = int(p99)
        self.status = f"idle_dz suggested={self.idle_dz_suggested}"

    def apply_idle_dz(self) -> None:
        if self.mk is None:
            return
        n = int(self.idle_dz_suggested or 0)
        self.mk.idle_dz(n)
        self.idle_dz_applied = n
        self.status = f"applied idle_dz={n}"

    def run_all(self) -> None:
        """Objective + rest + hip/ads YOLO 360 + save schema v2 JSON."""
        self.run_objective()
        self.rest_idle_dz()
        if self.idle_dz_suggested is not None:
            self.apply_idle_dz()
        ok, reason = self._gate_360()
        report = new_report(
            port=self.port,
            version=self.version or "",
            source="swipe_ui",
            capture_device=(self.pinned or {}).get("name"),
            capture_index=(self.pinned or {}).get("index"),
            lag_offset_ms=getattr(self.state.lag, "lag_offset_ms", None),
        )
        vr = check_void_gates(self.state)
        apply_preflight(report, preflight_schema_fields(self.state, vr))
        set_idle_dz(
            report,
            suggested=self.idle_dz_suggested,
            applied=self.idle_dz_applied,
        )
        if not ok:
            add_test(report, "vision_360", status="VOID", detail=reason, void=True)
            report["overall"] = "VOID"
            paths = write_results(report)
            self.status = f"VOID saved {paths[0]}"
            self.report = report
            return
        self.run_360_mode("hip")
        hip_v = dict(self.last_verdict or {})
        add_test(
            report,
            "hip_360_yolo",
            status=str(hip_v.get("overall", "FAIL")),
            metrics=hip_v.get("yolo") or hip_v.get("metrics") or {},
            detail=self.status,
        )
        self.run_360_mode("ads")
        ads_v = dict(self.last_verdict or {})
        add_test(
            report,
            "ads_360_yolo",
            status=str(ads_v.get("overall", "FAIL")),
            metrics=ads_v.get("yolo") or ads_v.get("metrics") or {},
            detail=self.status,
        )
        set_calibration(
            report,
            hip_total=self.total_hip,
            hip_status=str(hip_v.get("overall")),
            ads_total=self.total_ads,
            ads_status=str(ads_v.get("overall")),
        )
        block = schema_yolo_block(
            roi=self.roi,
            yolo=self.detector.config,
            yolo_t0=self.yolo_t0,
            yolo_t1=self.yolo_t1,
            delta=(ads_v.get("yolo") or {}).get("delta")
            or (hip_v.get("yolo") or {}).get("delta"),
        )
        apply_yolo_block(report, block)
        report["overall"] = compute_overall(report)
        paths = write_results(report)
        self.report = report
        self.status = f"Run All → {paths[0]} overall={report['overall']}"

    def save_results(self) -> None:
        if self.report is None:
            # save current snaps / last verdict
            report = new_report(
                port=self.port,
                version=self.version or "",
                source="swipe_ui",
                capture_device=(self.pinned or {}).get("name"),
                capture_index=(self.pinned or {}).get("index"),
                lag_offset_ms=getattr(self.state.lag, "lag_offset_ms", None),
            )
            vr = check_void_gates(load_preflight_state())
            apply_preflight(report, preflight_schema_fields(self.state, vr))
            apply_yolo_block(
                report,
                schema_yolo_block(
                    roi=self.roi,
                    yolo=self.detector.config,
                    yolo_t0=self.yolo_t0,
                    yolo_t1=self.yolo_t1,
                    delta=(self.last_verdict or {}).get("yolo", {}).get("delta")
                    if self.last_verdict
                    else None,
                ),
            )
            if self.last_verdict:
                add_test(
                    report,
                    "last_verdict",
                    status=str(self.last_verdict.get("overall", "INFO")),
                    metrics=self.last_verdict,
                )
            report["overall"] = compute_overall(report)
            self.report = report
        paths = write_results(self.report)
        self.status = f"saved {paths[0]}"

    def on_mouse(self, event, x, y, flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            if self._drawing_roi:
                self._roi_drag = (x, y)
            else:
                # lock target
                self.locked_xy = (float(x), float(y))
                if self.live_dets:
                    best = min(
                        self.live_dets,
                        key=lambda d: ((d.center() or (0, 0))[0] - x) ** 2
                        + ((d.center() or (0, 0))[1] - y) ** 2,
                    )
                    self.locked_cls = str(best.cls)
                    self.status = f"locked {self.locked_cls}"
                else:
                    self.status = f"click lock @ {x},{y}"
        elif event == cv2.EVENT_MOUSEMOVE and self._drawing_roi and self._roi_drag:
            x0, y0 = self._roi_drag
            self.roi = Roi(min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
        elif event == cv2.EVENT_LBUTTONUP and self._drawing_roi and self._roi_drag:
            x0, y0 = self._roi_drag
            self.roi = Roi(min(x0, x), min(y0, y), max(1, abs(x - x0)), max(1, abs(y - y0)))
            self._roi_drag = None
            self._drawing_roi = False
            self.state.roi_colorspace_stable = True  # fresh ROI intentional
            self.status = f"ROI {self.roi.as_dict()}"

    def handle(self, action: str | None) -> bool:
        """Return False to quit."""
        if action is None:
            return True
        if action == "quit":
            if self.mk:
                try:
                    self.mk._send("km.right(0)")
                except Exception:
                    pass
            return False
        if action == "set_roi":
            self._drawing_roi = True
            self.status = "drag ROI on preview"
        elif action == "cycle_detector":
            cfg = self.detector.cycle()
            self.status = f"detector {cfg.backend}:{cfg.model} avail={self.detector.available}"
        elif action == "run_objective":
            self.run_objective()
        elif action == "rest_idle_dz":
            self.rest_idle_dz()
        elif action == "apply_idle_dz":
            self.apply_idle_dz()
        elif action == "run_all":
            self.run_all()
        elif action == "hip_360":
            self.run_360_mode("hip")
        elif action == "ads_360":
            self.run_360_mode("ads")
        elif action == "total_dec":
            self.total_hip = max(200, int(self.total_hip * 0.85))
            self.total_ads = max(200, int(self.total_ads * 0.85))
            self.status = f"TOTAL hip={self.total_hip} ads={self.total_ads}"
        elif action == "total_inc":
            self.total_hip = min(8000, int(self.total_hip * 1.15))
            self.total_ads = min(8000, int(self.total_ads * 1.15))
            self.status = f"TOTAL hip={self.total_hip} ads={self.total_ads}"
        elif action == "snap_t0":
            self.snap_t0()
        elif action == "snap_t1":
            self.snap_t1()
        elif action == "save_results":
            self.save_results()
        elif action == "preflight_check":
            self.state = load_preflight_state()
            vr = check_void_gates(self.state)
            self.status = f"preflight void={vr.void} {vr.void_reason or 'PASS'}"
        elif action == "toggle_flash_sheet":
            self.state = load_preflight_state()
            mark_flash_sheet_green(
                self.state,
                both_bins=not self.state.flash_sheet_green,
                power_cycled=not self.state.flash_sheet_green,
                filters_off=True,
            )
            save_preflight_state(self.state)
            self.status = f"flash_sheet_green={self.state.flash_sheet_green}"
        elif action == "cycle_capture":
            self.devices = list_devices()
            idxs = [d["index"] for d in self.devices if d.get("opened") is not False]
            if not idxs:
                self.status = "no cameras"
            else:
                cur = (self.pinned or {}).get("index", idxs[0])
                try:
                    i = idxs.index(cur)
                except ValueError:
                    i = -1
                nxt = idxs[(i + 1) % len(idxs)]
                if self.cap:
                    self.cap.release()
                self.cap, info = elgato_open_capture(nxt)
                self.pinned = next(d for d in self.devices if d["index"] == nxt)
                apply_elgato_pin(
                    self.state,
                    device_name=str(self.pinned.get("name") or "camera"),
                    device_index=nxt,
                )
                save_preflight_state(self.state)
                self.status = f"capture idx={nxt} {self.pinned.get('name')} ok={info.get('ok')}"
        elif action == "lag_calib":
            # operator enters offset via state — flash mark at now
            t0 = time.monotonic()
            fr = self._read_frame()
            t1 = time.monotonic()
            # crude: assume flash seen this frame; store 0 if first
            lag_ms = (t1 - t0) * 1000.0
            self.state.lag.mark(
                lag_ms,
                device_name=(self.pinned or {}).get("name"),
                device_index=(self.pinned or {}).get("index"),
                note="swipe_ui l-key",
            )
            self.state.lag.save()
            save_preflight_state(self.state)
            self.status = f"lag_offset_ms≈{lag_ms:.1f} (refine with --set-lag-ms)"
        elif action == "reconnect_port":
            self._connect_makcu()
        elif action == "game_pulse":
            if self.mk:
                for _ in range(40):
                    self.mk.move(120, 0)
                    time.sleep(TICK_MS / 1000.0)
                self.status = "game-pulse done"
        elif action in ("feel_under", "feel_over", "feel_ok"):
            self.status = f"feel mark: {action}"
        return True

    def _draw_hud(self, frame):
        if frame is None or cv2 is None:
            return frame
        vis = frame.copy()
        if self.roi:
            cv2.rectangle(
                vis,
                (self.roi.x, self.roi.y),
                (self.roi.x + self.roi.w, self.roi.y + self.roi.h),
                (0, 255, 255),
                2,
            )
        # live dets
        if self.detector.available:
            self.live_dets = self.detector.detect(frame, self.roi)
            for d in self.live_dets[:8]:
                if not d.xyxy:
                    continue
                x1, y1, x2, y2 = map(int, d.xyxy)
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 200, 0), 1)
                cv2.putText(
                    vis, f"{d.cls}", (x1, max(12, y1 - 2)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 0), 1, cv2.LINE_AA,
                )
        # T0 ghost
        if self.yolo_t0 and self.yolo_t0[0].get("xyxy"):
            x1, y1, x2, y2 = map(int, self.yolo_t0[0]["xyxy"])
            cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 128, 0), 1)
            cv2.putText(vis, "T0", (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 128, 0), 1)
        if self.yolo_t1 and self.yolo_t1[0].get("xyxy"):
            x1, y1, x2, y2 = map(int, self.yolo_t1[0]["xyxy"])
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 128, 255), 2)
            cv2.putText(vis, "T1", (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 128, 255), 1)
        hint = exposure_hint(frame)
        lines = [
            f"port={self.port}  look=2  aim=1.50",
            f"Elgato={(self.pinned or {}).get('name', '?')} idx={(self.pinned or {}).get('index', '-')}",
            f"det={self.detector.config.backend}:{self.detector.config.model} avail={self.detector.available}",
            f"TOTAL hip={self.total_hip} ads={self.total_ads}  idle_dz={self.idle_dz_applied}/{self.idle_dz_suggested}",
            f"score_allowed={score_allowed(self.state)}",
            self.status[:90],
        ]
        if hint:
            lines.append(hint)
        if self.last_verdict:
            lines.append(f"verdict={self.last_verdict.get('overall')}")
        y = 18
        for ln in lines:
            cv2.putText(vis, ln, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(vis, ln, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 240, 240), 1, cv2.LINE_AA)
            y += 18
        return vis

    def loop(self) -> int:
        if cv2 is None:
            print("opencv missing — pip install opencv-python", file=sys.stderr)
            return 1
        if os.environ.get("MAKCU_HEADLESS") or not os.environ.get("DISPLAY"):
            print("No DISPLAY / MAKCU_HEADLESS — use --preflight-only or --no-gui", file=sys.stderr)
            return print_void(self.state)
        cv2.namedWindow(self.WIN, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.WIN, self.on_mouse)
        print("Swipe Lab keys:")
        for ln in keybind_help_lines()[:12]:
            print(ln)
        while True:
            fr = self._read_frame()
            if fr is None:
                fr = __import__("numpy").zeros((720, 1280, 3), dtype="uint8")
                cv2.putText(fr, "NO CAPTURE", (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)
            vis = self._draw_hud(fr)
            cv2.imshow(self.WIN, vis)
            key = cv2.waitKey(1) & 0xFF
            if key == 255:
                continue
            action = action_for_waitkey(key)
            if not self.handle(action):
                break
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        return 0


def run_gui_tk(port: str, elgato_name: str) -> int:
    """Bench tkinter preflight panel (fallback)."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("tkinter missing — try --lab with OpenCV or --preflight-only", file=sys.stderr)
        return 1

    # Reuse prior Bench App briefly via subprocess-style inline
    lab = SwipeLab(port, elgato_name=elgato_name)
    # If OpenCV available and DISPLAY, prefer lab
    if cv2 is not None and os.environ.get("DISPLAY") and not os.environ.get("MAKCU_HEADLESS"):
        return lab.loop()

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("MAKCU Swipe Lab (preflight)")
            self.geometry("640x400")
            self.state = load_preflight_state()
            ttk.Button(self, text="Preflight", command=self.refresh).pack(pady=6)
            ttk.Button(self, text="Run All (lab)", command=self.all).pack(pady=6)
            self.log = tk.Text(self, height=18)
            self.log.pack(fill=tk.BOTH, expand=True)

        def refresh(self) -> None:
            self.state = load_preflight_state()
            vr = check_void_gates(self.state)
            self.log.insert(tk.END, json.dumps(preflight_schema_fields(self.state, vr), indent=2) + "\n")

        def all(self) -> None:
            lab.run_all()
            self.log.insert(tk.END, lab.status + "\n")

    App().mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MAKCU Swipe Lab UI — YOLO T0/T1 + preflight gate")
    ap.add_argument("port_pos", nargs="?", default="")
    ap.add_argument("--port", default="")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--360", dest="want_360", action="store_true")
    ap.add_argument("--lab", action="store_true", help="Force OpenCV lab")
    ap.add_argument("--elgato-name", default="")
    ap.add_argument("--elgato-index", type=int, default=None)
    ap.add_argument("--camera", type=int, default=None, help="alias --elgato-index")
    ap.add_argument("--set-lag-ms", type=float, default=None)
    ap.add_argument("--mark-flash-green", action="store_true")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--fov-deg", type=float, default=None, help="Horizontal FOV for yolo_yaw_deg")
    ap.add_argument("--total-hip", type=int, default=DEFAULT_TOTAL_HIP)
    ap.add_argument("--total-ads", type=int, default=DEFAULT_TOTAL_ADS)
    ap.add_argument("--run-all", action="store_true", help="Headless-ish run all then exit")
    args = ap.parse_args(argv)

    port = args.port or args.port_pos
    if not port and load_config:
        try:
            port = str(load_config().get("port") or "")
        except Exception:
            port = ""
    if not port:
        port = "COM5"

    elgato_index = args.elgato_index if args.elgato_index is not None else args.camera
    state = load_preflight_state()

    if args.elgato_name or elgato_index is not None:
        apply_elgato_pin(
            state,
            device_name=args.elgato_name or state.capture_device_name or "Elgato",
            device_index=elgato_index,
        )
        save_preflight_state(state)

    if args.set_lag_ms is not None:
        state.lag.mark(
            args.set_lag_ms,
            device_name=state.capture_device_name,
            device_index=state.capture_index,
            note="cli --set-lag-ms",
        )
        state.lag.save()
        save_preflight_state(state)

    if args.mark_flash_green:
        mark_flash_sheet_green(state)
        save_preflight_state(state)

    if args.preflight_only or args.no_gui:
        return print_void(state)

    if args.want_360:
        code = print_void(state)
        if not score_allowed(state):
            print("360 blocked — preflight VOID", file=sys.stderr)
            return 2
        return run_swipe_test(port, ["--360"])

    lab = SwipeLab(
        port,
        elgato_name=args.elgato_name,
        elgato_index=elgato_index,
        fov_deg=args.fov_deg,
        total_hip=args.total_hip,
        total_ads=args.total_ads,
    )
    if args.run_all:
        lab.run_all()
        print(lab.status)
        return 0 if (lab.report or {}).get("overall") in ("PASS", "PARTIAL", None) else 1

    if args.lab or (cv2 is not None and os.environ.get("DISPLAY") and not os.environ.get("MAKCU_HEADLESS")):
        return lab.loop()
    return run_gui_tk(port, args.elgato_name)


if __name__ == "__main__":
    raise SystemExit(main())
