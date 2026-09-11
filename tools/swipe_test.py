#!/usr/bin/env python3
"""
swipe_test.py — Track B PASS/FAIL known-swipe tester + 360° feel calibration
(2nd laptop / USB2 CH343).

Objective fidelity over the stock km API at 4 000 000 baud:
  1) Connect (Makcu from accessibility/makcu_access.py; port arg or config).
  2) Print km.version() link line (build date must match Track B bins).
  3) km.steady(0), km.trim(0,0), km.idle_dz(0).
  4) Paced km.move magnitudes 8, 80, 240 on X (~one per 8 ms housekeep window),
     read KMH ix/iy, compare to C * |accum|^P with C=5046 P=0.40 rail 32767 ±3%.
     Then verify stop → ix=iy=0 within ~16 ms.
  5) Optional --game-pulse N: human-visible horizontal burst for joy.cpl / in-game
     look check (script cannot see the game).

360° feel + deadzone calibration (--360) — interactive, visual at HIS sens:
  Script cannot see Warzone. It sends a known horizontal mouse-delta budget;
  Dylan watches the camera and reports under / over / ok. No fake "degrees"
  from firmware — honest visual 360 at look=2 / aim=1.50.

Usage (on the 2nd PC, USB2 CH343 plugged in):
  pip install pyserial
  python tools/swipe_test.py COM5
  python tools/swipe_test.py COM5 --game-pulse 40
  python tools/swipe_test.py COM5 --360
  python tools/swipe_test.py COM5 --360 --total 2400
  python tools/swipe_test.py COM5 --360 --idle-dz 0
  python tools/swipe_test.py          # uses accessibility/config.json port

Exit code 0 = all objective steps PASS (or --360 completed cleanly); 1 = FAIL.
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

DEFAULT_TOTAL = 2400
DEFAULT_CHUNK_DX = 120
REST_SAMPLE_S = 2.5
UNDER_SCALE = 1.15
OVER_SCALE = 0.85


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


def next_kms(gen, timeout_s: float = 0.05):
    """Return next KMS dict within timeout, or None."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            d = next(gen)
        except StopIteration:
            return None
        if d.get("_kind") == "kms":
            return d
    return None


def pass_fail(ok: bool, label: str, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    extra = f"  {detail}" if detail else ""
    print(f"  [{tag}] {label}{extra}")
    return ok


def percentile_abs(samples: list[int], pct: float) -> int:
    """Nearest-rank |p| percentile of abs(samples). Empty → 0."""
    if not samples:
        return 0
    xs = sorted(abs(v) for v in samples)
    if len(xs) == 1:
        return xs[0]
    # nearest-rank: ceil(pct/100 * n) - 1, clamped
    k = max(0, min(len(xs) - 1, math.ceil(pct / 100.0 * len(xs)) - 1))
    return xs[k]


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


def measure_rest_p99(mk: Makcu, seconds: float = REST_SAMPLE_S) -> tuple[int, int, int]:
    """Sample KMS rx/ry while sticks are still; return (rx_p99, ry_p99, n_samples)."""
    mk.telem(1)
    time.sleep(0.05)
    gen = mk.read_telem()
    rx_vals: list[int] = []
    ry_vals: list[int] = []
    deadline = time.monotonic() + seconds
    print(f"  rest deadzone: keep sticks still for {seconds:.1f}s …")
    while time.monotonic() < deadline:
        d = next_kms(gen, timeout_s=0.1)
        if d is None:
            continue
        rx_vals.append(int(d["rx"]))
        ry_vals.append(int(d["ry"]))
    mk.telem(0)
    time.sleep(0.02)
    rx_p99 = percentile_abs(rx_vals, 99.0)
    ry_p99 = percentile_abs(ry_vals, 99.0)
    return rx_p99, ry_p99, len(rx_vals)


def send_360_pulse(mk: Makcu, total: int, chunk_dx: int) -> int:
    """Paced km.move(dx,0) every TICK_MS until |accum| >= total. Returns accum sent."""
    if total <= 0:
        print("  [skip] TOTAL <= 0 — nothing to send")
        return 0
    chunk = max(1, int(chunk_dx))
    remaining = int(total)
    sent = 0
    n_moves = 0
    print(
        f"  sending paced km.move @ {TICK_MS:.0f} ms — "
        f"TOTAL budget={total} chunk_dx={chunk}"
    )
    while remaining > 0:
        dx = chunk if remaining >= chunk else remaining
        mk.move(dx, 0)
        sent += dx
        remaining -= dx
        n_moves += 1
        time.sleep(TICK_MS / 1000.0)
    # Drain so stick recenters before the next prompt.
    time.sleep(0.08)
    print(f"  pulse done: sent accum_dx={sent} in {n_moves} moves")
    return sent


def prompt_feel() -> str:
    """Interactive under/over/ok/quit. Returns normalized token."""
    while True:
        try:
            raw = input("  camera ~one full 360? [under / over / ok / quit]: ").strip().lower()
        except EOFError:
            print()
            return "quit"
        if raw in ("under", "u"):
            return "under"
        if raw in ("over", "o"):
            return "over"
        if raw in ("ok", "yes", "y", "good"):
            return "ok"
        if raw in ("quit", "q", "exit"):
            return "quit"
        print("  type: under | over | ok | quit")


def print_ok_tips(total: int, total_default: int) -> None:
    print()
    print(f"=== matched TOTAL = {total} ===")
    if total_default > 0:
        scale = total / float(total_default)
        print(
            f"  app-side scale tip: if stock app uses mouse→km.move, "
            f"scale ≈ TOTAL_matched / TOTAL_default = {total} / {total_default} ≈ {scale:.3f}"
        )
    print(
        f"  firmware curve is fixed C={C:g} P={P} — tune the sender app or "
        f"--total, not km.sens (does not exist on this fw)."
    )
    print(
        "  reminder: this was a VISUAL 360 at your in-game look/aim — "
        "script cannot measure degrees."
    )


def run_360(
    mk: Makcu,
    *,
    total: int,
    chunk_dx: int,
    idle_dz_cli: int | None,
    apply_dz: bool,
    expect_ok: bool,
    total_default: int,
) -> int:
    """Interactive (or --expect-ok) 360 feel + rest deadzone calibration."""
    print("=== 360° feel + deadzone calibration ===")
    print("  in-game reminder: look sens = 2 / aim = 1.50")
    print("  honest: 360 is VISUAL at your sens — firmware does not report degrees")
    print()

    mk.steady(False)
    mk.trim(0, 0)
    # Start quiet for rest measurement.
    mk.idle_dz(0)
    time.sleep(0.05)

    rx_p99, ry_p99, n = measure_rest_p99(mk, REST_SAMPLE_S)
    suggested = max(rx_p99, ry_p99)
    print(f"  rest samples={n}  |rx|p99={rx_p99}  |ry|p99={ry_p99}")
    if suggested == 0:
        print("  suggested km.idle_dz(0)  (quiet — leave micro-aim intact)")
    else:
        print(f"  suggested km.idle_dz({suggested})  (rest |p99|)")

    if idle_dz_cli is not None:
        dz = max(0, min(32000, int(idle_dz_cli)))
        mk.idle_dz(dz)
        print(f"  applied idle_dz={dz} (--idle-dz)")
    elif apply_dz:
        dz = max(0, min(32000, int(suggested)))
        mk.idle_dz(dz)
        print(f"  applied idle_dz={dz} (--apply-dz)")
    else:
        mk.idle_dz(0)
        print("  leaving idle_dz=0 (pass --apply-dz or --idle-dz N to set)")

    print()
    cur_total = max(1, int(total))

    if expect_ok:
        print("=== 360 pulse (--expect-ok, non-interactive) ===")
        print("  Watch in-game: did the camera do ~one full 360?")
        send_360_pulse(mk, cur_total, chunk_dx)
        print(f"  TOTAL used: {cur_total}")
        print_ok_tips(cur_total, total_default)
        return 0

    while True:
        print()
        print(f"=== 360 pulse (TOTAL={cur_total}) ===")
        print("  Watch in-game: did the camera do ~one full 360?")
        send_360_pulse(mk, cur_total, chunk_dx)
        ans = prompt_feel()
        if ans == "quit":
            print(f"  quit — last TOTAL tried: {cur_total}")
            return 0
        if ans == "ok":
            print_ok_tips(cur_total, total_default)
            return 0
        if ans == "under":
            nxt = max(1, int(round(cur_total * UNDER_SCALE)))
            print(f"  under → suggest TOTAL {cur_total} → {nxt} (×{UNDER_SCALE})")
            try:
                again = input("  re-run with new TOTAL? [Y/n]: ").strip().lower()
            except EOFError:
                print()
                return 0
            if again in ("", "y", "yes"):
                cur_total = nxt
                continue
            print(f"  stopped — suggested next TOTAL={nxt} (last tried={cur_total})")
            return 0
        if ans == "over":
            nxt = max(1, int(round(cur_total * OVER_SCALE)))
            print(f"  over → suggest TOTAL {cur_total} → {nxt} (×{OVER_SCALE})")
            try:
                again = input("  re-run with new TOTAL? [Y/n]: ").strip().lower()
            except EOFError:
                print()
                return 0
            if again in ("", "y", "yes"):
                cur_total = nxt
                continue
            print(f"  stopped — suggested next TOTAL={nxt} (last tried={cur_total})")
            return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Track B PASS/FAIL swipe tester + 360° feel calibration "
        "over USB2 CH343 @ 4e6"
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
    ap.add_argument(
        "--360",
        dest="mode_360",
        action="store_true",
        help="interactive 360° feel + rest deadzone calibration (skips objective)",
    )
    ap.add_argument(
        "--total",
        type=int,
        default=DEFAULT_TOTAL,
        metavar="N",
        help=f"360 mode: total horizontal mouse-delta budget (default: {DEFAULT_TOTAL})",
    )
    ap.add_argument(
        "--chunks",
        type=int,
        default=None,
        metavar="N",
        help="360 mode: TOTAL = N × --chunk-dx (overrides --total)",
    )
    ap.add_argument(
        "--chunk-dx",
        type=int,
        default=DEFAULT_CHUNK_DX,
        metavar="N",
        help=f"360 mode: per-tick km.move dx (default: {DEFAULT_CHUNK_DX})",
    )
    ap.add_argument(
        "--idle-dz",
        type=int,
        default=None,
        metavar="N",
        help="360 mode: set km.idle_dz(N) after rest sample (default: leave 0)",
    )
    ap.add_argument(
        "--apply-dz",
        action="store_true",
        help="360 mode: apply suggested rest |p99| as km.idle_dz",
    )
    ap.add_argument(
        "--expect-ok",
        action="store_true",
        help="360 mode: fire one pulse at --total and exit (non-interactive)",
    )
    args = ap.parse_args()

    port = args.port or load_config().get("port", "COM3")
    print(f"port: {port} @ 4000000")
    mk = Makcu(port)
    ver = mk.version().strip()
    print(f"link: {ver}")
    print()

    if args.mode_360:
        chunk_dx = max(1, int(args.chunk_dx))
        if args.chunks is not None:
            total = max(1, int(args.chunks) * chunk_dx)
            print(f"TOTAL from --chunks: {args.chunks} × {chunk_dx} = {total}")
        else:
            total = max(1, int(args.total))
        return run_360(
            mk,
            total=total,
            chunk_dx=chunk_dx,
            idle_dz_cli=args.idle_dz,
            apply_dz=args.apply_dz,
            expect_ok=args.expect_ok,
            total_default=DEFAULT_TOTAL,
        )

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
