# On-device configuration (XIM-style)

The flashed firmware is configurable from the **same BOOT buttons used for
flashing**, without a PC app. The feel matches XIM Matrix pairing: everything
plugged in, long-press the button until the LED changes, then navigate.

## Connection (like XIM + MAKCU)

Plug **all three** USB roles before configuring:

| Port | Role | Why it matters |
|------|------|----------------|
| **USB1** (Left) | Device → target PC / console / XIM | Host must see the pad (pipeline live) |
| **USB2** (middle CH343) | Communicator COM port | Status lines (`[CFG] …`) print here |
| **USB3 / Right OTG** | Real controller | Firmware unlocks config only when the controller is ready |

USB2 is not VBUS-sensed in firmware (CH343 is a separate chip). Plug it so you
can read status on the COM port; unlock itself requires **USB1 host-visible +
controller ready**.

## Buttons

| Button | Where | Action |
|--------|-------|--------|
| **Left BOOT** | next to USB1 | **Long-press ~2 s** → enter config / **save + exit**. **Short-press** → next setting category |
| **Right BOOT** | next to USB3 | **Short-press** → next value in the current category |

Long-press timing matches XIM Matrix’s ~2 s pairing hold.

## Settings (categories)

1. **telem** — physical stick/trigger telemetry stream on the KM COM port (`0/1`)
2. **steady** — tremor damp on the aim stick (`0/1`)
3. **gain** — XIM curve sensitivity preset: `0=low`, `1=xim` (default), `2=high`

Values are stored in NVS and survive reboot. Changing a value applies **live**
(no reflash).

## LED legend (Left diag LED)

While config is active, blink speed shows category + value:

| Category | Off / low | On / mid / high |
|----------|-----------|-----------------|
| telem | slow (~500 ms) | fast (~70 ms) |
| steady | slow (~450 ms) | fast (~90 ms) |
| gain | slow / medium / very fast for low / xim / high |

Normal pipeline LED rates resume after you save & exit.

## Serial (optional)

Same settings are also available on the KM UART (USB2) if you want to script them:

```
km.cfg()       # dump current config
km.telem(0|1)
km.steady(0|1)
km.gain(0|1|2) # low / xim / high
km.steady_a(N)
km.steady_d(N)
km.trim(x,y)
```

Button changes and serial changes both write NVS.

## Firmware files

| File | Role |
|------|------|
| `firmware/MAKCM_ESP32s3_Pass_Left_IDF/src/km_cfg.c` | NVS, Left BOOT FSM, LED override, settings |
| `firmware/MAKCM_ESP32s3_Pass_Left_IDF/include/km_cfg.h` | API |
| `pass_ipc.h` (`FRAME_BTN`) | Right BOOT → Left |
| `firmware/MAKCM_ESP32s3_Pass_Right/src/main.cpp` | Right BOOT GPIO poller |

Reflash **both** Left and Right images after pulling this change (Right must
understand/`emit` `FRAME_BTN`).
