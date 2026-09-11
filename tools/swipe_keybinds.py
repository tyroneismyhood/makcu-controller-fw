#!/usr/bin/env python3
"""
Swipe Lab UI keybinds contract (Tools lock).

Dylan lock (ROI/detector) + prior Swipe Lab actions.
Peer HUD/scorer must import KEYBINDS / WAITKEY_MAP — do not invent a second map.

  from swipe_keybinds import KEYBINDS, WAITKEY_MAP, action_for_waitkey
"""

from __future__ import annotations

from typing import TypedDict


class Keybind(TypedDict):
    key: str
    action: str
    help: str


# Canonical product keybinds for tools/swipe_ui.py (OpenCV waitKey / HUD).
# LOCKED by Dylan: r = ROI, d = detector cycle, mouse click = lock target in ROI.
KEYBINDS: tuple[Keybind, ...] = (
    {"key": "o", "action": "run_objective", "help": "run objective KMH curve suite (8/80/240→stop)"},
    {"key": "r", "action": "set_roi", "help": "set/search ROI (search region for YOLO/target)"},
    {"key": "d", "action": "cycle_detector", "help": "cycle/toggle detector (yolov8n / onnx)"},
    {"key": "click", "action": "lock_target", "help": "mouse click = lock target in ROI"},
    {"key": "i", "action": "rest_idle_dz", "help": "rest idle_dz measure (+ show suggested N)"},
    {"key": "a", "action": "run_all", "help": "run all tests + YOLO T0/T1 + save results"},
    {"key": "y", "action": "apply_idle_dz", "help": "apply suggested idle_dz"},
    {"key": "h", "action": "hip_360", "help": "hip 360 pulse (look=2 reminder)"},
    {"key": "m", "action": "ads_360", "help": "ADS 360 pulse (aim=1.50, hold km.right)"},
    {"key": "[", "action": "total_dec", "help": "adjust current mode TOTAL −15%"},
    {"key": "]", "action": "total_inc", "help": "adjust current mode TOTAL +15%"},
    {"key": "u", "action": "feel_under", "help": "mark last 360 as under"},
    {"key": "v", "action": "feel_over", "help": "mark last 360 as over"},
    {"key": "k", "action": "feel_ok", "help": "mark last 360 as ok"},
    {"key": "p", "action": "game_pulse", "help": "game-pulse horizontal burst"},
    {"key": "s", "action": "save_results", "help": "save JSON+txt results (schema v2)"},
    {"key": "c", "action": "reconnect_port", "help": "reconnect / pick serial port (prefer CH343)"},
    {"key": "e", "action": "cycle_capture", "help": "cycle Elgato/capture device"},
    {"key": "l", "action": "lag_calib", "help": "capture lag calib (flash/LED vs lab monotonic)"},
    {"key": "f", "action": "preflight_check", "help": "run void-gate preflight checklist"},
    {"key": "g", "action": "toggle_flash_sheet", "help": "toggle flash-sheet-green checklist bit"},
    {"key": "0", "action": "snap_t0", "help": "snap YOLO/target T0 in ROI (before 360)"},
    {"key": "1", "action": "snap_t1", "help": "snap YOLO/target T1 in ROI (after 360)"},
    {"key": "q", "action": "quit", "help": "quit (release ADS if held)"},
    {"key": "esc", "action": "quit", "help": "quit (release ADS if held)"},
)

# OpenCV waitKey codes (lowercase letters); Esc = 27
# Note: mouse click is handled via setMouseCallback — not waitKey.
WAITKEY_MAP: dict[int, str] = {
    ord("o"): "run_objective",
    ord("r"): "set_roi",
    ord("d"): "cycle_detector",
    ord("i"): "rest_idle_dz",
    ord("a"): "run_all",
    ord("y"): "apply_idle_dz",
    ord("h"): "hip_360",
    ord("m"): "ads_360",
    ord("["): "total_dec",
    ord("]"): "total_inc",
    ord("u"): "feel_under",
    ord("v"): "feel_over",
    ord("k"): "feel_ok",
    ord("p"): "game_pulse",
    ord("s"): "save_results",
    ord("c"): "reconnect_port",
    ord("e"): "cycle_capture",
    ord("l"): "lag_calib",
    ord("f"): "preflight_check",
    ord("g"): "toggle_flash_sheet",
    ord("0"): "snap_t0",
    ord("1"): "snap_t1",
    ord("q"): "quit",
    27: "quit",  # Esc
}

# Remap notes (breaking vs earlier draft):
#   r was rest_idle_dz → now set_roi (Dylan lock); rest moved to i
#   d was ads_360 → now cycle_detector (Dylan lock); ADS moved to m


def keybind_help_lines() -> list[str]:
    """On-screen HUD lines for the keybind legend."""
    return [f"  {kb['key']}: {kb['help']}" for kb in KEYBINDS]


def action_for_waitkey(code: int) -> str | None:
    """Map OpenCV waitKey code → action name, or None."""
    if code < 0:
        return None
    if 65 <= code <= 90:  # A-Z → a-z
        code = code + 32
    return WAITKEY_MAP.get(code)


if __name__ == "__main__":
    for line in keybind_help_lines():
        print(line)
