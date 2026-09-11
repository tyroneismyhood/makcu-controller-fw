# tools/

Small helper utilities that aren't part of day-to-day use.

| File | What |
|------|------|
| `button_mapper.py` | Interactive logger: press each controller button when prompted, it captures which bit lights up in the telemetry `b=` mask and writes `button_map.json`. The GUI Monitor tab reads that file to show button names (e.g. `LB + RB`) instead of raw hex. Run once per controller model. |
| `button_map.json` | Output of the mapper (created on first run, one per repo checkout — remap if you switch controller models). |
| `kmh_fidelity_csv.py` | Track B proof CSV: paced `km.move` @ 8 ms (8/80/240→stop), merge on `KMH tick/ix/iy` (not KMS). Soft vs late vs carry. Needs Bench green sheet + CH343. |

```
python tools/button_mapper.py          # auto-detects the CH343 port
python tools/button_mapper.py COM5     # or name it explicitly
python tools/kmh_fidelity_csv.py COM5 --out kmh_fidelity.csv
python tools/kmh_fidelity_csv.py COM5 --rest-p99   # suggest km.idle_dz(N)
```

Notes:
- Triggers and sticks are analog — they don't appear in the `b` bitmask
  (sticks are the `lx/ly/rx/ry` fields; triggers aren't in telemetry yet).
- Mapping is per controller family (GIP pads generally share one layout).
- `KMH` is always-on after curve drain; expected = `C×|accum|^P` (5046 / 0.40).
  Do not join `KMS` for curve proof (pre-apply, 16 ms).
