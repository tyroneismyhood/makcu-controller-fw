"""Soft MAKCU — Class 3 / host-only virtual MAKCU (Track D).

Bit-faithful port of Class 2 / Track B formulas from
firmware/MAKCM_ESP32s3_Pass_Left_IDF/src/km_inject.c:

  applyMouseDelta → 8 ms housekeep drain → xim_curve(C=5046, P=0.40)
  blend_stick asymmetric USER-PRIORITY
  idle_dz / clean_idle / km.move / km.click / steady

Never flashes hardware. AAA host sim for hip/ADS calibration without a board.
"""

from .curve import KM_GAIN_C, KM_GAIN_P, RAIL, xim_curve
from .drain import HOUSEKEEP_TICK_MS, Accumulator
from .blend import blend_stick, clamp_s16, physical_deadzone_clean
from .km_api import KmApi
from .sim import SoftMakcu

__all__ = [
    "KM_GAIN_C",
    "KM_GAIN_P",
    "RAIL",
    "xim_curve",
    "HOUSEKEEP_TICK_MS",
    "Accumulator",
    "blend_stick",
    "clamp_s16",
    "physical_deadzone_clean",
    "KmApi",
    "SoftMakcu",
]

__version__ = "0.1.0"
