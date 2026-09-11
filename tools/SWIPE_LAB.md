# Swipe Lab — operator guide (Track B)

Lab laptop tooling for MAKCU Matrix-feel: objective KMH curve, rest idle_dz,
hip/ADS 360 feel, Elgato preview, schema v2 JSON. Calibration only — no
game-specific aimbot/recoil. Firmware curve stays `C=5046 P=0.40` / 8 ms.

Full capture failure modes + void gates: [`/workspace/bench/ELGATO_SWIPE_LAB_BRINGUP.md`](../../bench/ELGATO_SWIPE_LAB_BRINGUP.md)
(or repo-adjacent Bench doc). Plug map: [`docs/TRACK_B_SETUP.md`](../docs/TRACK_B_SETUP.md).

---

## Topology

| Port | Where | Role |
|------|--------|------|
| **USB1** (left) | **Main game PC** | USB device → game (powers board) |
| **USB2** (middle) | **2nd / lab laptop** @ **4 000 000** baud | CH343 `km.*` + KMH/KMS telem |
| **USB3** (right) | Controller / mouse host | Real pad or transmitter |
| **HDMI** | Main PC → **Elgato on lab** | Vision preview / future 360 score |

Score vision on lab; telem on lab USB2. **Never** merge vision↔telem on raw
dual-PC wall clocks — use lab monotonic + `lag_offset_ms` → KMH tick window.

---

## Deps

```bash
pip install pyserial
pip install opencv-python          # recommended (preview + device enum)
pip install ultralytics            # optional YOLO (yolov8n)
# OR:
pip install onnxruntime            # optional ONNX detector backend
# Windows: OpenCV uses DirectShow for Elgato — quit 4K Capture Utility / OBS exclusive first
```

OpenCV is optional for objective/KMH CLI; UI preview degrades to placeholder text.
`ultralytics` / `onnxruntime` are **optional imports** — UI runs without YOLO, but
vision score is **void** if a detector is required and unavailable
(`tools/yolo_roi.py`).

---

## Import map (Tools lock — single implementation)

| Concern | Module | Import |
|---------|--------|--------|
| Schema v2 writers | `tools/swipe_results_lib.py` | `new_report`, `add_test`, `apply_preflight`, `write_results` |
| Acceptance thresholds | `tools/swipe_acceptance.py` (+ re-export `swipe_core`) | `ACCEPTANCE`, `MATRIX_LABELS`, `score_band`, `acceptance_block` |
| Void-gates + lag calib | **`tools/swipe_preflight.py`** | `VoidReason`, `check_void_gates`, `LagCalibration`, `begin_lag_calib_flash`, `preflight_schema_fields`, `score_allowed` |
| Elgato enum / open | `tools/elgato_capture.py` | `list_devices`, `find_elgato`, `pin_elgato`, `open_capture`, `is_frame_black` |
| UI keybinds contract | `tools/swipe_keybinds.py` | `KEYBINDS`, `WAITKEY_MAP`, `action_for_waitkey`, `keybind_help_lines` |
| Constants shim | `tools/swipe_core.py` | re-exports acceptance only (pulse paths still in `swipe_test.py`) |

**swipe_ui must `import` preflight — do not rewrite void/lag logic in the UI.**

```python
from swipe_preflight import (
    VoidReason, PreflightState, check_void_gates,
    LagCalibration, begin_lag_calib_flash,
    preflight_schema_fields, score_allowed,
)
from elgato_capture import list_devices, pin_elgato, open_capture
from swipe_results_lib import new_report, apply_preflight, write_results
from swipe_keybinds import KEYBINDS, action_for_waitkey
from swipe_core import ACCEPTANCE, MATRIX_LABELS
```

---

## Void-gates (preflight REQUIRED before any vision score)

Void ≠ soft/late. If any gate fails → `void: true` + `void_reason` in JSON;
**do not** FAIL firmware on a void run.

1. Camera index = **pinned Elgato by name/VID** (not silent index 0)
2. No black / HDCP / exclusive lock during spin
3. Dropped frames == 0 in scored window
4. Capture lag offset **known** (calib once: flash/LED vs lab monotonic) and unchanged
5. Flash sheet green (both bins, power-cycle, filters off) — UI checklist
6. Vision joined via **lab monotonic + lag_offset_ms → KMH tick** — never raw dual-PC wall clock
7. ROI/colorspace stable mid-session

`check_void_gates(state) -> VoidCheckResult` / `score_allowed(state) -> bool`.

### Lag calib

```python
lag = begin_lag_calib_flash(
    flash_monotonic=t_flash,
    observed_frame_monotonic=t_frame,
    device_name=pinned["name"],
    device_index=pinned["index"],
)
lag.save()  # tools/results/lag_calib.json
# join: vision_t = lag.vision_time_lab(frame_monotonic)
```

Keybind contract: **`l`** = lag calib, **`f`** = run preflight, **`g`** = toggle flash-sheet-green.

---

## Accuracy+Matrix v1 thresholds (schema `acceptance`)

| Metric | PASS | SOFT |
|--------|------|------|
| yaw / feat | ≤ 2° | ≤ 5° |
| ecc | ≥ 0.92 | ≥ 0.85 |
| phase | ≥ 0.90 | ≥ 0.80 |

- **All-four fusion** required for overall PASS: yaw + ecc + phase + matrix
- HIP/ADS TOTAL ratio **1.333 ± 3%** (defaults 2400 / 1800)
- Matrix labels: `CLEAN STOP` | `NO CARRY` | `NO OVERSHOOT` | `RATIO 1.33`

---

## Keybinds (OpenCV UI contract)

Authoritative: `tools/swipe_keybinds.py` (`python tools/swipe_keybinds.py`).

| Key | Action |
|-----|--------|
| **`r`** | **set/search ROI** (Dylan lock) |
| **`d`** | **cycle detector** yolov8n/onnx (Dylan lock) |
| **click** | **lock target in ROI** (Dylan lock) |
| `0` / `1` | snap YOLO T0 (before 360) / T1 (after 360) |
| `o` | objective KMH curve suite |
| `h` | hip 360 (look=2) |
| `m` | ADS 360 (aim=1.50, `km.right` hold) |
| `i` | rest idle_dz measure |
| `a` | apply suggested idle_dz |
| `[` / `]` | TOTAL −15% / +15% |
| `u` / `v` / `k` | feel under / over / ok |
| `p` | game-pulse |
| `s` | save JSON+txt (schema v2) |
| `c` | reconnect / pick serial (prefer CH343) |
| `e` | cycle Elgato/capture device |
| `l` | lag calib |
| `f` | preflight void-gate check |
| `g` | toggle flash-sheet-green |
| `q` / Esc | quit (release ADS) |

Remap note: earlier drafts used `r`=rest and `d`=ADS — those moved to `i` / `m`.

### YOLO T0→T1 flow (peer HUD)

1. `r` set ROI → click lock target  
2. `0` snap **yolo_t0** in ROI  
3. run 360 (`h`/`m`)  
4. `1` snap **yolo_t1**  
5. `bbox_center_delta(t0, t1)` → schema **delta** `{dx_px, dy_px, d_px, yaw_deg_est?}`  
6. `s` save schema v2  

Do not implement full YOLO scorer inside swipe_ui — import `yolo_roi`.

---

## How to run

```bash
# CLI objective (lab USB2 CH343):
python tools/swipe_test.py COM5
python tools/swipe_test.py COM5 --360
python tools/swipe_test.py COM5 --game-pulse 40

# UI (when peer ships tools/swipe_ui.py):
python tools/swipe_ui.py COM5 --capture "Elgato"
python tools/swipe_ui.py COM5 --capture 1 --width 1920 --height 1080

# Enum capture devices:
python tools/elgato_capture.py

# Smoke schema / preflight:
python tools/swipe_results_lib.py
python tools/swipe_preflight.py
```

---

## Schema v2 stamp (minimum for scored/void runs)

```
schema_version: 2
hardware.capture_device   # pinned name
hardware.capture_index
hardware.lag_offset_ms
void / void_reason / void_reasons
preflight{gates, flash_sheet_*, lag, ...}
acceptance{thresholds, matrix_labels}
firmware_defaults{C, P, idle_dz, steady, trim}
roi: {x,y,w,h}
yolo: {backend: ultralytics|onnx, model: yolov8n|path, conf}
yolo_t0 / yolo_t1: [{cls, conf, xyxy|cxcywh}]
delta: {dx_px, dy_px, d_px, yaw_deg_est?}
```

Helpers: `set_yolo_roi` / `apply_yolo_block` in `swipe_results_lib`;
`schema_yolo_block` / `bbox_center_delta` in `yolo_roi`.

Use `apply_preflight(report, preflight_schema_fields(state))` before `write_results`.


---

## Peer UI (OpenCV lab)

```bash
pip install pyserial opencv-python numpy
# optional YOLO:
pip install ultralytics   # or onnxruntime + yolov8n.onnx

python tools/swipe_ui.py --preflight-only
python tools/swipe_ui.py --port COM5 --lab
# keys: r ROI, d detector, click lock target, 0/1 T0/T1 snaps, h/m hip/ads,
#       a Run All (objective+rest+YOLO 360 + schema v2 JSON), s save, q quit
python tools/swipe_ui.py --port COM5 --run-all   # writes tools/results/swipe_results_*.json
```

Binary-search T* uses **YOLO** close error only (not optical flow). Final PASS
still needs flow+ECC+phase; YOLO replaces feat_return. If YOLO PASS but
yaw_flow SOFT/FAIL → `SCALE_DISAGREE` (no promote).
