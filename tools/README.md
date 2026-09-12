# tools/

Small helper utilities that aren't part of day-to-day use.

| File | What |
|------|------|
| `button_mapper.py` | Interactive logger: press each controller button when prompted, it captures which bit lights up in the telemetry `b=` mask and writes `button_map.json`. The GUI Monitor tab reads that file to show button names (e.g. `LB + RB`) instead of raw hex. Run once per controller model. |
| `button_map.json` | Output of the mapper (created on first run, one per repo checkout — remap if you switch controller models). |

```
python tools/button_mapper.py          # auto-detects the CH343 port
python tools/button_mapper.py COM5     # or name it explicitly
```

Notes:
- Digital face/bumper bits are in `b=`. Sticks are `lx/ly/rx/ry`.
- Analog triggers are separate: `lt=` / `rt=` on a 0..1023 scale (requires a
  Left MCU firmware build that emits them).
- Mapping is per controller family (GIP pads generally share one layout).
