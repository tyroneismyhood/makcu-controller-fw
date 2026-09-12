#!/usr/bin/env python3
"""
Swipe Lab void-gates + Elgato lag calibration (Tools lock — shared import).

Bench bring-up: /workspace/bench/ELGATO_SWIPE_LAB_BRINGUP.md

swipe_ui MUST import this module — do not rewrite void logic in the UI:

  from swipe_preflight import (
      VoidReason, check_void_gates, LagCalibration,
      preflight_schema_fields, score_allowed,
      pin_elgato, apply_elgato_pin, load_preflight_state,
      save_preflight_state, mark_flash_sheet_green,
  )

Void runs are NOT soft/late — stamp void:true + void_reason and skip scoring.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Void reasons (stable string values for JSON schema v2)
# ---------------------------------------------------------------------------


class VoidReason(str, Enum):
    """Why a vision/score run is void (not a firmware soft/late fail)."""

    NONE = ""
    CAMERA_NOT_PINNED = "camera_not_pinned_elgato"
    BLACK_HDCP_LOCK = "black_hdcp_or_exclusive_lock"
    DROPPED_FRAMES = "dropped_frames_in_window"
    LAG_UNKNOWN = "capture_lag_offset_unknown"
    LAG_CHANGED = "capture_lag_offset_changed"
    FLASH_SHEET_NOT_GREEN = "flash_sheet_not_green"
    WALL_CLOCK_MERGE = "vision_joined_on_wall_clock"
    ROI_COLORSPACE_DRIFT = "roi_or_colorspace_changed_mid_session"
    MULTIPLE = "multiple_void_gates"


# Gate descriptions for HUD / docs (order matches bring-up checklist §D)
VOID_GATE_HELP: dict[str, str] = {
    VoidReason.CAMERA_NOT_PINNED.value: (
        "Camera index must be pinned Elgato by name/VID (not index 0)"
    ),
    VoidReason.BLACK_HDCP_LOCK.value: (
        "No black / HDCP / exclusive lock during spin"
    ),
    VoidReason.DROPPED_FRAMES.value: (
        "Dropped frames == 0 in scored window"
    ),
    VoidReason.LAG_UNKNOWN.value: (
        "Capture lag offset must be known (calib once: flash/LED vs lab monotonic)"
    ),
    VoidReason.LAG_CHANGED.value: (
        "Capture lag offset unchanged since last calib"
    ),
    VoidReason.FLASH_SHEET_NOT_GREEN.value: (
        "Flash sheet green (both bins, power-cycle, filters off)"
    ),
    VoidReason.WALL_CLOCK_MERGE.value: (
        "Vision joined via lab monotonic + lag offset → KMH tick — NEVER raw dual-PC wall clock"
    ),
    VoidReason.ROI_COLORSPACE_DRIFT.value: (
        "ROI/colorspace stable mid-session"
    ),
}


# ---------------------------------------------------------------------------
# Lag calibration (lab monotonic only)
# ---------------------------------------------------------------------------

DEFAULT_LAG_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "results", "lag_calib.json"
)


@dataclass
class LagCalibration:
    """
    Capture lag offset: Elgato buffer vs lab monotonic clock.

    Join path: vision_t_lab = frame_monotonic - lag_offset_ms/1000
               → join to KMH tick window — never dual-PC wall clock.
    """

    lag_offset_ms: float | None = None
    calibrated_at_monotonic: float | None = None
    calibrated_at_utc: str | None = None
    method: str = "flash_or_led"  # operator flash / LED blink vs lab clock
    capture_device_name: str | None = None
    capture_index: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.lag_offset_ms is not None

    def mark(
        self,
        lag_offset_ms: float,
        *,
        device_name: str | None = None,
        device_index: int | None = None,
        method: str | None = None,
        note: str | None = None,
    ) -> None:
        from datetime import datetime, timezone

        self.lag_offset_ms = float(lag_offset_ms)
        self.calibrated_at_monotonic = time.monotonic()
        self.calibrated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if device_name is not None:
            self.capture_device_name = device_name
        if device_index is not None:
            self.capture_index = int(device_index)
        if method is not None:
            self.method = method
        if note:
            self.notes.append(note)

    def unchanged_since(
        self,
        *,
        device_name: str | None,
        device_index: int | None,
        expected_lag_ms: float | None = None,
        lag_tol_ms: float = 0.5,
    ) -> bool:
        """True if stored calib still matches current capture + optional expected."""
        if not self.known:
            return False
        if device_name is not None and self.capture_device_name is not None:
            if device_name != self.capture_device_name:
                return False
        if device_index is not None and self.capture_index is not None:
            if int(device_index) != int(self.capture_index):
                return False
        if expected_lag_ms is not None and self.lag_offset_ms is not None:
            if abs(float(expected_lag_ms) - float(self.lag_offset_ms)) > lag_tol_ms:
                return False
        return True

    def vision_time_lab(self, frame_monotonic: float) -> float | None:
        """Map frame capture monotonic → lab time aligned for KMH join."""
        if not self.known or self.lag_offset_ms is None:
            return None
        return frame_monotonic - (self.lag_offset_ms / 1000.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LagCalibration:
        if not d:
            return cls()
        return cls(
            lag_offset_ms=d.get("lag_offset_ms"),
            calibrated_at_monotonic=d.get("calibrated_at_monotonic"),
            calibrated_at_utc=d.get("calibrated_at_utc"),
            method=d.get("method") or "flash_or_led",
            capture_device_name=d.get("capture_device_name"),
            capture_index=d.get("capture_index"),
            notes=list(d.get("notes") or []),
        )

    def save(self, path: str | None = None) -> str:
        path = path or DEFAULT_LAG_STORE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
            f.write("\n")
        return path

    @classmethod
    def load(cls, path: str | None = None) -> LagCalibration:
        path = path or DEFAULT_LAG_STORE
        try:
            with open(path, encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError):
            return cls()


def begin_lag_calib_flash(
    *,
    flash_monotonic: float,
    observed_frame_monotonic: float,
    device_name: str | None = None,
    device_index: int | None = None,
) -> LagCalibration:
    """
    One-shot lag from operator flash/LED.

    lag_offset_ms = (observed_frame_monotonic - flash_monotonic) * 1000
    Positive ⇒ vision sees the flash after the lab event (typical encoder buffer).
    """
    lag = LagCalibration()
    lag.mark(
        (observed_frame_monotonic - flash_monotonic) * 1000.0,
        device_name=device_name,
        device_index=device_index,
        method="flash_or_led",
        note="begin_lag_calib_flash",
    )
    return lag


# ---------------------------------------------------------------------------
# Preflight / void-gate check
# ---------------------------------------------------------------------------


@dataclass
class PreflightState:
    """Operator / session state fed into check_void_gates."""

    # Last MAKCU / CH343 serial port (UI auto-detect fallback)
    makcu_port: str | None = None

    # Capture pin
    capture_device_name: str | None = None
    capture_index: int | None = None
    capture_is_elgato: bool = False
    capture_pinned: bool = False  # True only if pin_elgato succeeded by name/VID

    # Live capture health (UI updates these during spin)
    black_frame: bool = False
    hdcp_or_lock: bool = False
    dropped_frames: int = 0

    # Lag
    lag: LagCalibration = field(default_factory=LagCalibration)

    # Flash sheet checklist (UI toggles / operator attest)
    flash_sheet_green: bool = False
    both_bins_flashed: bool = False
    power_cycled: bool = False
    filters_off: bool = False  # steady(0) trim(0,0)

    # Join path
    join_uses_lab_monotonic_plus_lag: bool = True  # must stay True to score
    wall_clock_merge: bool = False

    # ROI / colorspace
    roi_colorspace_stable: bool = True


@dataclass
class VoidCheckResult:
    void: bool
    void_reason: str  # VoidReason value or ""
    reasons: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)  # name → pass?
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "void": self.void,
            "void_reason": self.void_reason or None,
            "reasons": list(self.reasons),
            "gates": dict(self.gates),
            "detail": self.detail,
        }


def check_void_gates(state: PreflightState) -> VoidCheckResult:
    """
    Evaluate Bench §D void gates. Score only when result.void is False.

    Gates (all must pass):
      1. Camera pinned Elgato by name/VID (not bare index 0 assumption)
      2. No black / HDCP / exclusive lock
      3. Dropped frames == 0
      4. Lag offset known
      5. Lag unchanged for current device (implicit via lag.unchanged + pin)
      6. Flash sheet green (both bins + power-cycle + filters off)
      7. No raw dual-PC wall-clock merge
      8. ROI/colorspace stable
    """
    gates: dict[str, bool] = {}
    fails: list[str] = []

    # 1 — pin
    pin_ok = bool(
        state.capture_pinned
        and state.capture_is_elgato
        and state.capture_device_name
    )
    gates[VoidReason.CAMERA_NOT_PINNED.value] = pin_ok
    if not pin_ok:
        fails.append(VoidReason.CAMERA_NOT_PINNED.value)

    # 2 — black / HDCP / lock
    clear_ok = not (state.black_frame or state.hdcp_or_lock)
    gates[VoidReason.BLACK_HDCP_LOCK.value] = clear_ok
    if not clear_ok:
        fails.append(VoidReason.BLACK_HDCP_LOCK.value)

    # 3 — drops
    drops_ok = int(state.dropped_frames) == 0
    gates[VoidReason.DROPPED_FRAMES.value] = drops_ok
    if not drops_ok:
        fails.append(VoidReason.DROPPED_FRAMES.value)

    # 4 — lag known
    lag_known = state.lag.known
    gates[VoidReason.LAG_UNKNOWN.value] = lag_known
    if not lag_known:
        fails.append(VoidReason.LAG_UNKNOWN.value)

    # 5 — lag unchanged for this device
    lag_stable = False
    if lag_known:
        lag_stable = state.lag.unchanged_since(
            device_name=state.capture_device_name,
            device_index=state.capture_index,
        )
    gates[VoidReason.LAG_CHANGED.value] = lag_stable if lag_known else False
    if lag_known and not lag_stable:
        fails.append(VoidReason.LAG_CHANGED.value)

    # 6 — flash sheet
    sheet_ok = bool(
        state.flash_sheet_green
        and state.both_bins_flashed
        and state.power_cycled
        and state.filters_off
    )
    gates[VoidReason.FLASH_SHEET_NOT_GREEN.value] = sheet_ok
    if not sheet_ok:
        fails.append(VoidReason.FLASH_SHEET_NOT_GREEN.value)

    # 7 — join path
    join_ok = bool(
        state.join_uses_lab_monotonic_plus_lag and not state.wall_clock_merge
    )
    gates[VoidReason.WALL_CLOCK_MERGE.value] = join_ok
    if not join_ok:
        fails.append(VoidReason.WALL_CLOCK_MERGE.value)

    # 8 — ROI
    roi_ok = bool(state.roi_colorspace_stable)
    gates[VoidReason.ROI_COLORSPACE_DRIFT.value] = roi_ok
    if not roi_ok:
        fails.append(VoidReason.ROI_COLORSPACE_DRIFT.value)

    void = len(fails) > 0
    if not void:
        reason = VoidReason.NONE.value
    elif len(fails) == 1:
        reason = fails[0]
    else:
        reason = VoidReason.MULTIPLE.value

    detail_parts = [VOID_GATE_HELP.get(r, r) for r in fails]
    return VoidCheckResult(
        void=void,
        void_reason=reason,
        reasons=fails,
        gates=gates,
        detail="; ".join(detail_parts),
    )


def score_allowed(state: PreflightState) -> bool:
    """True only when preflight PASS (no void)."""
    return not check_void_gates(state).void


def preflight_schema_fields(
    state: PreflightState,
    void_result: VoidCheckResult | None = None,
) -> dict[str, Any]:
    """
    Schema v2 fragment for JSON reports:

      void, void_reason, void_reasons, lag_offset_ms,
      capture_device, capture_index, preflight{gates, flash_sheet, ...}
    """
    vr = void_result or check_void_gates(state)
    return {
        "void": vr.void,
        "void_reason": vr.void_reason or None,
        "void_reasons": list(vr.reasons),
        "lag_offset_ms": state.lag.lag_offset_ms,
        "capture_device": state.capture_device_name,
        "capture_index": state.capture_index,
        "preflight": {
            "pass": not vr.void,
            "gates": dict(vr.gates),
            "detail": vr.detail,
            "flash_sheet_green": state.flash_sheet_green,
            "both_bins_flashed": state.both_bins_flashed,
            "power_cycled": state.power_cycled,
            "filters_off": state.filters_off,
            "join_lab_monotonic_plus_lag": state.join_uses_lab_monotonic_plus_lag,
            "wall_clock_merge": state.wall_clock_merge,
            "roi_colorspace_stable": state.roi_colorspace_stable,
            "dropped_frames": state.dropped_frames,
            "black_frame": state.black_frame,
            "hdcp_or_lock": state.hdcp_or_lock,
            "lag": state.lag.to_dict(),
        },
    }



# ---------------------------------------------------------------------------
# Session persistence + Elgato pin (Bench / swipe_ui)
# ---------------------------------------------------------------------------

DEFAULT_PREFLIGHT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "results", "preflight_state.json"
)

_ELGATO_NAME_HINTS = ("elgato", "game capture", "cam link", "4k60", "hd60", "hd60s")


def pin_elgato(
    *,
    device_name: str | None,
    device_index: int | None = None,
    name_hints: tuple[str, ...] = _ELGATO_NAME_HINTS,
) -> tuple[bool, str]:
    """
    Pin capture by Elgato-like name (never silent index 0).
    Returns (ok, detail). On ok, caller sets state.capture_pinned / capture_is_elgato.
    """
    if not device_name or not str(device_name).strip():
        return False, "no device name — refuse bare camera index"
    name = str(device_name).strip()
    lower = name.lower()
    if not any(h in lower for h in name_hints):
        return (
            False,
            f"'{name}' is not Elgato-like — pin by name/VID, not index {device_index}",
        )
    return True, f"pinned '{name}'" + (f" @ index {device_index}" if device_index is not None else "")


def apply_elgato_pin(
    state: PreflightState,
    *,
    device_name: str | None,
    device_index: int | None = None,
) -> tuple[bool, str]:
    ok, detail = pin_elgato(device_name=device_name, device_index=device_index)
    if ok:
        state.capture_device_name = str(device_name).strip()
        state.capture_index = device_index
        state.capture_is_elgato = True
        state.capture_pinned = True
        if state.lag.capture_device_name is None:
            state.lag.capture_device_name = state.capture_device_name
        if device_index is not None and state.lag.capture_index is None:
            state.lag.capture_index = int(device_index)
    else:
        state.capture_pinned = False
        state.capture_is_elgato = False
        state.capture_device_name = device_name
        state.capture_index = device_index
    return ok, detail


def save_preflight_state(state: PreflightState, path: str | None = None) -> str:
    path = path or DEFAULT_PREFLIGHT_STORE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "makcu_port": state.makcu_port,
        "capture_device_name": state.capture_device_name,
        "capture_index": state.capture_index,
        "capture_is_elgato": state.capture_is_elgato,
        "capture_pinned": state.capture_pinned,
        "flash_sheet_green": state.flash_sheet_green,
        "both_bins_flashed": state.both_bins_flashed,
        "power_cycled": state.power_cycled,
        "filters_off": state.filters_off,
        "join_uses_lab_monotonic_plus_lag": state.join_uses_lab_monotonic_plus_lag,
        "wall_clock_merge": state.wall_clock_merge,
        "roi_colorspace_stable": state.roi_colorspace_stable,
        "dropped_frames": state.dropped_frames,
        "black_frame": state.black_frame,
        "hdcp_or_lock": state.hdcp_or_lock,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return path


def load_preflight_state(path: str | None = None) -> PreflightState:
    path = path or DEFAULT_PREFLIGHT_STORE
    st = PreflightState()
    st.lag = LagCalibration.load()
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return st
    for k in (
        "makcu_port",
        "capture_device_name",
        "capture_index",
        "capture_is_elgato",
        "capture_pinned",
        "flash_sheet_green",
        "both_bins_flashed",
        "power_cycled",
        "filters_off",
        "join_uses_lab_monotonic_plus_lag",
        "wall_clock_merge",
        "roi_colorspace_stable",
        "dropped_frames",
        "black_frame",
        "hdcp_or_lock",
    ):
        if k in d:
            setattr(st, k, d[k])
    return st


def mark_flash_sheet_green(
    state: PreflightState,
    *,
    both_bins: bool = True,
    power_cycled: bool = True,
    filters_off: bool = True,
) -> None:
    state.both_bins_flashed = both_bins
    state.power_cycled = power_cycled
    state.filters_off = filters_off
    state.flash_sheet_green = bool(both_bins and power_cycled and filters_off)


if __name__ == "__main__":
    st = PreflightState()
    r = check_void_gates(st)
    print(json.dumps(r.to_dict(), indent=2))
    print("--- schema fields ---")
    print(json.dumps(preflight_schema_fields(st, r), indent=2))
