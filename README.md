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
