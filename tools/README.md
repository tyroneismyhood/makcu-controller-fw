# tools/

Helper utilities for MAKCU Track B lab work.

| File | What |
|------|------|
| `button_mapper.py` | Interactive logger: press each controller button when prompted, captures which bit lights up in telemetry `b=` and writes `button_map.json`. GUI Monitor tab reads that file. |
| `button_map.json` | Output of the mapper (per checkout — remap if you switch controller models). |
| `kmh_fidelity_csv.py` | Track B proof CSV: paced `km.move` @ 8 ms (8/80/240→stop), merge on `KMH tick/ix/iy` (not KMS). Soft vs late vs carry. |
| `swipe_test.py` | CLI PASS/FAIL objective KMH + `--360` hip/ADS feel + idle_dz + `--game-pulse`. |
| **`swipe_results_lib.py`** | **Schema v2** JSON/txt writers (`void`, `lag_offset_ms`, acceptance, calibration, idle_dz). |
| **`swipe_acceptance.py`** | Accuracy+Matrix v1 thresholds + Matrix labels (single source). |
| **`swipe_core.py`** | Re-exports acceptance constants for UI/Accuracy (pulse paths still in `swipe_test`). |
| **`swipe_preflight.py`** | **Shared** void-gates + Elgato lag calib — `swipe_ui` must import, not rewrite. |
| **`elgato_capture.py`** | OpenCV device enum; pin Elgato by name/VID; `open_capture` helpers. |
| **`swipe_keybinds.py`** | OpenCV UI keybind contract (`KEYBINDS` / `WAITKEY_MAP`). |
| **`yolo_roi.py`** | Thin YOLO-in-ROI detect + T0→T1 `bbox_center_delta` (optional ultralytics/onnxruntime). |
| **`SWIPE_LAB.md`** | Operator guide: topology, void-gates, keybinds, import map. |

```
python tools/button_mapper.py          # auto-detects the CH343 port
python tools/button_mapper.py COM5     # or name it explicitly
python tools/kmh_fidelity_csv.py COM5 --out kmh_fidelity.csv
python tools/kmh_fidelity_csv.py COM5 --rest-p99   # suggest km.idle_dz(N)
python tools/swipe_test.py COM5
python tools/swipe_test.py COM5 --360
python tools/elgato_capture.py         # list capture devices
```

## Swipe Lab

See **[SWIPE_LAB.md](SWIPE_LAB.md)** for plug map, void-gates, lag calib, schema v2,
and keybinds. Product UI (`swipe_ui.py`) is owned by the peer builder and must:

```python
from swipe_preflight import check_void_gates, LagCalibration, preflight_schema_fields
from elgato_capture import pin_elgato, open_capture
from swipe_results_lib import new_report, apply_preflight, write_results
from swipe_keybinds import KEYBINDS, action_for_waitkey
```

### Deps

- **Required:** `pyserial`
- **Recommended:** `opencv-python` (Elgato preview / enum; Windows DirectShow)
- OpenCV missing ⇒ objective/KMH CLI still works; UI runs without live video

### Keybinds (contract)

| Key | Action |
|-----|--------|
| **`r`** | set/search ROI | **`d`** cycle detector | **click** lock target |
| `0`/`1` | snap yolo_t0 / yolo_t1 | `o` objective | `h` hip | `m` ADS |
| `i` rest idle_dz | `a` apply idle_dz | `s` save v2 | `e` Elgato | `l` lag |
| `f` preflight | `g` flash sheet | `q`/Esc quit |

Authoritative list: `python tools/swipe_keybinds.py`

