"""In-process km.* shim — same semantics as UART text parser in km_inject.c.

Supported (Class 2 / Track B):
  km.move(dx, dy)              — sum into accumulator
  km.move_auto / km.move_bezier — collapse to move (duration/path ignored)
  km.click(btn)                — btn 0=L(RT/fire), 1=R(LT/ADS), 2=M(X)
  km.left/right/middle(0|1)
  km.btnA/B/X/Y(0|1), km.lb/rb(0|1)
  km.idle_dz(N)
  km.steady(0|1), km.steady_a(N), km.steady_d(N)
  km.trim(x, y)
  km.version()

Unsupported (silently ignored, matching firmware): km.moveto, km.aim_mode.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .sim import SoftMakcu

# Generic button bits — match km_inject.c
BTN_A = 0x0001
BTN_B = 0x0002
BTN_X = 0x0004
BTN_Y = 0x0008
BTN_LB = 0x0010
BTN_RB = 0x0020
BTN_FIRE = 0x0040  # RT analog-1 (mouse left)
BTN_ADS = 0x0080  # LT analog-1 (mouse right)

CLICK_HOLD_MS = 120


class KmApi:
    """Callable object API + text-line parser matching firmware parse_km_text."""

    def __init__(self, engine: "SoftMakcu"):
        self._eng = engine

    # ---- object API --------------------------------------------------------

    def move(self, dx: int, dy: int, *_ignored) -> None:
        self._eng.apply_mouse_delta(int(dx), int(dy))

    def move_auto(self, dx: int, dy: int, *_ignored) -> None:
        self.move(dx, dy)

    def move_bezier(self, dx: int, dy: int, *_ignored) -> None:
        self.move(dx, dy)

    def click(self, btn: int = 0, _cnt: int = 1) -> None:
        mask = {0: BTN_FIRE, 1: BTN_ADS, 2: BTN_X}.get(int(btn), 0)
        if mask:
            self._eng.btn_pulse(mask)

    def left(self, on: int) -> None:
        self._eng.btn_hold(BTN_FIRE, bool(on))

    def right(self, on: int) -> None:
        self._eng.btn_hold(BTN_ADS, bool(on))

    def middle(self, on: int) -> None:
        self._eng.btn_hold(BTN_X, bool(on))

    def btnA(self, on: int) -> None:
        self._eng.btn_hold(BTN_A, bool(on))

    def btnB(self, on: int) -> None:
        self._eng.btn_hold(BTN_B, bool(on))

    def btnX(self, on: int) -> None:
        self._eng.btn_hold(BTN_X, bool(on))

    def btnY(self, on: int) -> None:
        self._eng.btn_hold(BTN_Y, bool(on))

    def lb(self, on: int) -> None:
        self._eng.btn_hold(BTN_LB, bool(on))

    def rb(self, on: int) -> None:
        self._eng.btn_hold(BTN_RB, bool(on))

    def idle_dz(self, n: int) -> None:
        v = max(0, min(32000, int(n)))
        self._eng.idle_dz = v

    def steady(self, on: int) -> None:
        self._eng.steady_on = bool(on)

    def steady_a(self, n: int) -> None:
        self._eng.steady_alpha = max(0, min(99, int(n)))

    def steady_d(self, n: int) -> None:
        self._eng.steady_dead = max(0, min(32000, int(n)))

    def trim(self, x: int, y: int) -> None:
        self._eng.trim_x = max(-32767, min(32767, int(x)))
        self._eng.trim_y = max(-32767, min(32767, int(y)))

    def version(self) -> str:
        return "kmbox:   1.0.0 SoftMAKCU (host sim)\r\n>>> "

    # ---- text parser -------------------------------------------------------

    def ingest_line(self, line: str) -> Optional[str]:
        """Parse one ASCII km.* line. Returns response string if any."""
        buf = line.strip()
        if not buf:
            return None

        if buf.startswith("km.version("):
            return self.version()

        m = re.match(r"km\.steady_a\((-?\d+)\)", buf)
        if m:
            self.steady_a(int(m.group(1)))
            return None
        m = re.match(r"km\.steady_d\((-?\d+)\)", buf)
        if m:
            self.steady_d(int(m.group(1)))
            return None
        m = re.match(r"km\.steady\((-?\d+)\)", buf)
        if m:
            self.steady(int(m.group(1)))
            return None
        m = re.match(r"km\.idle_dz\((-?\d+)\)", buf)
        if m:
            self.idle_dz(int(m.group(1)))
            return None
        m = re.match(r"km\.trim\((-?\d+)\s*,\s*(-?\d+)\)", buf)
        if m:
            self.trim(int(m.group(1)), int(m.group(2)))
            return None

        m = re.match(
            r"km\.(?:move|move_auto|move_bezier)\((-?\d+)\s*,\s*(-?\d+)",
            buf,
        )
        if m:
            self.move(int(m.group(1)), int(m.group(2)))
            return None

        m = re.match(r"km\.click\((-?\d+)", buf)
        if m:
            self.click(int(m.group(1)))
            return None

        for name, fn in (
            ("left", self.left),
            ("right", self.right),
            ("middle", self.middle),
            ("btnA", self.btnA),
            ("btnB", self.btnB),
            ("btnX", self.btnX),
            ("btnY", self.btnY),
            ("lb", self.lb),
            ("rb", self.rb),
        ):
            m = re.match(rf"km\.{name}\(([01])", buf)
            if m:
                fn(int(m.group(1)))
                return None

        # Unsupported: km.moveto, km.aim_mode — silently ignored
        return None
