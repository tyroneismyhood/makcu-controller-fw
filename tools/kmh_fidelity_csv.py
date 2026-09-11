#!/usr/bin/env python3
"""
kmh_fidelity_csv.py — Track A / Track B proof CSV for MAKCU Matrix-feel.

Merge key (Matrix/Firmware contract):
  KMH tick=%u ix=%ld iy=%ld   — monotonic 8 ms housekeep stamp after curve drain.
  Do NOT join on KMS (16 ms, pre-apply physical).

Columns:
  tick, t_cmd_ms, dx, dy, expected_x, expected_y, ix, iy,
  mrx, mry, t_kmh_ms, soft_x, late_ms

Track A (filters off): rest + optional idle_dz from rest |p99|, then µ-deflection
  is a manual/physical stick exercise — this script mainly proves KMH stream +
  zero after stop.

Track B: paced km.move @ 8 ms for accum 8 / 80 / 240 then stop.
  expected = C * |accum|^P  (C=5046, P=0.40), ±3% / rail 32767.
  soft = |ix - expected| miss; late = shape ok but host KMH gap > budget.

Requires: pip install pyserial
  python tools/kmh_fidelity_csv.py [COM_PORT] [--out path.csv]
"""

from __future__ import annotations

import argparse
import csv
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
# Matrix latency: km.move → curve applied p50 ≤ 8 / p99 ≤ 16; jitter ≤ 8
LATE_P99_MS = 16.0
SHAPE_TOL = 0.03  # ±3%


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


def drain_kmh(mk: Makcu, seconds: float):
    """Yield (host_ms, kmh_dict) for a window, draining the UART."""
    end = time.monotonic() + seconds
    # read_telem blocks forever — poll with a short deadline via timeout reads
    buf_deadline = end
    gen = mk.read_telem()
    while time.monotonic() < buf_deadline:
        # serial timeout is 50 ms; generator yields when a line parses
        try:
            d = next(gen)
        except StopIteration:
            break
        now = time.monotonic() * 1000.0
        if d.get("_kind") == "kmh":
            yield now, d
        # KMS kept only if caller wants physical context later


def rest_p99(mk: Makcu, seconds: float = 2.0) -> int:
    """Rest |p99| of physical rx/ry from KMS (for km.idle_dz). Not a curve join."""
    mk.telem(True)
    samples = []
    end = time.monotonic() + seconds
    gen = mk.read_telem()
    while time.monotonic() < end:
        d = next(gen)
        if d.get("_kind") != "kms":
            continue
        samples.append(abs(d["rx"]))
        samples.append(abs(d["ry"]))
    mk.telem(False)
    if not samples:
        return 0
    samples.sort()
    idx = min(len(samples) - 1, int(math.ceil(0.99 * len(samples)) - 1))
    return int(samples[max(0, idx)])


def run_track_b(mk: Makcu, out_path: str, magnitudes=(8, 80, 240)):
    mk.steady(False)
    mk.trim(0, 0)
    mk.idle_dz(0)

    # Sync to a couple of housekeep ticks so the first move lands in a clean window.
    gen = mk.read_telem()
    primed = 0
    while primed < 2:
        d = next(gen)
        if d.get("_kind") == "kmh":
            primed += 1

    rows = []
    for mag in magnitudes:
        # one move per 8 ms window; wait for the KMH that drains it
        t_cmd = time.monotonic() * 1000.0
        mk.move(mag, 0)
        exp = xim_curve(mag)
        # collect next KMH (should be ≤ ~16 ms host-side)
        deadline = time.monotonic() + 0.05
        kmh = None
        t_kmh = None
        while time.monotonic() < deadline:
            d = next(gen)
            if d.get("_kind") != "kmh":
                continue
            t_kmh = time.monotonic() * 1000.0
            kmh = d
            # skip empty ticks until we see non-zero or tick advances with our inject
            if d["ix"] != 0 or d["iy"] != 0 or (t_kmh - t_cmd) > LATE_P99_MS:
                break
        if kmh is None:
            rows.append({
                "tick": "",
                "t_cmd_ms": f"{t_cmd:.3f}",
                "dx": mag,
                "dy": 0,
                "expected_x": exp,
                "expected_y": 0,
                "ix": "",
                "iy": "",
                "mrx": "",
                "mry": "",
                "t_kmh_ms": "",
                "soft_x": "drop",
                "late_ms": "",
            })
            continue
        late = t_kmh - t_cmd
        soft = "ok" if shape_ok(kmh["ix"], exp) else "soft"
        rows.append({
            "tick": kmh["tick"],
            "t_cmd_ms": f"{t_cmd:.3f}",
            "dx": mag,
            "dy": 0,
            "expected_x": exp,
            "expected_y": 0,
            "ix": kmh["ix"],
            "iy": kmh["iy"],
            "mrx": "",  # KMS is pre-apply; score mrx only when |physical| <= idle_dz
            "mry": "",
            "t_kmh_ms": f"{t_kmh:.3f}",
            "soft_x": soft,
            "late_ms": f"{late:.3f}",
        })
        # pad one empty tick so windows don't stack
        time.sleep(TICK_MS / 1000.0)

    # stop → rest: next drains must be zero within ≤8 ms (one tick)
    t_stop = time.monotonic() * 1000.0
    mk.move(0, 0)  # no-op; stop = no further moves
    zeros = []
    deadline = time.monotonic() + 0.05
    while time.monotonic() < deadline and len(zeros) < 3:
        d = next(gen)
        if d.get("_kind") != "kmh":
            continue
        t_kmh = time.monotonic() * 1000.0
        zeros.append((d, t_kmh))
        rows.append({
            "tick": d["tick"],
            "t_cmd_ms": f"{t_stop:.3f}",
            "dx": 0,
            "dy": 0,
            "expected_x": 0,
            "expected_y": 0,
            "ix": d["ix"],
            "iy": d["iy"],
            "mrx": "",
            "mry": "",
            "t_kmh_ms": f"{t_kmh:.3f}",
            "soft_x": "ok" if d["ix"] == 0 and d["iy"] == 0 else "carry",
            "late_ms": f"{t_kmh - t_stop:.3f}",
        })

    fieldnames = [
        "tick", "t_cmd_ms", "dx", "dy", "expected_x", "expected_y",
        "ix", "iy", "mrx", "mry", "t_kmh_ms", "soft_x", "late_ms",
    ]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    ap = argparse.ArgumentParser(description="MAKCU KMH fidelity CSV (Track B paced km.move)")
    ap.add_argument("port", nargs="?", default=None, help="CH343 COM/tty port")
    ap.add_argument("--out", default="kmh_fidelity.csv")
    ap.add_argument("--rest-p99", action="store_true", help="print rest |p99| then exit")
    args = ap.parse_args()

    port = args.port or load_config().get("port", "COM3")
    mk = Makcu(port)
    print("link:", mk.version().strip())

    if args.rest_p99:
        n = rest_p99(mk)
        print(f"rest |p99| = {n}  →  mk.idle_dz({n})")
        return

    rows = run_track_b(mk, args.out)
    print(f"wrote {args.out} ({len(rows)} rows)")
    for r in rows:
        print(
            f"  tick={r['tick']} dx={r['dx']} exp={r['expected_x']} "
            f"ix={r['ix']} soft={r['soft_x']} late={r['late_ms']}"
        )


if __name__ == "__main__":
    main()
