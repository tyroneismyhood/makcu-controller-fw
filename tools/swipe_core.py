#!/usr/bin/env python3
"""
swipe_core — Tools-lock constants + fusion verdict helpers for Swipe Lab.

Ownership note (Xim split):
  ACCEPTANCE / Matrix labels / FusionSignals / fuse_verdict live here.
  Pulse / serial / KMH objective runners remain in tools/swipe_test.py
  (peer may extract later). Void-gates: tools/swipe_preflight.py.
  YOLO ROI detect: tools/yolo_roi.py.

Import surface:
  from swipe_core import ACCEPTANCE, MATRIX_LABELS, FusionSignals, fuse_verdict
  from swipe_preflight import check_void_gates, LagCalibration, VoidReason
  from swipe_keybinds import KEYBINDS, WAITKEY_MAP, action_for_waitkey
  from elgato_capture import list_devices, pin_elgato, open_capture
  from yolo_roi import YoloRoiDetector, bbox_center_delta, schema_yolo_block
  from swipe_results_lib import new_report, apply_preflight, set_yolo_roi, write_results
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from swipe_acceptance import (  # noqa: F401
    ACCEPTANCE,
    CURVE_C,
    CURVE_P,
    CURVE_RAIL,
    DEFAULT_TOTAL_ADS,
    DEFAULT_TOTAL_HIP,
    EXPECTED_IX,
    MAGNITUDES,
    MATRIX_LABELS,
    SHAPE_TOL,
    TICK_MS,
    USB2_BAUD,
    acceptance_block,
    hip_ads_ratio_ok,
    score_band,
)


@dataclass
class FusionSignals:
    """Accuracy multi-signal pack produced by tools/swipe_scorer.py."""

    yaw_flow_deg: float = 0.0
    ecc_peak: float = 0.0
    phase_peak: float = 0.0
    feat_return_deg: float = 999.0
    feat_return_px: float = 999.0
    frames: int = 0
    trough_frame: int | None = None
    recovery_frame: int | None = None
    similarity_curve: list[float] = field(default_factory=list)

    def to_metrics(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep curve out of default metrics blob unless caller wants it
        return d


def fuse_verdict(
    signals: FusionSignals,
    *,
    matrix_ok: bool | None = None,
    hip_total: int | None = None,
    ads_total: int | None = None,
) -> dict[str, Any]:
    """
    Accuracy+Matrix v1 fusion.

    all-four required for overall PASS: yaw, ecc, phase, matrix.
    yaw uses min(|yaw residual vs 360|, feat_return_deg) style residual —
    here yaw_err = min(abs(yaw_flow_deg - 360) mod wrap, feat_return_deg)
    for "did we close a 360" scoring; if yaw_flow is a residual already
    (small), treat abs(yaw_flow_deg) as the error when |yaw| < 90.
    """
    # Interpret yaw: large ~360 means full turn tracked; small means residual.
    yaw_raw = float(signals.yaw_flow_deg)
    if abs(yaw_raw) >= 90.0:
        # distance to nearest full turn
        turns = round(yaw_raw / 360.0) if yaw_raw != 0 else 0
        yaw_err = abs(yaw_raw - 360.0 * turns)
    else:
        yaw_err = abs(yaw_raw)
    feat_err = float(signals.feat_return_deg)
    yaw_metric = min(yaw_err, feat_err)

    yaw_s = score_band("yaw", yaw_metric)
    ecc_s = score_band("ecc", float(signals.ecc_peak))
    phase_s = score_band("phase", float(signals.phase_peak))

    ratio_ok = None
    if hip_total is not None and ads_total is not None:
        ratio_ok = hip_ads_ratio_ok(int(hip_total), int(ads_total))

    if matrix_ok is None:
        # Default matrix gate: ratio if provided, else unknown→not PASS
        matrix_ok = bool(ratio_ok) if ratio_ok is not None else False

    matrix_s = "PASS" if matrix_ok else "FAIL"
    bands = {
        "yaw": yaw_s,
        "ecc": ecc_s,
        "phase": phase_s,
        "matrix": matrix_s,
    }
    # all-four fusion
    required = tuple(ACCEPTANCE.get("fusion_required") or ("yaw", "ecc", "phase", "matrix"))
    vals = [bands[k] for k in required if k in bands]
    if vals and all(v == "PASS" for v in vals):
        overall = "PASS"
    elif any(v == "FAIL" for v in vals):
        overall = "FAIL"
    else:
        overall = "PARTIAL"

    labels = list(MATRIX_LABELS) if matrix_ok else []
    return {
        "overall": overall,
        "bands": bands,
        "metrics": {
            "yaw_err_deg": yaw_metric,
            "yaw_flow_deg": yaw_raw,
            "feat_return_deg": feat_err,
            "ecc_peak": float(signals.ecc_peak),
            "phase_peak": float(signals.phase_peak),
            "hip_ads_ratio_ok": ratio_ok,
            "frames": signals.frames,
        },
        "matrix_labels": labels,
        "acceptance": acceptance_block(),
    }


__all__ = [
    "ACCEPTANCE",
    "MATRIX_LABELS",
    "CURVE_C",
    "CURVE_P",
    "CURVE_RAIL",
    "TICK_MS",
    "SHAPE_TOL",
    "MAGNITUDES",
    "EXPECTED_IX",
    "DEFAULT_TOTAL_HIP",
    "DEFAULT_TOTAL_ADS",
    "USB2_BAUD",
    "acceptance_block",
    "hip_ads_ratio_ok",
    "score_band",
    "FusionSignals",
    "fuse_verdict",
]


if __name__ == "__main__":
    import json

    print(json.dumps(acceptance_block(), indent=2))
    sig = FusionSignals(yaw_flow_deg=358.5, ecc_peak=0.95, phase_peak=0.93, feat_return_deg=1.2)
    print(json.dumps(fuse_verdict(sig, matrix_ok=True, hip_total=2400, ads_total=1800), indent=2))
