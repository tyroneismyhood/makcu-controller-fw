# Track A — Passthrough fidelity (injection / accessibility OFF)

## Report path (Left ↔ Right)

```
Controller ──USB──► Right (PassUsbHost::in_xfer_complete)
                      │ FRAME_EP_IN @ 5 Mbps IPC UART
                      ▼
                    Left ipc_rx_task → ipc_handle_frame
                      │
                      ▼
                    pass_usb_submit_in → submit_in_core
                      │ km_apply (telem / optional modify)
                      ▼
                    TinyUSB usbd_edpt_xfer → Console/PC

Console OUT/CTRL ──► Left pass_driver_* ──FRAME_EP_OUT/CTRL──► Right submit_*
```

## Findings

1. **Soft/off sticks when injection was “off” (critical)**  
   `km_apply` still ran extract → `PHYSICAL_IDLE_DEADZONE` (4000) → `apply_*`
   whenever either stick axis exceeded the deadzone, even with zero injection
   and accessibility filters disabled. Soft deflection on one axis was
   hard-zeroed when the other moved — felt like added deadzone / soft center.

2. **GIP synth only when injection active (OK, clarified)**  
   Synth timer already keyed off `km_has_active_injection()`, but comments
   were weak. Accessibility (steady/trim) must never arm synth (would change
   report cadence vs a wired pad).

3. **Idle deadzone used outside injection**  
   Same `PHYSICAL_IDLE_DEADZONE` ran for accessibility-only paths, softening
   sticks before steady/trim. Injection blend still needs it; passthrough and
   a11y-only must not.

4. **Left IPC mid-frame wedge**  
   Right already resets the RX state machine after 10 ms of silence mid-frame.
   Left did not — a dropped byte at 5 Mbps could discard subsequent `EP_IN`
   until magic resync by chance (dropped reports / lag spikes).

5. **GIP kickstart spam on announce**  
   Every announce (`0x02`) triggered identify/power/LED until first input.
   Announce ~500 ms; spamming OUT during bring-up can delay first `0x20`.

## Changes

| File | Why |
|------|-----|
| `firmware/.../Left.../km_inject.c` | `km_wants_report_modify()`; wire-perfect early return (telem only, bytes untouched); `clean_idle` only when injection live |
| `firmware/.../Left.../pass_usb_device.c` | Document injection-only synth; reinforce no-synth when idle |
| `firmware/.../Left.../ipc.c` | 10 ms mid-frame RX inactivity resync (parity with Right) |
| `firmware/.../Right.../PassUsbHost.cpp` + `.h` | Rate-limit GIP kickstart ≥400 ms; reset on new device; header comment fix |

## How to verify on hardware

1. Flash **both** Left and Right from this branch; **power-cycle** after Right flash.
2. Confirm filters/injection off: do **not** send `km.move` / `km.click` / `km.steady(1)` / `km.trim(...)`. Optional: `km.telem(1)` and watch `n=` climb with stick motion.
3. Quiet Left build preferred (`COM3_LOG=0`) so UART logging does not add jitter.
4. **Feel test:** rest sticks (no soft pull), then slow micro-moves near center — should match a direct USB cable (no hard deadzone “notch”).
5. **Cadence:** with `COM3_LOG=1` briefly, `EP_IN` / `IN done` should track controller activity only — no 4 ms synth stream while idle.
6. **GIP bring-up:** Xbox/GIP pad should leave announce and stream `0x20` without OUT floods (logs show kickstart ~once per ≥400 ms until input).
7. A/B: same pad direct to console vs through MAKCU; camera/look near center should feel equivalent.

## Residual risks

- **IN coalescing:** if a new report arrives while TinyUSB `in_flight`, the pending slot keeps only the latest — intermediate samples drop under load (inherent single-slot design).
- **Synth timer still ticks at 4 ms** even when idle (early-return only) — minor CPU wake; does not emit USB traffic.
- **IPC 5 Mbps + CRC drops** can still lose a frame; watchdog recovers the parser but cannot resurrect the lost payload.
- **Right `ipc_rx_task` 1 ms poll** adds up to ~1 ms Left→Right OUT/CTRL latency (rumble path), not the input path.
- **String descriptors** still via `usb_device_info` (not always byte-exact) — enum cosmetics, not stick fidelity.
