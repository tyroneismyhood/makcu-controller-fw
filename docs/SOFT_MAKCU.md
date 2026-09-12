# Soft MAKCU — Class 3 / Track D (host-only virtual MAKCU)

**Branch:** `track-d/soft-makcu`  
**Mission:** Stop flash→test→reflash (brick risk). Calibrate hip/ADS feel on the
main PC using the **exact Class 2 / Track B formulas** (the `km_inject.c` twin
on `track-b`). This branch is Class 3 only — **no firmware tree, no swipe lab**.

Soft MAKCU **never flashes**, never opens a board, never talks USB/DFU.
Profile JSON export is for *later* manual application on Class 2.

---

## Class 3 vs Class 2

| | Class 2 / Track B | Class 3 / Soft MAKCU (Track D) |
|---|---|---|
| Where formulas run | ESP32-S3 firmware (`km_inject.c` on `track-b`) | Host Python (`soft_makcu/`) |
| Hardware | MAKCU board required | **None** |
| Flash risk | Yes (brick if bad image) | **None** — never flashes |
| Curve | `xim_curve` C=5046 P=0.40 rail ±32767 | Same constants + cast semantics |
| Drain | 8 ms `km_housekeep_cb` | 8 ms `Accumulator.drain` / `SoftMakcu.tick` |
| Blend | `blend_stick` asymmetric USER-PRIORITY | Identical integer math |
| Idle DZ | `km.idle_dz` + `clean_idle` only when inj live | Same |
| Output | Real controller IN reports | Live stick viz + optional profile JSON |
| Use | On-console fidelity | Pre-flash hip/ADS tuning, golden unit tests |

Class 2 remains the source of truth on device. Class 3 is a **host twin** so
you can prove curve + blend + totals before you ever pick up a cable.

---

## How formulas stay in sync with Class 2

Canonical constants (do not invent new ones here):

```
KM_GAIN_C  = 5046.0
KM_GAIN_P  = 0.40
rx = clamp(C × |accum|^P, ±32767); accum drained every 8 ms
```

Acceptance bands:

| accum / 8 ms | expected ix | Soft MAKCU golden |
|---:|---:|---:|
| 8 | ~12k (tracking) | **11592** |
| 80 | ~29k (mid) | **29119** |
| 240 | rail (flick) | **32767** |

Port map:

| Class 2 (`track-b`) | Soft MAKCU |
|---|---|
| `xim_curve` | `soft_makcu/curve.py` |
| `applyMouseDelta` + `km_housekeep_cb` | `soft_makcu/drain.py` |
| `blend_stick` / `clamp_s16` / `physical_deadzone_clean` | `soft_makcu/blend.py` |
| `parse_km_text` / `km.move` / `km.click` / `km.idle_dz` / `km.steady*` | `soft_makcu/km_api.py` |
| Full engine | `soft_makcu/sim.py` (`SoftMakcu`) |
| Golden vectors | `soft_makcu/golden_vectors.json` + pytest |

When Track B changes `KM_GAIN_C` / `KM_GAIN_P` or blend math, update
`curve.py` / `blend.py` and regenerate `golden_vectors.json`, then
`pytest soft_makcu/tests` must stay green (bit-exact vs SoftAxis EXPECTED_IX for 8/80/240).

### Float64 vs firmware float32

ESP32-S3 uses `powf` (float32). Soft MAKCU’s default path uses Python
float64 (`C * mag**P` then truncate toward zero). Empirically, for the
published golden magnitudes **8 / 80 / 240**, float64 and a float32-forced
path (`xim_curve_f32`) agree within **0 counts**. Pytest enforces **bit-exact**
match vs `golden_vectors.json` / SoftAxis EXPECTED_IX. If a future host libm
diverges, document the delta here — do not reopen a soft-only ±N bar.

---

## Safety: never flashes

- No import of board flashers or firmware helpers.
- No serial/USB open required for the lab UI or unit tests.
- `export_profile()` writes JSON only (`soft_makcu/exports/…`). Applying that
  profile to a board is an explicit Class 2 / human step — Soft MAKCU will
  not do it.
- Banner in the Lab UI: **NEVER FLASHES**.

---

## How to run

From repo root (`makcu-controller-fw/`):

```bash
pip install -r requirements.txt

# Lab UI (OpenCV) — zero-arg
python -m soft_makcu
# or
python soft_makcu/lab_ui.py
# or

# Headless smoke (CI / no display)
SOFT_MAKCU_HEADLESS=1 python -m soft_makcu
# or
python -m soft_makcu --smoke

# Golden tests (accuracy bar)
python -m pytest soft_makcu/tests -q
```

Use the project `.venv` if present (`source .venv/bin/activate`).

### Lab keys

| Key | Action |
|---|---|
| Drag left pad | `km.move` deltas |
| `1` / `2` / `3` | Inject accum 8 / 80 / 240 |
| `H` / `A` | Run hip / ADS total chunked across 8 ms ticks |
| `[` `]` | Nudge `total_hip` ±50 |
| `;` `'` | Nudge `total_ads` ±50 |
| `D` / `d` | `idle_dz` ±100 |
| `E` | Export profile JSON |
| `R` | Reset |
| `Q` / ESC | Quit |

---

## Package layout

```
soft_makcu/
  __init__.py
  __main__.py          # python -m soft_makcu
  curve.py             # xim_curve
  drain.py             # 8 ms accumulator
  blend.py             # blend_stick / idle_dz
  km_api.py            # km.move/click/idle_dz/steady shim (in-process; no USB)
  sim.py               # SoftMakcu engine
  lab_ui.py            # OpenCV lab
  golden_vectors.json
  tests/test_golden.py
  lab_ui.py            # thin launcher → soft_makcu.lab_ui
docs/SOFT_MAKCU.md     # this file
README.md              # home checklist
```

---

## In-game playbook

The home checklist (success / over / short + what to send Xim) lives in the
root [README.md](../README.md). Soft Lab never opens the game — tune totals
here, prove 360s in Warzone at look **2** / aim **1.50**, then send the
export JSON + `success|over|short` note.
