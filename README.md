# Soft MAKCU — Class 3 / Track D

Host-only soft twin of the Track B (`track-b`) look formulas. **No board. No flash.**
Tune hip / ADS feel on your PC, then apply once later on Class 2.

This branch does **not** contain firmware, swipe lab, Elgato, or serial tools.

Deeper notes: [docs/SOFT_MAKCU.md](docs/SOFT_MAKCU.md)

---

## When you get home

```bash
cd makcu-controller-fw
git checkout track-d/soft-makcu
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Run the lab**

```bash
python -m soft_makcu
```

Headless (no window): `python -m soft_makcu --smoke`

**Run tests**

```bash
python -m pytest soft_makcu/tests -q
```

---

## What you’ll see

- Three stick pads: **INJECTED** (post-curve), **MERGED** (blend), **PHYSICAL** (sim)
- **Golden ix** chips for accum **8 / 80 / 240** → `11592 / 29119 / 32767` (bit-exact)
- **TOTAL hip / ADS** bars (default 2400 / 1800, ratio 1.33) — keys `H` / `A` run a chunked total; `[ ]` and `; '` nudge
- SoftAxis chips: CLEAN STOP · NO CARRY · NO OVERSHOOT · RATIO 1.33
- `E` exports profile JSON under `soft_makcu/exports/` — Soft Lab never flashes it

Keys: drag inject pad · `1`/`2`/`3` goldens · `H`/`A` hip/ads · `R` reset · `Q` quit

---

## Class 3 vs Class 2

| | This branch (Class 3) | `track-b` (Class 2) |
|---|---|---|
| Where | Python on your PC | ESP32-S3 firmware |
| Hardware | None | MAKCU board |
| Flash | Never | Yes — once, after you like the feel |
| Formulas | Same `xim_curve` C=5046 P=0.40, 8 ms drain, blend | Same |

**Workflow:** tune totals / idle_dz here → export JSON → flash that profile on Class 2 later.

---

## Layout

```
soft_makcu/            # curve, drain, blend, km_api, sim, lab_ui, goldens, tests
docs/SOFT_MAKCU.md     # formula sync + keys
```

---

## In-game: how to use this tool (home playbook)

Soft Lab **does not talk to Warzone by itself**. It is the **safe math twin** of Class 2.
You tune `TOTAL_hip` / `TOTAL_ads` here, export a profile, then prove the same totals
**in-game** on Class 2 (`track-b`) with your stock `km.move` app (or Swipe Lab later).

### Before you touch the game

1. Run Soft Lab: `python -m soft_makcu`
2. Confirm goldens: press `1` / `2` / `3` → ix chips should hit **11592 / 29119 / 32767**
3. SoftAxis chips should show green: **CLEAN STOP · NO CARRY · NO OVERSHOOT · RATIO 1.33**
4. Note the on-screen **hip=… ads=…** (defaults 2400 / 1800)
5. Press `E` → saves `soft_makcu/exports/soft_makcu_profile_….json`

### In Warzone (prove the 360)

Use these game settings every time:

| Setting | Value |
|---|---|
| Look sens | **2.00** |
| Aim (ADS) sens | **1.50** |
| Stance for hip test | **Hip-fire** (not ADS) |
| Stance for ads test | **ADS held** the whole pulse |

1. Drop somewhere flat with a **clear landmark** (door, tower, buy station, unique rock).
2. Aim the crosshair at that landmark. That is your **T0** heading.
3. Fire one **hip** pulse using the same `TOTAL_hip` your Soft Lab shows (stock app / Class 2 inject = that many `km.move` counts paced ~8 ms).
4. Watch the camera. Did you land back on the same landmark (~one full turn)?
5. Repeat for **ADS** with `TOTAL_ads` (hold ADS the whole time).

Soft Lab keys that mirror those pulses on the **sim sticks** (not the game):

| Key | What it does |
|---|---|
| `H` | Run current **hip** TOTAL through SoftMakcu |
| `A` | Run current **ADS** TOTAL |
| `[` / `]` | Nudge **hip** TOTAL down / up |
| `;` / `'` | Nudge **ADS** TOTAL down / up |
| `E` | Export profile JSON for me / for Class 2 later |
| `R` | Reset engine |

---

## What to send me (Xim) — copy this every time

After each serious run, send **all** of:

1. The export file: `soft_makcu/exports/soft_makcu_profile_….json` (press `E`)
2. A short note with these lines filled in:

```text
look=2  aim=1.50
TOTAL_hip=____   result= success | over | short
TOTAL_ads=____   result= success | over | short
landmark=____ (what you aimed at)
notes=____
```

3. Optional but useful: a phone clip or screenshot of the landing (over / short / on-target).

That JSON + those numbers is enough for me to tell you the next TOTAL / ratio tweak without another flash cycle.

---

## Successful 360 — what “good” looks like + what to give me

**In Soft Lab:** after `H` or `A`, chips stay **CLEAN STOP · NO CARRY · NO OVERSHOOT**, stick returns to center, ratio chip stays near **1.33**.

**In-game:** one pulse ≈ **one full turn**, crosshair lands back on the **same landmark** (within a tight miss — think “same door frame,” not half a building over). No extra spin after the pulse ends. No floaty mush at the end.

**Send me:**

- Export JSON (`E`)
- `result=success` for hip and/or ads
- Exact `TOTAL_hip` / `TOTAL_ads` that worked
- One line: “landed on [landmark]”

I will lock those as your Class 2 starter totals.

---

## Going OVER (past the landmark) — what to do

**Means:** TOTAL is too big (or ADS total too big vs hip).

**In Soft Lab**

1. Lower the total that overshot: hip → `[` a few times; ads → `;`
2. Press `H` or `A` again and watch chips (still want CLEAN STOP / NO OVERSHOOT on the sim)
3. Keep hip:ads near **1.33** (if you cut hip a lot, cut ads too, or ratio goes red)

**In-game**

1. Same landmark, same sens (2 / 1.50)
2. Re-run with the **lower** TOTAL
3. If still over → lower again (~10–15% per step is fine: e.g. 2400 → 2100 → 1800)
4. If suddenly **short** → you bracketed it; split the difference

**Send me:**

```text
result=over
TOTAL_hip_tried=____  TOTAL_ads_tried=____
about_how_far_past= e.g. "90° past" / "half turn extra" / "barely past"
next_TOTAL_I_will_try=____
```

Plus the latest export JSON after you nudge.

---

## Not reaching the target (SHORT) — what to do

**Means:** TOTAL is too small.

**In Soft Lab**

1. Raise the short total: hip → `]` ; ads → `'`
2. Re-run `H` / `A`
3. Keep ratio ~**1.33** (raise ads with hip)

**In-game**

1. Same landmark + sens
2. Bigger TOTAL (~10–15% up: 2400 → 2760 → …)
3. If you jump from short → way over, split the difference (binary search)

**Send me:**

```text
result=short
TOTAL_hip_tried=____  TOTAL_ads_tried=____
about_how_far_left= e.g. "stopped ~90° early" / "almost there"
next_TOTAL_I_will_try=____
```

Plus export JSON.

---

## Quick decision table

| What you see in-game | Do this | Tell me |
|---|---|---|
| Lands on landmark, clean stop | Press `E`, stop changing that TOTAL | `success` + JSON + totals |
| Spins past landmark | Lower TOTAL (`[` / `;`), retry | `over` + how far past + JSON |
| Stops before landmark | Raise TOTAL (`]` / `'`), retry | `short` + how far early + JSON |
| Keeps drifting after pulse ends | Soft/Class 2 carry bug — don’t raise TOTAL | `carry` + clip if you can |
| Hip OK but ADS wrong (or reverse) | Fix the bad total only; watch ratio 1.33 | which stance failed + both totals |

---

## Do / don’t

**Do**

- Always use look **2** / aim **1.50** when judging 360s
- Change **one** total at a time when possible
- Export (`E`) after every “this one felt right” run
- Prefer Soft Lab + JSON here before flashing Class 2 again

**Don’t**

- Don’t flash the board to try every TOTAL (that’s why Class 3 exists)
- Don’t mix hip and ADS judgments in one pulse
- Don’t send vibes only — send **numbers + export JSON**
