#!/usr/bin/env python3
"""Soft MAKCU Lab UI — OpenCV host sim (Class 3). Never flashes hardware.

Usage:
  python -m soft_makcu
  python soft_makcu/lab_ui.py
  python tools/soft_makcu/lab_ui.py   # if installed as tools symlink

Controls:
  Mouse drag on left pad     — inject Δ as km.move (per frame, scaled)
  Sliders / keys             — inject fixed accum magnitudes
  H / A                      — run hip / ADS synthetic 360 totals
  [ ]                        — nudge total_hip ±50
  ; '                        — nudge total_ads ±50
  D / d                      — idle_dz ±100
  E                          — export profile JSON
  R                          — reset injection
  Q / ESC                    — quit

Safety: this process never opens esptool, never writes firmware partitions.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Allow `python soft_makcu/lab_ui.py` and `python -m soft_makcu`
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from soft_makcu.curve import KM_GAIN_C, KM_GAIN_P, RAIL, xim_curve  # noqa: E402
from soft_makcu.drain import HOUSEKEEP_TICK_MS  # noqa: E402
from soft_makcu.sim import SoftMakcu  # noqa: E402

WIN = "Soft MAKCU Lab (Class 3 — never flashes)"
W, H = 960, 640
STICK_R = 120
PAD_ORIGIN = (180, 320)
MERGED_ORIGIN = (480, 320)
PHYS_ORIGIN = (780, 320)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _draw_stick(img, origin, x, y, label, color):
    ox, oy = origin
    cv2.circle(img, (ox, oy), STICK_R, (60, 60, 60), 2)
    cv2.line(img, (ox - STICK_R, oy), (ox + STICK_R, oy), (40, 40, 40), 1)
    cv2.line(img, (ox, oy - STICK_R), (ox, oy + STICK_R), (40, 40, 40), 1)
    # Map ±32767 → circle; mouse convention +y = down matches image y+
    px = int(ox + (x / RAIL) * (STICK_R - 4))
    py = int(oy + (y / RAIL) * (STICK_R - 4))
    cv2.circle(img, (px, py), 8, color, -1)
    cv2.putText(
        img,
        label,
        (ox - STICK_R, oy - STICK_R - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (200, 200, 200),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        img,
        f"x={x:+6d}  y={y:+6d}",
        (ox - STICK_R, oy + STICK_R + 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        color,
        1,
        cv2.LINE_AA,
    )


def _hud(img, eng: SoftMakcu, status: str):
    st = eng.state
    lines = [
        "SOFT MAKCU  |  Class 3 host sim  |  NEVER FLASHES",
        f"curve C={KM_GAIN_C:g} P={KM_GAIN_P:.2f}  tick={HOUSEKEEP_TICK_MS}ms  rail=±{RAIL}",
        f"tick={st.tick}  ax={st.ax:+d} ay={st.ay:+d}  ix={st.ix:+d} iy={st.iy:+d}",
        f"mrx={st.mrx:+d} mry={st.mry:+d}  buttons=0x{st.buttons:04x}  idle_dz={eng.idle_dz}",
        f"total_hip={eng.profile.total_hip}  total_ads={eng.profile.total_ads}  chunk={eng.profile.chunk_dx}",
        f"golden ix@8={xim_curve(8)}  @80={xim_curve(80)}  @240={xim_curve(240)}",
        status,
        "keys: drag pad | 1/2/3=mag 8/80/240 | H/A=hip/ads | [] hip | ;' ads | E=export | R=reset | Q=quit",
    ]
    y = 22
    for i, line in enumerate(lines):
        col = (0, 220, 255) if i == 0 else (180, 180, 180)
        if i == 6:
            col = (80, 255, 80)
        cv2.putText(img, line, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1, cv2.LINE_AA)
        y += 20


class LabApp:
    def __init__(self, eng: SoftMakcu):
        self.eng = eng
        self.status = "ready — drag left pad or press 1/2/3"
        self.dragging = False
        self.last_mx = 0
        self.last_my = 0
        self.scale = 1.0  # mouse px → km.move counts
        self.export_dir = Path("soft_makcu/exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def on_mouse(self, event, x, y, flags, _param):
        ox, oy = PAD_ORIGIN
        if event == cv2.EVENT_LBUTTONDOWN:
            if (x - ox) ** 2 + (y - oy) ** 2 <= (STICK_R + 20) ** 2:
                self.dragging = True
                self.last_mx, self.last_my = x, y
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging:
            dx = int((x - self.last_mx) * self.scale)
            dy = int((y - self.last_my) * self.scale)
            self.last_mx, self.last_my = x, y
            if dx or dy:
                self.eng.km.move(dx, dy)
                self.status = f"inject move({dx:+d},{dy:+d})"
        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False

    def inject_mag(self, mag: int):
        self.eng.km.move(mag, 0)
        self.status = f"inject accum x={mag} → expect ix={xim_curve(mag)}"

    def run_total(self, which: str):
        """Chunk a hip/ADS total across 8 ms ticks (synthetic 360 feel)."""
        total = self.eng.profile.total_hip if which == "hip" else self.eng.profile.total_ads
        chunk = max(1, self.eng.profile.chunk_dx)
        remaining = total
        peaks = []
        while remaining > 0:
            dx = min(chunk, remaining)
            self.eng.km.move(dx, 0)
            st = self.eng.tick()
            peaks.append(st.ix)
            remaining -= dx
        # drain idle to zero
        for _ in range(3):
            self.eng.tick()
        peak = max(peaks) if peaks else 0
        self.status = (
            f"{which} total={total} chunk={chunk} peak_ix={peak} "
            f"(rail={'YES' if peak >= RAIL else 'no'})"
        )

    def export(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.export_dir / f"soft_makcu_profile_{ts}.json"
        self.eng.export_profile(path)
        self.status = f"exported {path} (for later flash — Soft MAKCU never flashes)"

    def frame(self) -> np.ndarray:
        # If wall ticker not running, advance one tick so viz updates
        if not (self.eng._ticker and self.eng._ticker.is_alive()):
            self.eng.tick()
        img = np.zeros((H, W, 3), dtype=np.uint8)
        img[:] = (24, 24, 28)
        st = self.eng.state
        _draw_stick(img, PAD_ORIGIN, st.ix, st.iy, "INJECTED (post xim_curve)", (0, 200, 255))
        _draw_stick(img, MERGED_ORIGIN, st.mrx, st.mry, "MERGED (blend_stick)", (80, 255, 120))
        _draw_stick(img, PHYS_ORIGIN, st.px, st.py, "PHYSICAL (sim pad)", (200, 160, 80))
        _hud(img, self.eng, self.status)
        # Track bar visual for hip/ads
        cv2.rectangle(img, (16, H - 48), (W - 16, H - 16), (50, 50, 55), -1)
        hip_w = int((W - 40) * _clamp(self.eng.profile.total_hip / 4800, 0, 1))
        ads_w = int((W - 40) * _clamp(self.eng.profile.total_ads / 4800, 0, 1))
        cv2.rectangle(img, (20, H - 44), (20 + hip_w, H - 34), (0, 180, 255), -1)
        cv2.rectangle(img, (20, H - 28), (20 + ads_w, H - 18), (0, 220, 120), -1)
        return img


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Soft MAKCU Lab UI (Class 3 — never flashes)")
    parser.add_argument("--no-display", action="store_true", help="Smoke headless (one frame dump)")
    parser.add_argument("--hip", type=int, default=None, help="Override total_hip")
    parser.add_argument("--ads", type=int, default=None, help="Override total_ads")
    args = parser.parse_args(argv)

    eng = SoftMakcu()
    if args.hip is not None:
        eng.profile.total_hip = args.hip
    if args.ads is not None:
        eng.profile.total_ads = args.ads

    app = LabApp(eng)

    if args.no_display or os.environ.get("SOFT_MAKCU_HEADLESS"):
        eng.km.move(8, 0)
        eng.tick()
        eng.km.move(80, 0)
        eng.tick()
        eng.km.move(240, 0)
        st = eng.tick()
        out = Path("soft_makcu/exports")
        out.mkdir(parents=True, exist_ok=True)
        frame = app.frame()
        path = out / "headless_smoke.png"
        cv2.imwrite(str(path), frame)
        print(f"Soft MAKCU headless smoke OK  last ix={st.ix}  frame={path}")
        print(f"golden: 8→{xim_curve(8)} 80→{xim_curve(80)} 240→{xim_curve(240)}")
        return 0

    eng.start(HOUSEKEEP_TICK_MS)
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WIN, app.on_mouse)

    try:
        while True:
            frame = app.frame()
            cv2.imshow(WIN, frame)
            key = cv2.waitKey(8) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                break
            elif key == ord("1"):
                app.inject_mag(8)
            elif key == ord("2"):
                app.inject_mag(80)
            elif key == ord("3"):
                app.inject_mag(240)
            elif key in (ord("h"), ord("H")):
                app.run_total("hip")
            elif key in (ord("a"), ord("A")):
                app.run_total("ads")
            elif key == ord("["):
                eng.profile.total_hip = max(100, eng.profile.total_hip - 50)
                app.status = f"total_hip={eng.profile.total_hip}"
            elif key == ord("]"):
                eng.profile.total_hip = min(20000, eng.profile.total_hip + 50)
                app.status = f"total_hip={eng.profile.total_hip}"
            elif key == ord(";"):
                eng.profile.total_ads = max(100, eng.profile.total_ads - 50)
                app.status = f"total_ads={eng.profile.total_ads}"
            elif key == ord("'"):
                eng.profile.total_ads = min(20000, eng.profile.total_ads + 50)
                app.status = f"total_ads={eng.profile.total_ads}"
            elif key == ord("D"):
                eng.idle_dz = min(32000, eng.idle_dz + 100)
                app.status = f"idle_dz={eng.idle_dz}"
            elif key == ord("d"):
                eng.idle_dz = max(0, eng.idle_dz - 100)
                app.status = f"idle_dz={eng.idle_dz}"
            elif key in (ord("e"), ord("E")):
                app.export()
            elif key in (ord("r"), ord("R")):
                eng.reset()
                app.status = "reset"
    finally:
        eng.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
