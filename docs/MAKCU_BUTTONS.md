# Physical pad → MAKCU `km.buttons` (official API)

The communicator menu on the **2nd laptop** does **not** speak gamepad HID.
It talks the official MAKCU KM serial API over the CH343 COM port and expects
**mouse button** events.

## What was broken

The pad played fine on the target (USB passthrough). The blurred menu on the
communicator PC never saw LT/RT because firmware never implemented the official
button stream those menus enable:

```text
km.buttons(1)     # menu enables this
```

## Fix (official API only)

Firmware now implements the verified MAKCU button stream:

| Host command | Behavior |
|--------------|----------|
| `km.buttons(1)` | Enable stream |
| `km.buttons(0)` | Disable stream |
| `km.buttons()` | Query enabled → `0` / `1` |
| `km.left()` / `km.right()` / … | Query pressed → `0` / `1` |

When enabled, each change emits the official wire form:

```text
km. <mask_u8>
```

(`k` `m` `.` + one raw mask byte — same as real MAKCU / makcu-rs.)

### Mask mapping (pad → mouse bits)

| Bit | Mask | MAKCU button | Physical pad |
|-----|------|--------------|--------------|
| 0 | `0x01` | left | **RT** (fire) |
| 1 | `0x02` | right | **LT** (ADS) |
| 2 | `0x04` | middle | X / middle inject |
| 3 | `0x08` | ms1 | LB |
| 4 | `0x10` | ms2 | RB |

So if your menu binds an activation key to **mouse right**, pull **LT** on the
pad. Bind to **mouse left** → pull **RT**.

## What you do

1. Flash updated **Left** firmware.
2. Open the communicator menu on the 2nd laptop (it should already call
   `km.buttons(1)` — that is the MAKCU API, not a custom protocol).
3. Pull LT/RT on the physical pad — the menu should see right/left mouse
   button events even while another window is focused (serial is not
   focus-gated).

No Python helper is required. Do not use custom `KMS` telemetry for activation
keys; use `km.buttons` only.
