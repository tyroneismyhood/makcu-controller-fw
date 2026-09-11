#!/usr/bin/env python3
"""
swipe_test.py — Track B PASS/FAIL known-swipe tester (2nd laptop / USB2 CH343).

Objective fidelity over the stock km API at 4 000 000 baud:
  1) Connect (Makcu from accessibility/makcu_access.py; port arg or config).
  2) Print km.version() link line (build date must match Track B bins).
  3) km.steady(0), km.trim(0,0), km.idle_dz(0).
  4) Paced km.move magnitudes 8, 80, 240 on X (~one per 8 ms housekeep window),
     read KMH ix/iy, compare to C * |accum|^P with C=5046 P=0.40 rail 32767 ±3%.
     Then verify stop → ix=iy=0 within ~16 ms.
  5) Optional --game-pulse N: human-visible horizontal burst for joy.cpl / in-game
     look check (script cannot see the game).

Usage (on the 2nd PC, USB2 CH343 plugged in):
  pip install pyserial
  python tools/swipe_test.py COM5
  python tools/swipe_test.py COM5 --game-pulse 40
  python tools/swipe_test.py          # uses accessibility/config.json port

Exit code 0 = all objective steps PASS; 1 = any FAIL.
See docs/TRACK_B_SETUP.md.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "accessibility"))
from makcu_access import Makcu, load_config  # noqa: E402

C = 5046.0
P = 0.40
RAIL = 32767
TICK_MS = 8.0
SHAPE_TOL = 0.03  # ±3%
STOP_BUDGET_MS = 16.0
MAGNITUDES = (8, 80, 240)


def xim_curve(accum: int) -> int:
    if accum == 0:
        return 0
    mag = abs(accum)
    r = C * (float(mag) ** P)
    ri = RAIL if r > RAIL else int(r)
    return -ri if accum < 0 else ri


def shape_ok(got: int, exp: int) -> bool:
    if exp == 0:
        return got == 0
    if abs(exp) >= RAIL:
        return abs(got) >= int(RAIL * (1.0 - SHAPE_TOL))
    return abs(got - exp) <= max(1, int(abs(exp) * SHAPE_TOL))


def next_kmh(gen, timeout_s: float = 0.05):
    """Return next KMH dict within timeout, or None."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            d = next(gen)
        except StopIteration:
            return None
        if d.get("_kind") == "kmh":
            return d
    return None


def pass_fail(ok: bool, label: str, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    extra = f"  {detail}" if detail else ""
    print(f"  [{tag}] {label}{extra}")
    return ok


def run_objective(mk: Makcu) -> bool:
    mk.steady(False)
    mk.trim(0, 0)
    mk.idle_dz(0)
    time.sleep(0.05)

    gen = mk.read_telem()
    # Prime on two housekeep ticks so the first move lands in a clean window.
    primed = 0
    t0 = time.monotonic()
    while primed < 2 and time.monotonic() - t0 < 1.0:
        d = next_kmh(gen, timeout_s=0.1)
        if d is not None:
            primed += 1
    if primed < 2:
        print("  [FAIL] could not prime on KMH ticks (is Track B quiet firmware flashed?)")
        return False

    all_ok = True
    for mag in MAGNITUDES:
        exp = xim_curve(mag)
        t_cmd = time.monotonic()
        mk.move(mag, 0)
        kmh = next_kmh(gen, timeout_s=STOP_BUDGET_MS / 1000.0 + 0.05)
        late_ms = (time.monotonic() - t_cmd) * 1000.0
        if kmh is None:
            all_ok &= pass_fail(False, f"move({mag},0)", "no KMH within budget")
            continue
        ix, iy = kmh["ix"], kmh["iy"]
        ok_x = shape_ok(ix, exp)
        ok_y = iy == 0
        ok = ok_x and ok_y
        all_ok &= pass_fail(
            ok,
            f"move({mag},0) → curve",
            f"ix={ix} exp={exp} iy={iy} late={late_ms:.1f}ms "
            f"(C={C:g} P={P} ±{SHAPE_TOL*100:.0f}% rail={RAIL})",
        )
        # Keep windows from stacking; one empty tick.
        time.sleep(TICK_MS / 1000.0)

    # Stop: no further moves; ix/iy must drain to 0 within ~16 ms.
    t_stop = time.monotonic()
    # Drain a couple of housekeep periods with no new km.move.
    got_zero = False
    last = None
    while (time.monotonic() - t_stop) * 1000.0 <= STOP_BUDGET_MS + 8.0:
        kmh = next_kmh(gen, timeout_s=0.02)
        if kmh is None:
            continue
        last = kmh
        if kmh["ix"] == 0 and kmh["iy"] == 0:
            got_zero = True
            elapsed = (time.monotonic() - t_stop) * 1000.0
            all_ok &= pass_fail(True, "stop → ix=iy=0", f"at {elapsed:.1f}ms")
            break

    if not got_zero:
        detail = f"last ix={last['ix']} iy={last['iy']}" if last else "no KMH"
        all_ok &= pass_fail(False, "stop → ix=iy=0 within ~16ms", detail)

    return all_ok


def game_pulse(mk: Makcu, n: int) -> None:
    """Human-visible horizontal burst — watch joy.cpl / in-game camera."""
    print()
    print(f"=== game-pulse: {n} × km.move(120,0) @ {TICK_MS:.0f} ms ===")
    print("  watch the camera / joy.cpl — script cannot see the game")
    for _ in range(n):
        mk.move(120, 0)
        time.sleep(TICK_MS / 1000.0)
    # Let injection drain so the stick recenters.
    time.sleep(0.05)
    print("  pulse done (stick should return to center after drain)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Track B PASS/FAIL swipe tester over USB2 CH343 @ 4e6"
    )
    ap.add_argument(
        "port",
        nargs="?",
        default=None,
        help="CH343 COM/tty (default: accessibility/config.json)",
    )
    ap.add_argument(
        "--game-pulse",
        type=int,
        default=0,
        metavar="N",
        help="after objective test, send N× km.move(120,0) @ 8 ms (default: off)",
    )
    args = ap.parse_args()

    port = args.port or load_config().get("port", "COM3")
    print(f"port: {port} @ 4000000")
    mk = Makcu(port)
    ver = mk.version().strip()
    print(f"link: {ver}")
    print()
    print("=== objective fidelity (Track B curve C=5046 P=0.40) ===")
    ok = run_objective(mk)

    if args.game_pulse and args.game_pulse > 0:
        game_pulse(mk, args.game_pulse)

    print()
    if ok:
        print("OVERALL: PASS")
        return 0
    print("OVERALL: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
