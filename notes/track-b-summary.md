# Track B — Matrix-quality M&K ↔ stick translation

**Branch:** `track-b/matrix-translation` (based on `track-a/passthrough-fidelity` @ 8155926)
**Goal:** Matrix-like feel on MAKCU without a physical XIM Matrix — tight
latency, clean curves, no overshoot/carryover, no drift. Legitimate
high-fidelity input translation only (no aimbot / recoil / anti-cheat bypass).

## Pipeline map

```
km.move(dx,dy)
  -> applyMouseDelta()           # sum into g_vel_accum_*
  -> km_housekeep_cb @ 8 ms
       drain accum -> xim_curve(C=5046, P=0.40) -> rx/ry_injected
       emit KMH tick= ix= iy=   # always on (Track B / Firmware contract)
  -> synth timer @ 4 ms (injection-only; Track A)
       re-submit cached real report + km_apply overlay
  -> km_apply on every IN
       if !modify: telem-only, wire-perfect (Track A)
       extract physical RS; idle_dz only if inj live (default 0)
       optional trim + steady (a11y, OFF by default)
       blend_stick (user-priority XIM asymmetric)
       write GIP (EP 0x81|0x82) / XInput / DS5
```

C/P and the 8 ms drain window are **unchanged** (Matrix-fit defaults).

## What softens accuracy (findings)

| Factor | Status | Effect |
|--------|--------|--------|
| Tremor `steady` filter | OFF by default | Lag + deadzone when enabled — a11y only |
| Physical idle deadzone | Was 4000 always-on; now **default 0**, live `km.idle_dz` | Old value softened micro-aim and idle soft axes |
| Idle rewrite in passthrough | Fixed in Track A | Deadzone path no longer runs when injection/filters off |
| GIP EP assume 0x82 only | Fixed in Track B | Elite 1698 on 0x81 skipped inject entirely |
| 8 ms window + power curve | By design | Boundary phase can change flick magnitude (nonlinear) |
| Upstream pacing | Sender-owned | Irregular km.move cadence still modulates feel |

Clarification: tremor filter was **never** default-on; the always-on softener
was the physical idle deadzone (now default 0).

## Changes on this branch

### Firmware contract (plus Matrix translation)
1. `PHYSICAL_IDLE_DEADZONE` default **0**; runtime `_Atomic idle_dz`; `km.idle_dz(N)`.
2. GIP `km_apply` accepts **EP 0x81 or 0x82** (Elite-class + One S / Series X).
3. Always-on housekeep stamp: `KMH tick=%u ix=%ld iy=%ld\n` after curve drain
   (`km_uart_write_raw`, independent of KM_RING / COM3_LOG / km.telem).

### Inherited from Track A (kept via rebase)
- Wire-perfect passthrough when injection + steady + trim are off
- `clean_idle` only while injection live
- Synth gated to injection only
- Left IPC mid-frame resync; Right GIP kickstart rate-limit

### Python
- `makcu_access.idle_dz(N)`; `read_telem()` yields KMS and KMH (`_kind`)
- `makcu_monitor` skips KMH in shake samples; documents Matrix idle_dz=0

### Explicitly NOT changed
- Curve C/P (5046 / 0.40)
- 8 ms drain tick / window model
- No game-specific aim / recoil / anti-cheat logic

## Matrix-feel acceptance checklist

- [ ] `km.idle_dz(0)` (default) + `km.steady(0)` — no firmware softening
- [ ] Mouse stop -> stick neutral within one 8 ms drain (no overshoot / carryover)
- [ ] KMH lines stream at ~125 Hz with ix/iy tracking moves; zero after stop
- [ ] Elite 1698 (EP 0x81) receives GIP inject same as 0x82 pads
- [ ] Idle controller, no km moves: report bytes unmodified (Track A)
- [ ] Noisy pad only: raise `km.idle_dz` to rest |p99|; micro-aim still OK at 0
- [ ] Dual-input: same-sign blend headroom not eaten by idle DZ at default 0
- [ ] No game-specific macros / recoil / anti-cheat logic

## Residual risks

1. Nonlinear 8 ms window splitting remains (Matrix model).
2. KMH always-on adds UART load at 4 Mbaud — fine for CH343; leave telem KMS off in gameplay.
3. No physical Matrix A/B — acceptance is feel + KMH/telem heuristics.
4. Pads with huge rest noise may need non-zero idle_dz; measure |p99| first.

## Conflicts / coordination

| File | Track B | Track A |
|------|---------|---------|
| km_inject.c | idle_dz, KMH, GIP 0x81|0x82 | modify-guard, clean_idle | Combined on this branch |
| ipc / pass_usb / PassUsbHost | none new | Track A commits | Inherited via rebase |

