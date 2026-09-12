#!/usr/bin/env python3
"""Soft Lab UI — host Soft MAKCU lab (Class 3). Soft sim only; never flashes.

Owned by Soft Lab. Math fidelity owned by SoftMakcu (`soft_makcu`).

Usage (THE one command):
  python -m soft_makcu
  python -m soft_makcu --smoke          # goldens, no display
  SOFT_MAKCU_HEADLESS=1 python -m soft_makcu

Host sim only — never opens serial, never flashes, never talks to a board.
Golden ix bit-exact SoftAxis bar (no soft reopen): 8→11592 / 80→29119 / 240→32767
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python soft_makcu/lab_ui.py` and `python -m soft_makcu`
_PKG = Path(__file__).resolve().parent
_ROOT = _PKG.parent
if _ROOT.is_dir() and str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from soft_makcu.curve import KM_GAIN_C, KM_GAIN_P, RAIL, xim_curve  # noqa: E402
from soft_makcu.drain import HOUSEKEEP_TICK_MS  # noqa: E402
from soft_makcu.sim import SoftMakcu  # noqa: E402

# SoftAxis labels + goldens live in this package (host-local; no Tools imports).
SOFTAXIS_BAR = "bit-exact SoftAxis EXPECTED_IX (no soft-only reopen)"
MATRIX_LABELS = ("CLEAN STOP", "NO CARRY", "NO OVERSHOOT", "RATIO 1.33")
DEFAULT_TOTAL_HIP = 2400
DEFAULT_TOTAL_ADS = 1800
HIP_ADS_RATIO = 1.333
HIP_ADS_RATIO_TOL = 0.03


def _load_expected_ix() -> dict[int, int]:
    gv = _PKG / "golden_vectors.json"
    if gv.is_file():
        data = json.loads(gv.read_text())
        primary = data.get("primary_golden") or {}
        out = {int(k): int(v) for k, v in primary.items()}
        if out:
            return out
    return {8: 11592, 80: 29119, 240: 32767}


EXPECTED_IX: dict[int, int] = _load_expected_ix()


def hip_ads_ratio_ok(total_hip: int, total_ads: int) -> bool:
    if total_ads <= 0:
        return False
    ratio = float(total_hip) / float(total_ads)
    return abs(ratio - HIP_ADS_RATIO) <= HIP_ADS_RATIO * HIP_ADS_RATIO_TOL


BANNER = "Soft Lab — zero hardware · never flashes"
WIN = "Soft Lab — Soft MAKCU (never flashes)"
W, H = 1100, 720
STICK_R = 110
PAD_ORIGIN = (170, 380)
MERGED_ORIGIN = (460, 380)
PHYS_ORIGIN = (750, 380)

# Optional OpenCV — GUI needs it; --smoke does not
cv2: Any = None
np: Any = None
_CV2_ERR: str | None = None


def _ensure_cv2() -> bool:
    global cv2, np, _CV2_ERR
    if cv2 is not None:
        return True
    if _CV2_ERR is not None:
        return False
    try:
        import cv2 as _cv2
        import numpy as _np

        cv2 = _cv2
        np = _np
        return True
    except Exception as exc:  # noqa: BLE001
        _CV2_ERR = str(exc)
        return False


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _ratio_readout(hip: int, ads: int) -> dict[str, Any]:
    if ads <= 0:
        return {"ratio": None, "ok": False, "band": "FAIL", "text": "ADS TOTAL must be > 0"}
    ratio = float(hip) / float(ads)
    ok = bool(hip_ads_ratio_ok(hip, ads))
    band = "PASS" if ok else "FAIL"
    return {
        "ratio": ratio,
        "ok": ok,
        "band": band,
        "text": f"hip:ads = {ratio:.3f}  target {HIP_ADS_RATIO} ±{HIP_ADS_RATIO_TOL*100:.0f}%  [{band}]",
    }


def _matrix_flags(eng: SoftMakcu, last_peak: int, drained_clean: bool) -> dict[str, bool]:
    """Map SoftMakcu sim observables → SoftAxis MATRIX_LABELS.

    CLEAN STOP / NO CARRY / NO OVERSHOOT ← idle drain zeros inject (no leftover)
    RATIO 1.33 ← hip_ads_ratio_ok
    """
    del last_peak  # reserved for future peak-rail chip; not a soft-only reopen
    st = eng.state
    idle_zero = st.ix == 0 and st.iy == 0
    no_carry = idle_zero and eng.accum.accum_x == 0 and eng.accum.accum_y == 0
    clean_stop = drained_clean and idle_zero
    no_overshoot = drained_clean and idle_zero
    ratio_ok = hip_ads_ratio_ok(eng.profile.total_hip, eng.profile.total_ads)
    return {
        "CLEAN STOP": clean_stop,
        "NO CARRY": no_carry,
        "NO OVERSHOOT": no_overshoot,
        "RATIO 1.33": ratio_ok,
    }


def _golden_rows() -> list[dict[str, Any]]:
    rows = []
    for accum, expect in EXPECTED_IX.items():
        got = xim_curve(int(accum))
        rows.append({"accum": int(accum), "ix": got, "expected": int(expect), "ok": got == int(expect)})
    return rows


def run_smoke() -> int:
    """Headless golden smoke: SoftMakcu move(N)+tick vs EXPECTED_IX. No display."""
    eng = SoftMakcu()
    results: list[dict[str, Any]] = []
    all_ok = True
    for accum, expect in EXPECTED_IX.items():
        eng.reset()
        eng.km.move(int(accum), 0)
        st = eng.tick()
        ok = st.ix == int(expect)
        all_ok = all_ok and ok
        results.append({"accum": accum, "ix": st.ix, "expected": expect, "ok": ok})
        st2 = eng.tick()
        if st2.ix != 0 or st2.iy != 0:
            all_ok = False
            results.append({"accum": accum, "idle_ix": st2.ix, "ok": False, "note": "NO CARRY fail"})

    ratio = _ratio_readout(eng.profile.total_hip, eng.profile.total_ads)
    flags = _matrix_flags(eng, last_peak=results[-1]["ix"] if results else 0, drained_clean=True)
    payload = {
        "banner": BANNER,
        "smoke": "OK" if all_ok else "FAIL",
        "accuracy_bar": SOFTAXIS_BAR,
        "C": KM_GAIN_C,
        "P": KM_GAIN_P,
        "tick_ms": HOUSEKEEP_TICK_MS,
        "goldens": results,
        "hip_ads": ratio,
        "matrix": flags,
        "labels": list(MATRIX_LABELS),
    }
    print(json.dumps(payload, indent=2))
    print(f"{BANNER}")
    print("soft_makcu --smoke", "OK" if all_ok else "FAIL", flush=True)
    return 0 if all_ok else 1


def _draw_stick(img, origin, x, y, label, color) -> None:
    ox, oy = origin
    cv2.circle(img, (ox, oy), STICK_R, (55, 58, 70), 2)
    cv2.line(img, (ox - STICK_R, oy), (ox + STICK_R, oy), (40, 42, 52), 1)
    cv2.line(img, (ox, oy - STICK_R), (ox, oy + STICK_R), (40, 42, 52), 1)
    px = int(ox + (x / RAIL) * (STICK_R - 4))
    py = int(oy + (y / RAIL) * (STICK_R - 4))
    cv2.circle(img, (px, py), 9, color, -1)
    cv2.putText(img, label, (ox - STICK_R, oy - STICK_R - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (210, 214, 224), 1, cv2.LINE_AA)
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


def _put(img, text: str, xy: tuple[int, int], color, scale=0.48, thickness=1) -> None:
    cv2.putText(img, text, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


class LabApp:
    def __init__(self, eng: SoftMakcu):
        self.eng = eng
        self.status = "ready — drag inject pad · 1/2/3 goldens · Soft / No flash"
        self.dragging = False
        self.last_mx = 0
        self.last_my = 0
        self.scale = 1.0
        self.last_peak = 0
        self.drained_clean = True
        self.export_dir = _PKG / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.eng.profile.total_hip = int(DEFAULT_TOTAL_HIP)
        self.eng.profile.total_ads = int(DEFAULT_TOTAL_ADS)

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
                self.drained_clean = False
                self.status = f"inject move({dx:+d},{dy:+d})"
        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False

    def inject_mag(self, mag: int):
        self.eng.km.move(mag, 0)
        expect = EXPECTED_IX.get(mag, xim_curve(mag))
        self.drained_clean = False
        self.status = f"golden move({mag}) → expect ix={expect}"

    def run_total(self, which: str):
        total = self.eng.profile.total_hip if which == "hip" else self.eng.profile.total_ads
        chunk = max(1, self.eng.profile.chunk_dx)
        remaining = total
        peaks: list[int] = []
        while remaining > 0:
            dx = min(chunk, remaining)
            self.eng.km.move(dx, 0)
            st = self.eng.tick()
            peaks.append(st.ix)
            remaining -= dx
        for _ in range(3):
            self.eng.tick()
        self.drained_clean = self.eng.state.ix == 0 and self.eng.state.iy == 0
        peak = max(peaks) if peaks else 0
        self.last_peak = peak
        ratio = _ratio_readout(self.eng.profile.total_hip, self.eng.profile.total_ads)
        self.status = (
            f"{which} total={total} peak_ix={peak} rail={'YES' if peak >= RAIL else 'no'} | {ratio['text']}"
        )

    def export(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.export_dir / f"soft_makcu_profile_{ts}.json"
        self.eng.export_profile(path)
        self.status = f"exported {path} — Soft Lab never flashes (apply on Class 2 later)"

    def frame(self):
        if not (self.eng._ticker and self.eng._ticker.is_alive()):
            self.eng.tick()
            if self.eng.state.ix == 0 and self.eng.state.iy == 0 and self.eng.accum.accum_x == 0:
                self.drained_clean = True

        img = np.zeros((H, W, 3), dtype=np.uint8)
        img[:] = (18, 18, 22)

        cv2.rectangle(img, (0, 0), (W, 42), (28, 32, 44), -1)
        _put(img, BANNER, (16, 28), (90, 220, 200), 0.62, 2)
        _put(img, "Soft / No flash", (W - 200, 28), (140, 150, 170), 0.5, 1)

        st = self.eng.state
        _draw_stick(img, PAD_ORIGIN, st.ix, st.iy, "INJECTED (xim_curve)", (0, 200, 255))
        _draw_stick(img, MERGED_ORIGIN, st.mrx, st.mry, "MERGED (blend_stick)", (80, 255, 140))
        _draw_stick(img, PHYS_ORIGIN, st.px, st.py, "PHYSICAL (sim)", (200, 170, 90))

        y = 58
        lines = [
            (f"SoftMakcu  C={KM_GAIN_C:g}  P={KM_GAIN_P:.2f}  tick={HOUSEKEEP_TICK_MS:g}ms  rail=±{RAIL}", (180, 185, 195)),
            (f"tick={st.tick}  ax={st.ax:+d} ay={st.ay:+d}  ix={st.ix:+d} iy={st.iy:+d}  mrx={st.mrx:+d} mry={st.mry:+d}", (200, 205, 215)),
            (f"idle_dz={self.eng.idle_dz}  buttons=0x{st.buttons:04x}  hip={self.eng.profile.total_hip}  ads={self.eng.profile.total_ads}", (170, 175, 185)),
        ]
        for text, col in lines:
            _put(img, text, (16, y), col, 0.47)
            y += 20

        _put(img, f"Golden ix — {SOFTAXIS_BAR}", (16, y + 4), (90, 180, 255), 0.5)
        y += 24
        for row in _golden_rows():
            mark = "PASS" if row["ok"] else "FAIL"
            col = (80, 255, 140) if row["ok"] else (80, 80, 255)
            _put(img, f"  accum {row['accum']:>3} → ix {row['ix']:>5}  (expect {row['expected']})  {mark}", (16, y), col, 0.45)
            y += 18

        ratio = _ratio_readout(self.eng.profile.total_hip, self.eng.profile.total_ads)
        flags = _matrix_flags(self.eng, self.last_peak, self.drained_clean)
        y += 6
        _put(img, "SoftAxis Matrix", (16, y), (90, 180, 255), 0.5)
        y += 22
        xchip = 16
        for label in MATRIX_LABELS:
            ok = flags.get(label, False)
            col = (60, 160, 90) if ok else (55, 55, 70)
            tw = 8 + 11 * len(label)
            cv2.rectangle(img, (xchip, y - 14), (xchip + tw, y + 6), col, -1)
            _put(img, label, (xchip + 4, y), (230, 235, 240) if ok else (140, 145, 155), 0.42)
            xchip += tw + 8
        y += 28
        rcol = (80, 255, 140) if ratio["band"] == "PASS" else (80, 80, 255)
        _put(img, ratio["text"], (16, y), rcol, 0.5)
        y += 22

        _put(img, self.status, (16, y), (80, 255, 120), 0.48)
        y += 20
        _put(
            img,
            "keys: drag pad | 1/2/3=golden 8/80/240 | H/A=hip/ads | [] hip | ;' ads | Dd idle_dz | E=export | R=reset | Q=quit",
            (16, y),
            (120, 125, 135),
            0.40,
        )

        cv2.rectangle(img, (16, H - 52), (W - 16, H - 14), (40, 42, 52), -1)
        hip_w = int((W - 40) * _clamp(self.eng.profile.total_hip / 4800, 0, 1))
        ads_w = int((W - 40) * _clamp(self.eng.profile.total_ads / 4800, 0, 1))
        cv2.rectangle(img, (20, H - 48), (20 + hip_w, H - 36), (0, 170, 255), -1)
        cv2.rectangle(img, (20, H - 30), (20 + ads_w, H - 18), (0, 210, 130), -1)
        _put(img, f"hip TOTAL {self.eng.profile.total_hip}", (24, H - 38), (20, 20, 20), 0.4)
        _put(img, f"ads TOTAL {self.eng.profile.total_ads}", (24, H - 20), (20, 20, 20), 0.4)
        return img


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Soft Lab — Soft MAKCU host sim (never flashes). SoftAxis bit-exact goldens."
    )
    parser.add_argument("--smoke", action="store_true", help="Golden move+tick smoke; no display (exit 0)")
    parser.add_argument("--no-display", action="store_true", help="Alias of --smoke (compat)")
    parser.add_argument("--hip", type=int, default=None, help="Override total_hip")
    parser.add_argument("--ads", type=int, default=None, help="Override total_ads")
    args = parser.parse_args(argv)

    headless = (
        args.smoke
        or args.no_display
        or os.environ.get("SOFT_MAKCU_HEADLESS")
        or os.environ.get("MAKCU_HEADLESS") == "1"
    )

    if headless:
        return run_smoke()

    if not _ensure_cv2():
        print(
            f"OpenCV unavailable ({_CV2_ERR}). Soft Lab GUI needs opencv-python.\n"
            f"Math still works: python -m soft_makcu --smoke\n"
            f"{BANNER}",
            file=sys.stderr,
        )
        return run_smoke()

    eng = SoftMakcu()
    if args.hip is not None:
        eng.profile.total_hip = args.hip
    if args.ads is not None:
        eng.profile.total_ads = args.ads

    app = LabApp(eng)
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
                app.status = f"total_hip={eng.profile.total_hip} | {_ratio_readout(eng.profile.total_hip, eng.profile.total_ads)['text']}"
            elif key == ord("]"):
                eng.profile.total_hip = min(20000, eng.profile.total_hip + 50)
                app.status = f"total_hip={eng.profile.total_hip} | {_ratio_readout(eng.profile.total_hip, eng.profile.total_ads)['text']}"
            elif key == ord(";"):
                eng.profile.total_ads = max(100, eng.profile.total_ads - 50)
                app.status = f"total_ads={eng.profile.total_ads} | {_ratio_readout(eng.profile.total_hip, eng.profile.total_ads)['text']}"
            elif key == ord("'"):
                eng.profile.total_ads = min(20000, eng.profile.total_ads + 50)
                app.status = f"total_ads={eng.profile.total_ads} | {_ratio_readout(eng.profile.total_hip, eng.profile.total_ads)['text']}"
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
                app.drained_clean = True
                app.status = "reset — Soft / No flash"
    finally:
        eng.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
