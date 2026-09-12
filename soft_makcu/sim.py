"""SoftMakcu engine — host-only Class 3 virtual MAKCU ticking at 8 ms.

Combines Accumulator drain, blend_stick, idle_dz/clean_idle, and button
latches. Optional wall-clock ticker thread; lab UI / tests can also call
tick() manually for deterministic sims.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .blend import (
    blend_stick,
    clamp_s16,
    compute_merged_stick,
    physical_deadzone_clean,
)
from .curve import KM_GAIN_C, KM_GAIN_P, RAIL, xim_curve
from .drain import HOUSEKEEP_TICK_MS, STALE_RELEASE_MS, Accumulator
from .km_api import CLICK_HOLD_MS, KmApi


@dataclass
class StickState:
    """Live stick snapshot after last tick (mouse convention: +ry = down)."""

    ix: int = 0  # injected (post-curve)
    iy: int = 0
    px: int = 0  # physical (post idle_dz if inj live)
    py: int = 0
    mrx: int = 0  # merged
    mry: int = 0
    buttons: int = 0
    tick: int = 0
    ax: int = 0  # raw accum drained this tick
    ay: int = 0


@dataclass
class CalibProfile:
    """Hip / ADS totals for later flash — Soft MAKCU never flashes itself."""

    total_hip: int = 2400
    total_ads: int = 1800
    chunk_dx: int = 120
    idle_dz: int = 0
    C: float = KM_GAIN_C
    P: float = KM_GAIN_P
    note: str = "Soft MAKCU host calib — apply manually to sender / Track B tools"

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")


class SoftMakcu:
    """Main-PC-only virtual MAKCU. Never opens serial, never flashes."""

    def __init__(self):
        self.accum = Accumulator()
        self.km = KmApi(self)
        self.idle_dz: int = 0
        self.steady_on: bool = False
        self.steady_alpha: int = 70
        self.steady_dead: int = 6000
        self.steady_fx: int = 0
        self.steady_fy: int = 0
        self.trim_x: int = 0
        self.trim_y: int = 0
        self.btn_held: int = 0
        self.btn_click: int = 0
        self.click_release_ms: float = 0.0
        self.physical_x: int = 0
        self.physical_y: int = 0
        self.last_cmd_ms: float = 0.0
        self.state = StickState()
        self.profile = CalibProfile()
        self._lock = threading.Lock()
        self._ticker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._started_mono: float = 0.0

    # ---- km injection path -------------------------------------------------

    def apply_mouse_delta(self, dx: int, dy: int) -> None:
        with self._lock:
            self.accum.apply_mouse_delta(dx, dy)
            self.last_cmd_ms = self._now_ms()

    def btn_hold(self, mask: int, on: bool) -> None:
        with self._lock:
            if on:
                self.btn_held |= mask
            else:
                self.btn_held &= ~mask
            self.last_cmd_ms = self._now_ms()

    def btn_pulse(self, mask: int) -> None:
        with self._lock:
            self.btn_click = mask
            self.click_release_ms = self._now_ms() + CLICK_HOLD_MS
            self.last_cmd_ms = self._now_ms()

    def set_physical(self, rx: int, ry: int) -> None:
        """Simulate a real controller right stick (mouse convention)."""
        with self._lock:
            self.physical_x = int(rx)
            self.physical_y = int(ry)

    def _now_ms(self) -> float:
        if self._started_mono:
            return (time.monotonic() - self._started_mono) * 1000.0
        return time.monotonic() * 1000.0

    def _has_active_injection(self) -> bool:
        if self.accum.injected_x or self.accum.injected_y:
            return True
        if self.btn_held or self.btn_click:
            return True
        return False

    def _steady_apply(self, rx: int, ry: int) -> tuple[int, int]:
        a = self.steady_alpha
        d = self.steady_dead
        self.steady_fx = (a * self.steady_fx + (100 - a) * rx) // 100
        self.steady_fy = (a * self.steady_fy + (100 - a) * ry) // 100
        return self._steady_dz(self.steady_fx, d), self._steady_dz(self.steady_fy, d)

    @staticmethod
    def _steady_dz(v: int, dz: int) -> int:
        if dz <= 0:
            return v
        a = -v if v < 0 else v
        if a <= dz:
            return 0
        out = (a - dz) * 32767 // (32767 - dz)
        return -out if v < 0 else out

    def tick(self) -> StickState:
        """One 8 ms housekeep + merge. Deterministic when called manually."""
        with self._lock:
            now = self._now_ms()
            # Stale release safety net
            if self.last_cmd_ms and (now - self.last_cmd_ms) > STALE_RELEASE_MS:
                self.accum.injected_x = 0
                self.accum.injected_y = 0
                self.accum.accum_x = 0
                self.accum.accum_y = 0

            ix, iy = self.accum.drain()
            ax, ay = self.accum.last_ax, self.accum.last_ay

            if self.click_release_ms and now >= self.click_release_ms:
                self.btn_click = 0
                self.click_release_ms = 0.0

            inj_live = bool(ix or iy or self.btn_held or self.btn_click)
            px, py = self.physical_x, self.physical_y
            if inj_live:
                px = physical_deadzone_clean(px, self.idle_dz)
                py = physical_deadzone_clean(py, self.idle_dz)
            px += self.trim_x
            py += self.trim_y
            if self.steady_on:
                px, py = self._steady_apply(px, py)

            mrx, mry = compute_merged_stick(px, py, ix, iy)
            buttons = self.btn_held | self.btn_click

            self.state = StickState(
                ix=ix,
                iy=iy,
                px=px,
                py=py,
                mrx=mrx,
                mry=mry,
                buttons=buttons,
                tick=self.accum.tick,
                ax=ax,
                ay=ay,
            )
            return self.state

    def reset(self) -> None:
        with self._lock:
            self.accum.reset()
            self.accum.tick = 0
            self.accum.history.clear()
            self.btn_held = self.btn_click = 0
            self.click_release_ms = 0.0
            self.steady_fx = self.steady_fy = 0
            self.state = StickState()

    # ---- wall-clock ticker -------------------------------------------------

    def start(self, tick_ms: float = HOUSEKEEP_TICK_MS) -> None:
        if self._ticker and self._ticker.is_alive():
            return
        self._stop.clear()
        self._started_mono = time.monotonic()
        period = tick_ms / 1000.0

        def _loop() -> None:
            next_t = time.monotonic()
            while not self._stop.is_set():
                self.tick()
                next_t += period
                sleep = next_t - time.monotonic()
                if sleep > 0:
                    self._stop.wait(sleep)
                else:
                    next_t = time.monotonic()

        self._ticker = threading.Thread(target=_loop, name="soft-makcu", daemon=True)
        self._ticker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ticker:
            self._ticker.join(timeout=1.0)
            self._ticker = None

    def export_profile(self, path: str | Path) -> CalibProfile:
        self.profile.idle_dz = self.idle_dz
        self.profile.save(path)
        return self.profile
