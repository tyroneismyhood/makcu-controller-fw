"""Golden tests — Soft MAKCU ix must match firmware xim_curve bit-exact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soft_makcu.blend import blend_stick
from soft_makcu.curve import RAIL, xim_curve, xim_curve_f32
from soft_makcu.drain import Accumulator, HOUSEKEEP_TICK_MS
from soft_makcu.sim import SoftMakcu

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "golden_vectors.json"


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN_PATH.read_text())


def test_primary_magnitudes_bit_exact(golden):
    """Host expected ix for accum 8/80/240 must match SoftAxis EXPECTED_IX exactly."""
    primary = golden["primary_golden"]
    for key, expected in primary.items():
        mag = int(key)
        got = xim_curve(mag)
        assert got == expected, f"accum={mag}: got {got} expected {expected}"
        # Negative polarity
        assert xim_curve(-mag) == (-expected if expected != 0 else 0)


def test_firmware_comment_bands(golden):
    """Firmware comments: 8→~12k, 80→~29k, 240→rail — exact SoftAxis numbers."""
    assert xim_curve(8) == 11592
    assert xim_curve(80) == 29119
    assert xim_curve(240) == RAIL


def test_all_golden_vectors(golden):
    for row in golden["xim_curve"]:
        mag = row["accum"]
        assert xim_curve(mag) == row["expected_ix"]
        if mag:
            assert xim_curve(-mag) == row["expected_ix_neg"]


def test_float32_vs_float64_bit_exact(golden):
    """float64 vs float32 paths must agree bit-exact on golden magnitudes."""
    for row in golden["xim_curve"]:
        mag = row["accum"]
        assert xim_curve(mag) == xim_curve_f32(mag), f"accum={mag} f64/f32 diverge"
        assert row["f64_vs_f32_delta"] == 0


def test_blend_stick_golden(golden):
    for case in golden["blend_stick"]:
        got = blend_stick(case["real"], case["inject"])
        assert got == case["expected"], case["why"]


def test_drain_zeros_after_idle():
    acc = Accumulator()
    acc.apply_mouse_delta(8, 0)
    ix, iy = acc.drain()
    assert ix == xim_curve(8) and iy == 0
    ix2, iy2 = acc.drain()
    assert ix2 == 0 and iy2 == 0


def test_housekeep_tick_ms():
    assert HOUSEKEEP_TICK_MS == 8


def test_softmakcu_move_and_tick():
    eng = SoftMakcu()
    eng.km.move(80, 0)
    st = eng.tick()
    assert st.ix == xim_curve(80)
    assert st.iy == 0
    assert st.mrx == st.ix  # physical at 0
    st2 = eng.tick()
    assert st2.ix == 0


def test_km_text_parser():
    eng = SoftMakcu()
    eng.km.ingest_line("km.move(8,-8)")
    st = eng.tick()
    assert st.ix == xim_curve(8)
    assert st.iy == xim_curve(-8)
    eng.km.ingest_line("km.idle_dz(500)")
    assert eng.idle_dz == 500
    resp = eng.km.ingest_line("km.version()")
    assert resp and "kmbox" in resp


def test_opposing_blend_full_gain():
    """Opposing signs → inject at full gain (USER-PRIORITY XIM-style)."""
    # real +10000, inject -20000 → opposing
    got = blend_stick(10000, -20000)
    expected = 10000 + ((-20000 * 32768) >> 15)
    assert got == expected


def test_aligned_blend_scales_by_headroom():
    got = blend_stick(16384, 16384)
    gain = 32768 - 16384
    expected = 16384 + ((16384 * gain) >> 15)
    assert got == expected
