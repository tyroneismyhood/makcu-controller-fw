"""blend_stick + idle_dz / clean_idle — port of km_inject.c helpers.

USER-PRIORITY asymmetric XIM-style blend:
  aligned (same sign or either zero): inject scales by (1 − |real|/32768)
  opposing (different signs):          inject passes at FULL gain

(a ^ b) >= 0 iff signs match (or either is zero) — two's complement.
Python int XOR matches C int promotion for ±32767 stick values.

idle_dz: Analog stick idle noise floor — drift below this is clamped to
zero so it doesn't add to mouse injection. Applied ONLY while km
injection is live (clean_idle=True). Default 0 = Matrix-feel / micro-aim
safe. Set live via km.idle_dz(N).
"""

from __future__ import annotations

RAIL = 32767


def clamp_s16(v: int) -> int:
    """Symmetric clamp — -32768 must NOT be returned (see firmware clamp_s16)."""
    if v < -RAIL:
        return -RAIL
    if v > RAIL:
        return RAIL
    return int(v)


def blend_stick(real: int, inject: int) -> int:
    """Firmware blend_stick(int16_t real, int16_t inject) → int16_t."""
    real = clamp_s16(real)
    inject = clamp_s16(inject)

    if inject == 0 or real == 0 or (inject ^ real) >= 0:
        abs_real = -real if real < 0 else real
        gain = 32768 - abs_real
        if gain < 0:
            gain = 0
    else:
        gain = 32768

    summed = int(real) + ((int(inject) * gain) >> 15)
    if summed > RAIL:
        return RAIL
    if summed < -RAIL:
        return -RAIL
    return int(summed)


def physical_deadzone_clean(v: int, idle_dz: int) -> int:
    """Firmware physical_deadzone_clean — clamp |v| < dz → 0."""
    dz = int(idle_dz)
    if dz <= 0:
        return int(v)
    if -dz < v < dz:
        return 0
    return int(v)


def compute_merged_stick(
    real_x: int,
    real_y: int,
    inj_x: int,
    inj_y: int,
) -> tuple[int, int]:
    """compute_merged_stick without the critical section — returns (mrx, mry)."""
    mrx = blend_stick(clamp_s16(real_x), clamp_s16(inj_x))
    mry = blend_stick(clamp_s16(real_y), clamp_s16(inj_y))
    return mrx, mry
