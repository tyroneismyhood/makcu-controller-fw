"""8 ms accumulator / housekeep drain — port of applyMouseDelta + km_housekeep_cb.

Firmware model (km_inject.c):
  - km.move(dx,dy) → applyMouseDelta adds to g_vel_accum_{x,y}
  - Every KM_HOUSEKEEP_TICK_MS (8) the housekeep callback:
        ax = g_vel_accum_x; ay = g_vel_accum_y
        g_vel_accum_* = 0
        rx_injected = xim_curve(ax); ry_injected = xim_curve(ay)
  - Mouse stops → no events → next drain produces zero → stick neutral.
  - No decay, no carryover, no rate-limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .curve import xim_curve

HOUSEKEEP_TICK_MS: int = 8
STALE_RELEASE_MS: int = 500


@dataclass
class Accumulator:
    """Per-tick velocity accumulator drained every HOUSEKEEP_TICK_MS."""

    accum_x: int = 0
    accum_y: int = 0
    injected_x: int = 0
    injected_y: int = 0
    tick: int = 0
    # Diagnostic: last drained raw accum before curve
    last_ax: int = 0
    last_ay: int = 0
    history: list = field(default_factory=list)

    def apply_mouse_delta(self, dx: int, dy: int) -> None:
        """Firmware applyMouseDelta — sum into velocity accumulator."""
        self.accum_x += int(dx)
        self.accum_y += int(dy)

    def drain(self) -> tuple[int, int]:
        """One housekeep tick: curve then zero accumulator. Returns (ix, iy)."""
        ax, ay = self.accum_x, self.accum_y
        self.accum_x = 0
        self.accum_y = 0
        self.last_ax, self.last_ay = ax, ay
        self.injected_x = xim_curve(ax)
        self.injected_y = xim_curve(ay)
        self.tick += 1
        self.history.append(
            {
                "tick": self.tick,
                "ax": ax,
                "ay": ay,
                "ix": self.injected_x,
                "iy": self.injected_y,
            }
        )
        return self.injected_x, self.injected_y

    def reset(self) -> None:
        self.accum_x = self.accum_y = 0
        self.injected_x = self.injected_y = 0
        self.last_ax = self.last_ay = 0
        # keep tick / history for session diagnostics unless caller clears
