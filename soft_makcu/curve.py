"""xim_curve — bit-exact port of km_inject.c xim_curve().

Firmware (km_inject.c):
    static inline int32_t xim_curve(int32_t accum) {
        if (accum == 0) return 0;
        int32_t mag = (accum < 0) ? -accum : accum;
        float r = KM_GAIN_C * powf((float)mag, KM_GAIN_P);
        int32_t ri = (r > 32767.0f) ? 32767 : (int32_t)r;
        return (accum < 0) ? -ri : ri;
    }

Defaults: KM_GAIN_C=5046.0f, KM_GAIN_P=0.40f, rail ±32767.

Comments in firmware:
    accum=8   →  ~12k (tracking)
    accum=80  →  ~29k (mid)
    accum=240 →  rail (flick)

Host Python uses IEEE-754 float64 for the pow/mul. Empirically the
truncated cast to int matches ESP32 float32 powf for the golden
magnitudes 8/80/240 within 0 counts (see golden_vectors.json). Document
any divergence > 0 in SOFT_MAKCU.md if a future host/libm differs.
"""

from __future__ import annotations

KM_GAIN_C: float = 5046.0
KM_GAIN_P: float = 0.40
RAIL: int = 32767


def xim_curve(accum: int, *, c: float = KM_GAIN_C, p: float = KM_GAIN_P) -> int:
    """Map per-tick velocity accumulator → injected stick axis.

    Truncates toward zero after rail check — matches ESP `(int32_t)r`.
    """
    if accum == 0:
        return 0
    mag = -accum if accum < 0 else accum
    r = c * (float(mag) ** p)
    ri = RAIL if r > float(RAIL) else int(r)  # truncate toward 0
    return -ri if accum < 0 else ri


def xim_curve_f32(accum: int, *, c: float = KM_GAIN_C, p: float = KM_GAIN_P) -> int:
    """Same curve forced through float32 intermediates (closer to powf).

    Pack/unpack via struct mimics ESP32 single-precision FPU. Golden
    magnitudes currently yield identical ix to float64 path.
    """
    import struct

    def f32(x: float) -> float:
        return struct.unpack("f", struct.pack("f", float(x)))[0]

    if accum == 0:
        return 0
    mag = -accum if accum < 0 else accum
    r = f32(f32(c) * f32(float(mag) ** f32(p)))
    ri = RAIL if r > float(RAIL) else int(r)
    return -ri if accum < 0 else ri
