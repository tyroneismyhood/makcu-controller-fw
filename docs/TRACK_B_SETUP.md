# Track B setup + sensitivity (Matrix-feel)

Track B (`track-b/matrix-translation`) is the Class 2 Matrix-feel firmware:
XIM-fit stick curve, inject-path `km.idle_dz` default **0**, always-on **KMH**
housekeep stamps, GIP input on EP **0x81|0x82**, and Track A wire-perfect
passthrough when injection/filters are off.

Bins in `firmware/bin/` for this branch are dated **2026-09-11**. Confirm with
`km.version()` → `Sep 11 2026` (not `Jul  8 2026` from old `main`).

---

## Plug map

| Port | Role | Where it goes |
|------|------|----------------|
| **USB3** (right) | Right MCU — USB host | Real controller (Xbox wired GIP) |
| **USB1** (left) | Left MCU — USB device | **Main PC / console** (powers the board) |
| **USB2** (middle) | CH343 USB-serial | **2nd PC** @ **4 000 000** baud — stock `km.*` API / accessibility / swipe test |

Typical Dylan layout:

- Mouse stays on the **2nd PC** (sender app scales `km.move` deltas).
- Controller on **USB3**.
- **USB1** → main gaming PC.
- **USB2** → 2nd PC CH343 for the km API app / `tools/swipe_test.py`.

Flash **both** MCUs (Left + Right). One-sided flash = no controller input.
See [FLASHING.md](../FLASHING.md).

```bash
# Left (hold USB1 BOOT while plugging in → 303A:0009):
esptool.py --chip esp32s3 --port COM3 --baud 921600 write_flash 0x0 firmware/bin/MERGED_left.bin

# Right (USB3; hold BOOT if not enumerated → 303A:0009):
esptool.py --chip esp32s3 --port COM4 --baud 921600 write_flash 0x0 firmware/bin/MERGED_right.bin
```

Or: `python firmware/flash_tool.py` / `firmware/Flash_MAKCM.bat`.

---

## Verify flash + link

1. Power via USB1; controller on USB3; USB2 to the 2nd PC.
2. On the 2nd PC:

```bash
pip install pyserial
python -c "from accessibility.makcu_access import Makcu; print(Makcu('COM5').version())"
# expect: kmbox:   1.0.0 Sep 11 2026 ...
```

3. Objective PASS/FAIL (KMH curve + stop drain):

```bash
python tools/swipe_test.py COM5
# optional human-visible look pulse (watch joy.cpl / in-game — script cannot see the game):
python tools/swipe_test.py COM5 --game-pulse 40
```

4. On the main PC: `Win+R` → `joy.cpl` → Xbox controller sticks/buttons move.

---

## Sensitivity: firmware curve vs sender app

**Honest numbers (do not treat firmware as the sens dial):**

| Piece | What it does |
|-------|----------------|
| Firmware curve | `C=5046`, `P=0.40`, rail `32767` — XIM-fit for **~15 cm/360 @ 1200 DPI** Matrix baseline |
| Sender app | **Owns sensitivity** — scale the `km.move(dx,dy)` deltas before they hit USB2 |
| Defaults for Matrix-feel | `km.idle_dz(0)` and `km.steady(0)` (swipe_test sets these; keep them off for micro-aim) |

### Dylan: 800 DPI mouse + Warzone-style FPS

- Matrix / firmware fit assumes **~1200 DPI**.
- DPI ratio: `800 / 1200 ≈ 0.667`.
- To keep the **same cm/360** as a 1200-DPI Matrix baseline, the sender app
  typically needs about **~1.5×** mouse→`km.move` scale vs that baseline
  (`1 / 0.667 ≈ 1.5`).
- Tune **in-game** look / ADS separately (e.g. look sens 2 / aim 1.50 as a
  starting point for the optional `--game-pulse` visual check) — the firmware
  does not implement game-specific recoil or aimbot.
- Prefer matching feel with **app scale + in-game sens**, not by rewriting
  `C`/`P` unless you are deliberately re-fitting the curve.

### Quick checklist

1. Flash Track B bins (date `Sep 11 2026`).
2. `km.idle_dz(0)`, `km.steady(0)`, `km.trim(0,0)`.
3. Set sender mouse scale for 800 DPI (~1.5× vs 1200-DPI Matrix baseline).
4. `python tools/swipe_test.py COMx` → OVERALL PASS.
5. Fine-tune look/ADS in-game; run `python tools/swipe_test.py COMx --360` for feel + idle_dz, or `--game-pulse` for a quick burst.

---

## 360° feel + deadzone (`--360`) — hip vs ADS

Interactive calibration from the **2nd PC** over USB2. The script cannot see
Warzone — two separate visual 360s at **your** sens. No fake degrees from
firmware.

| Mode | In-game | TOTAL flag | Default | ADS |
|------|---------|-----------|---------|-----|
| **Hip-fire** | look sens **2**, unscoped | `--total-hip` | 2400 | not held |
| **ADS / aim** | aim sens **1.50** | `--total-ads` | 1800 (≈0.75× hip) | script holds `km.right(1)` for the pulse, then `km.right(0)` (LT) |

```bash
python tools/swipe_test.py COM5 --360              # rest dz once → hip loop → ads loop
python tools/swipe_test.py COM5 --360 hip          # hip only
python tools/swipe_test.py COM5 --360 ads          # ads only
python tools/swipe_test.py COM5 --360 --total-hip 2400 --total-ads 1800
python tools/swipe_test.py COM5 --360 --idle-dz 0
python tools/swipe_test.py COM5 --360 --apply-dz
# scripted one-shot per selected mode (no prompts):
python tools/swipe_test.py COM5 --360 --expect-ok
# --total is a legacy alias for --total-hip
```

What it does:

1. Handshake (`km.version()`) + hip/ADS sens reminders.
2. Rest sample once (~2.5 s, sticks still) → `|rx|/|ry| p99` and suggested
   `km.idle_dz(N)` (0 if quiet). Default leaves idle_dz at 0 unless
   `--idle-dz N` or `--apply-dz`.
3. **Hip** paced pulse (`TOTAL_hip`, default 2400 @ 8 ms) → under/over/ok/quit.
4. **ADS** paced pulse (`TOTAL_ads`, default 1800) with LT held via firmware →
   same prompt loop.
5. Prints **finals**: `idle_dz_suggested`, `idle_dz_applied`, `TOTAL_hip`,
   `TOTAL_ads`, and app-side scale tips vs those defaults. Firmware curve stays
   fixed `C=5046 P=0.40` — tune the sender app or `--total-hip`/`--total-ads`,
   not `km.sens` (does not exist on this fw).

Objective PASS/FAIL remains the default when `--360` is not passed;
`--game-pulse` is unchanged for a quick visual burst after objective.

## Related

- [FLASHING.md](../FLASHING.md) — boot buttons, Error 1 = success, DIO 80 MHz
- [docs/PC_CONNECTION_GUIDE.md](PC_CONNECTION_GUIDE.md) — USB1/2/3 roles
- [tools/kmh_fidelity_csv.py](../tools/kmh_fidelity_csv.py) — CSV harness for the same curve
- [tools/swipe_test.py](../tools/swipe_test.py) — PASS/FAIL known-swipe + `--360` feel/deadzone
