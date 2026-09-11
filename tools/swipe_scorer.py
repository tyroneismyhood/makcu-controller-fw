#!/usr/bin/env python3
"""
Swipe Lab scorer (peer-owned): Elgato secondary fusion + YOLO primary close.

Imports Tools locks:
  from swipe_core import FusionSignals, fuse_verdict, ACCEPTANCE, score_band
  from yolo_roi import bbox_center_delta, schema_yolo_block

YOLO replaces feat_return_* for close math (Accuracy lock). Binary-search T*
uses yolo metrics only — never optical flow. If yolo PASS but yaw_flow
SOFT/FAIL → SCALE_DISAGREE (no promote).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from swipe_acceptance import ACCEPTANCE, score_band
from swipe_core import FusionSignals, fuse_verdict
from yolo_roi import Detection, bbox_center_delta

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore

CLASS_SCALE_DISAGREE = "SCALE_DISAGREE"
CLASS_CONVERGE_FAIL = "CONVERGE_FAIL"
MAX_BINSEARCH_ITERS = 12
TOTAL_CAP = 8000
TOTAL_FLOOR = 200
DEFAULT_CHUNK_DX = 120


def _ema(prev: float, x: float, a: float = 0.35) -> float:
    return a * x + (1.0 - a) * prev


@dataclass
class ScorerState:
    ref_gray: Any = None
    ref_kps: Any = None
    ref_desc: Any = None
    prev_gray: Any = None
    yaw_accum_deg: float = 0.0
    sim_smooth: float = 1.0
    sim_curve: list[float] = field(default_factory=list)
    yaw_curve: list[float] = field(default_factory=list)
    ecc_curve: list[float] = field(default_factory=list)
    phase_curve: list[float] = field(default_factory=list)
    feat_px_curve: list[float] = field(default_factory=list)
    frames: int = 0
    detector: Any = None
    matcher: Any = None


def _make_detector():
    if cv2 is None:
        return None, None
    if hasattr(cv2, "AKAZE_create"):
        det = cv2.AKAZE_create()
    else:
        det = cv2.ORB_create(nfeatures=800)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    return det, matcher


class FusionScorer:
    """Secondary signals during pulse: flow yaw, ECC, phase, ORB return."""

    def __init__(self, roi: tuple[int, int, int, int] | None = None):
        self.roi = roi
        self.st = ScorerState()
        self.st.detector, self.st.matcher = _make_detector()

    def _crop(self, frame):
        if frame is None:
            return None
        if self.roi is None:
            return frame
        x, y, w, h = self.roi
        H, W = frame.shape[:2]
        x = max(0, min(W - 1, x))
        y = max(0, min(H - 1, y))
        w = max(1, min(W - x, w))
        h = max(1, min(H - y, h))
        return frame[y : y + h, x : x + w]

    def _gray(self, frame):
        crop = self._crop(frame)
        if crop is None or cv2 is None:
            return None
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
        return cv2.resize(g, (320, 180), interpolation=cv2.INTER_AREA)

    def begin(self, frame) -> None:
        self.st = ScorerState()
        self.st.detector, self.st.matcher = _make_detector()
        g = self._gray(frame)
        self.st.ref_gray = g
        self.st.prev_gray = g
        if g is not None and self.st.detector is not None:
            self.st.ref_kps, self.st.ref_desc = self.st.detector.detectAndCompute(g, None)
        self.st.sim_smooth = 1.0

    def _feat_match(self, gray) -> tuple[float, float]:
        if gray is None or self.st.ref_desc is None or self.st.detector is None:
            return 0.0, 999.0
        kps, desc = self.st.detector.detectAndCompute(gray, None)
        if desc is None or self.st.ref_kps is None or len(kps) < 8:
            return 0.0, 999.0
        try:
            knn = self.st.matcher.knnMatch(self.st.ref_desc, desc, k=2)
        except Exception:
            return 0.0, 999.0
        good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
        if len(good) < 6:
            return 0.0, 999.0
        src = np.float32([self.st.ref_kps[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kps[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        if mask is None:
            return len(good) / max(1, len(knn)), 999.0
        inliers = float(mask.sum()) / float(len(mask))
        h, w = gray.shape[:2]
        pts = np.float32([[w / 2, h / 2]]).reshape(-1, 1, 2)
        try:
            warped = cv2.perspectiveTransform(pts, H)
            px = math.hypot(float(warped[0, 0, 0] - pts[0, 0, 0]), float(warped[0, 0, 1] - pts[0, 0, 1]))
            return inliers, px
        except Exception:
            return inliers, 999.0

    def _phase(self, gray) -> float:
        if gray is None or self.st.ref_gray is None:
            return 0.0
        try:
            (dx, dy), resp = cv2.phaseCorrelate(np.float32(self.st.ref_gray), np.float32(gray))
            shift = math.hypot(float(dx), float(dy))
            peak = float(resp) if resp is not None else 0.0
            return max(0.0, min(1.0, peak * (1.0 / (1.0 + shift / 20.0))))
        except Exception:
            return 0.0

    def _ecc(self, gray) -> float:
        if gray is None or self.st.ref_gray is None:
            return 0.0
        try:
            warp = np.eye(2, 3, dtype=np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 1e-4)
            cc, _ = cv2.findTransformECC(
                np.float32(self.st.ref_gray) / 255.0,
                np.float32(gray) / 255.0,
                warp,
                cv2.MOTION_EUCLIDEAN,
                criteria,
                None,
                1,
            )
            return float(max(0.0, min(1.0, cc)))
        except Exception:
            return 0.0

    def _flow_yaw_delta(self, gray) -> float:
        if gray is None or self.st.prev_gray is None:
            return 0.0
        try:
            flow = cv2.calcOpticalFlowFarneback(
                self.st.prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
            fx = float(np.median(flow[..., 0]))
            return fx * (70.0 / 320.0)
        except Exception:
            return 0.0

    def update(self, frame) -> dict[str, float]:
        g = self._gray(frame)
        if g is None or self.st.ref_gray is None:
            return {}
        inlier, feat_px = self._feat_match(g)
        phase = self._phase(g)
        ecc = self._ecc(g) if self.st.frames % 3 == 0 else (
            self.st.ecc_curve[-1] if self.st.ecc_curve else 0.0
        )
        self.st.yaw_accum_deg += self._flow_yaw_delta(g)
        sim = 0.45 * inlier + 0.30 * phase + 0.25 * ecc
        self.st.sim_smooth = _ema(self.st.sim_smooth, sim)
        self.st.sim_curve.append(self.st.sim_smooth)
        self.st.yaw_curve.append(self.st.yaw_accum_deg)
        self.st.ecc_curve.append(ecc)
        self.st.phase_curve.append(phase)
        self.st.feat_px_curve.append(feat_px)
        self.st.prev_gray = g
        self.st.frames += 1
        return {"sim": self.st.sim_smooth, "yaw": self.st.yaw_accum_deg, "ecc": ecc, "phase": phase}

    def finish(self) -> FusionSignals:
        ecc_peak = max(self.st.ecc_curve) if self.st.ecc_curve else 0.0
        phase_peak = max(self.st.phase_curve) if self.st.phase_curve else 0.0
        feat_px = float(self.st.feat_px_curve[-1]) if self.st.feat_px_curve else 999.0
        # Secondary only — YOLO overwrites feat_return in fuse_yolo_primary
        feat_deg = min(180.0, feat_px * 0.15)
        return FusionSignals(
            yaw_flow_deg=float(self.st.yaw_accum_deg),
            ecc_peak=float(ecc_peak),
            phase_peak=float(phase_peak),
            feat_return_deg=float(feat_deg),
            feat_return_px=float(feat_px),
            frames=self.st.frames,
            similarity_curve=list(self.st.sim_curve),
        )


def yolo_close_metrics(
    t0: list[dict[str, Any]] | list[Detection],
    t1: list[dict[str, Any]] | list[Detection],
    *,
    frame_w: int,
    px_per_deg: float | None = None,
) -> dict[str, Any]:
    """
    Primary close from YOLO T0/T1.
    Prefer yaw_deg_est if px_per_deg; else d_px / frame_w (yolo_dpx).
    """
    a = t0[0] if t0 else None
    b = t1[0] if t1 else None
    delta = bbox_center_delta(a, b, px_per_deg=px_per_deg)
    if not delta.get("ok"):
        return {
            "matched": False,
            "band": "FAIL",
            "yolo_yaw_deg": None,
            "yolo_dpx_norm": None,
            "delta": delta,
            "error": 999.0,
        }
    d_px = float(delta["d_px"])
    dpx_norm = d_px / float(max(1, frame_w))
    yaw = delta.get("yaw_deg_est")
    if yaw is not None:
        err = abs(float(yaw))
        band = score_band("yolo_yaw", err) if "yolo_yaw_pass_deg" in ACCEPTANCE else score_band("yaw", err)
    else:
        err = dpx_norm / float(ACCEPTANCE.get("yolo_dpx_pass_frac", 0.005)) * float(
            ACCEPTANCE.get("yolo_yaw_pass_deg", ACCEPTANCE.get("yaw_pass_deg", 2.0))
        )
        band = score_band("yolo_dpx", dpx_norm)
        yaw = None
    if yaw is not None:
        error = abs(float(yaw))
    else:
        pass_frac = float(ACCEPTANCE.get("yolo_dpx_pass_frac", 0.005))
        pass_deg = float(ACCEPTANCE.get("yolo_yaw_pass_deg", ACCEPTANCE.get("yaw_pass_deg", 2.0)))
        error = dpx_norm / pass_frac * pass_deg
    return {
        "matched": True,
        "band": band,
        "yolo_yaw_deg": float(yaw) if yaw is not None else None,
        "yolo_dpx_norm": dpx_norm,
        "delta": delta,
        "error": float(error),
    }


def fuse_yolo_primary(
    secondary: FusionSignals,
    yolo_metrics: dict[str, Any],
    *,
    matrix_ok: bool | None = None,
    hip_total: int | None = None,
    ads_total: int | None = None,
) -> dict[str, Any]:
    """
    YOLO replaces feat_return_*. Final PASS still needs flow+ECC+phase via
    fuse_verdict, with feat_return set from YOLO error.
    SCALE_DISAGREE if yolo PASS but yaw_flow SOFT/FAIL.
    """
    yolo_band = yolo_metrics.get("band", "FAIL")
    yolo_err = float(yolo_metrics.get("error", 999.0))
    # Inject YOLO as feat_return so Tools fuse_verdict uses it as close residual
    sig = FusionSignals(
        yaw_flow_deg=secondary.yaw_flow_deg,
        ecc_peak=secondary.ecc_peak,
        phase_peak=secondary.phase_peak,
        feat_return_deg=yolo_err if yolo_metrics.get("matched") else 999.0,
        feat_return_px=float((yolo_metrics.get("delta") or {}).get("d_px") or 999.0),
        frames=secondary.frames,
        similarity_curve=list(secondary.similarity_curve),
    )
    verdict = fuse_verdict(
        sig, matrix_ok=matrix_ok, hip_total=hip_total, ads_total=ads_total
    )
    # yaw_flow band alone (distance to 360)
    yaw_raw = float(secondary.yaw_flow_deg)
    if abs(yaw_raw) >= 90.0:
        turns = round(yaw_raw / 360.0) if yaw_raw else 0
        yaw_flow_err = abs(yaw_raw - 360.0 * turns)
    else:
        yaw_flow_err = abs(yaw_raw)
    yaw_flow_band = score_band("yaw", yaw_flow_err)

    classifications: list[str] = []
    if yolo_band == "PASS" and yaw_flow_band in ("SOFT", "FAIL"):
        classifications.append(CLASS_SCALE_DISAGREE)
        verdict["overall"] = "SCALE_DISAGREE"
        verdict["notes"] = list(verdict.get("notes") or []) + [
            "yolo PASS but yaw_flow SOFT/FAIL — no promote"
        ]

    verdict["yolo"] = {
        "band": yolo_band,
        "yolo_yaw_deg": yolo_metrics.get("yolo_yaw_deg"),
        "yolo_dpx_norm": yolo_metrics.get("yolo_dpx_norm"),
        "delta": yolo_metrics.get("delta"),
        "primary_close": "yolo",
    }
    verdict["bands"]["yolo"] = yolo_band
    verdict["bands"]["yaw_flow"] = yaw_flow_band
    verdict["classifications"] = classifications
    # Hard PASS only if yolo + secondary all PASS (and not SCALE_DISAGREE)
    if verdict["overall"] == "PASS" and yolo_band != "PASS":
        verdict["overall"] = "SOFT_FAIL" if yolo_band == "SOFT" else "FAIL"
    return verdict


def binary_search_T_yolo(
    *,
    evaluate: Callable[[int], dict[str, Any]],
    t_lo: int = 8,
    t_hi: int = 40,
    chunk_dx: int = DEFAULT_CHUNK_DX,
    max_iters: int = MAX_BINSEARCH_ITERS,
    pass_err: float | None = None,
) -> dict[str, Any]:
    """
    Binary-search tick count T (TOTAL=T*chunk_dx) on YOLO primary error only.
    evaluate(total) -> yolo_close_metrics dict (must include 'error', 'band').
    """
    if pass_err is None:
        pass_err = float(ACCEPTANCE.get("yolo_yaw_pass_deg", ACCEPTANCE.get("yaw_pass_deg", 2.0)))
    history: list[dict[str, Any]] = []
    lo, hi = max(1, t_lo), max(t_lo + 1, t_hi)
    best: dict[str, Any] = {"T": lo, "err": 999.0, "total": lo * chunk_dx, "band": "FAIL"}
    for i in range(max_iters):
        if hi - lo <= 1:
            break
        mid = (lo + hi) // 2
        total = max(TOTAL_FLOOR, min(TOTAL_CAP, mid * chunk_dx))
        m = evaluate(total)
        err = float(m.get("error", 999.0))
        band = m.get("band", "FAIL")
        history.append({"iter": i, "T": mid, "total": total, "err": err, "band": band})
        if err < float(best["err"]):
            best = {"T": mid, "err": err, "total": total, "band": band, "metrics": m}
        if err <= pass_err and band == "PASS":
            return {
                "ok": True,
                "status": "PASS",
                "T": mid,
                "total": total,
                "err": err,
                "history": history,
                "metrics": m,
            }
        # Under-rotated → increase T; over / close enough → decrease
        if band in ("FAIL", "SOFT") or not m.get("matched", True):
            lo = mid
        else:
            hi = mid
    status = "PASS" if best["err"] <= pass_err and best.get("band") == "PASS" else CLASS_CONVERGE_FAIL
    return {
        "ok": status == "PASS",
        "status": status,
        "T": best["T"],
        "total": best["total"],
        "err": best["err"],
        "history": history,
        "metrics": best.get("metrics"),
    }


def exposure_hint(frame) -> str | None:
    if frame is None or cv2 is None:
        return None
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
    m = float(g.mean())
    if m < 18:
        return "DARK — HDCP / exposure / limited RGB?"
    if m > 240:
        return "BLOWN highlights"
    v = float(cv2.Laplacian(g, cv2.CV_64F).var())
    if v < 25:
        return "BLUR/SOFT"
    return None
