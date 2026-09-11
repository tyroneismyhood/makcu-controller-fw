#!/usr/bin/env python3
"""
Swipe Lab Accuracy+Matrix v1 acceptance constants (Tools lock).

Importable by swipe_ui / Accuracy scorers — single source of truth for thresholds.
Does NOT run pulses, serial, or KMH paths (those stay in swipe_test / swipe_core).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Accuracy+Matrix v1 fusion thresholds
# ---------------------------------------------------------------------------

ACCEPTANCE: dict[str, Any] = {
    # yaw / feat error (degrees)
    "yaw_pass_deg": 2.0,
    "yaw_soft_deg": 5.0,
    # eccentricity
    "ecc_pass": 0.92,
    "ecc_soft": 0.85,
    # phase alignment
    "phase_pass": 0.90,
    "phase_soft": 0.80,
    # all four metrics required for overall PASS
    "fusion_required": ("yolo", "yaw_flow", "ecc", "phase"),
    # YOLO primary close (replaces feat_return); binary-search uses these
    "yolo_yaw_pass_deg": 2.0,
    "yolo_yaw_soft_deg": 5.0,
    "yolo_dpx_pass_frac": 0.005,
    "yolo_dpx_soft_frac": 0.0125,
    # HIP/ADS TOTAL ratio (hip / ads ≈ 2400/1800)
    "hip_ads_ratio": 1.333,
    "hip_ads_ratio_tol": 0.03,  # ±3%
}

# Matrix labels stamped into JSON / HUD when telem path is clean
MATRIX_LABELS: tuple[str, ...] = (
    "CLEAN STOP",
    "NO CARRY",
    "NO OVERSHOOT",
    "RATIO 1.33",
)

# Firmware curve defaults (record in report firmware_defaults; do not retune here)
CURVE_C = 5046.0
CURVE_P = 0.40
CURVE_RAIL = 32767
TICK_MS = 8.0
SHAPE_TOL = 0.03
MAGNITUDES: tuple[int, ...] = (8, 80, 240)
# Expected ix for magnitudes under C/P (Track B sheet)
EXPECTED_IX: dict[int, int] = {8: 11592, 80: 29119, 240: 32767}

DEFAULT_TOTAL_HIP = 2400
DEFAULT_TOTAL_ADS = 1800  # ≈ hip / 1.333
USB2_BAUD = 4_000_000


def hip_ads_ratio_ok(total_hip: int, total_ads: int) -> bool:
    """True if hip/ads TOTAL is within ACCEPTANCE ratio ± tol."""
    if total_ads <= 0:
        return False
    ratio = float(total_hip) / float(total_ads)
    target = float(ACCEPTANCE["hip_ads_ratio"])
    tol = float(ACCEPTANCE["hip_ads_ratio_tol"])
    return abs(ratio - target) <= target * tol


def score_band(metric: str, value: float) -> str:
    """
    Return PASS | SOFT | FAIL for a single Accuracy metric.

    metric: 'yaw' | 'ecc' | 'phase'
    """
    if metric == "yaw":
        if value <= float(ACCEPTANCE["yaw_pass_deg"]):
            return "PASS"
        if value <= float(ACCEPTANCE["yaw_soft_deg"]):
            return "SOFT"
        return "FAIL"
    if metric == "ecc":
        if value >= float(ACCEPTANCE["ecc_pass"]):
            return "PASS"
        if value >= float(ACCEPTANCE["ecc_soft"]):
            return "SOFT"
        return "FAIL"
    if metric == "phase":
        if value >= float(ACCEPTANCE["phase_pass"]):
            return "PASS"
        if value >= float(ACCEPTANCE["phase_soft"]):
            return "SOFT"
        return "FAIL"
    if metric == "yolo_yaw":
        if value <= float(ACCEPTANCE.get("yolo_yaw_pass_deg", 2.0)):
            return "PASS"
        if value <= float(ACCEPTANCE.get("yolo_yaw_soft_deg", 5.0)):
            return "SOFT"
        return "FAIL"
    if metric == "yolo_dpx":
        if value <= float(ACCEPTANCE.get("yolo_dpx_pass_frac", 0.005)):
            return "PASS"
        if value <= float(ACCEPTANCE.get("yolo_dpx_soft_frac", 0.0125)):
            return "SOFT"
        return "FAIL"
    raise ValueError(f"unknown metric: {metric}")


def acceptance_block() -> dict[str, Any]:
    """Schema fragment: acceptance thresholds + matrix labels for JSON header."""
    return {
        "version": "accuracy_matrix_v1",
        "thresholds": dict(ACCEPTANCE),
        "matrix_labels": list(MATRIX_LABELS),
        "curve": {"C": CURVE_C, "P": CURVE_P, "rail": CURVE_RAIL, "tick_ms": TICK_MS},
        "expected_ix": dict(EXPECTED_IX),
        "defaults": {
            "total_hip": DEFAULT_TOTAL_HIP,
            "total_ads": DEFAULT_TOTAL_ADS,
            "usb2_baud": USB2_BAUD,
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(acceptance_block(), indent=2))
