# Controller bridge over the official MAKCU API

The controller still passes through to the target as its original USB device.
The second laptop does not receive that HID connection; Blurred receives the
translated state over the middle CH343 serial port.

No Python process or private command protocol is involved.

## Button mapping

MAKCU exposes five mouse-button bits, so five controller controls can be
represented without extending the API:

| Mask | MAKCU control | Xbox | PlayStation |
|------|---------------|------|-------------|
| `0x01` | left | RT | R2 |
| `0x02` | right | LT | L2 |
| `0x04` | middle | X | Square |
| `0x08` | side1 | LB | L1 |
| `0x10` | side2 | RB | R1 |

The firmware decodes Xbox GIP, Xbox 360 XInput, DualShock 4, DualSense, and
DualSense Edge reports. Trigger values cross the pressed threshold at roughly
6% travel. Releases emit a complete `0x00` snapshot when no mapped controls
remain pressed.

The official mouse mask has no distinct bits for the other controller buttons.
Representing those would require a non-MAKCU command, which this firmware does
not add.

## Legacy protocol

Blurred's legacy KMBox path enables raw physical events with:

```text
km.buttons(1)\r\n
```

Each change is emitted in the legacy MAKCU wire form used by existing KMBox
clients: the bytes `k`, `m`, `.` followed by one raw mask byte. For example:

```text
LT down:  6B 6D 2E 02
LT up:    6B 6D 2E 00
```

`km.buttons(2,period_ms)` selects the constructed stream. `km.buttons(0)`
disables it, and `km.buttons()` queries the mode. The official `km.axis` and
`km.mouse` stream commands are also accepted; the physical right stick is
translated into relative X/Y values with a radial deadzone and progressive
fixed-point curve.

## V2 binary protocol

V2 uses the official frame:

```text
50 CMD LEN_LO LEN_HI PAYLOAD...
```

To enable a 1 ms raw button stream:

```text
Host:   50 02 02 00 01 01
Device: 50 02 01 00 00
```

An LT transition then produces:

```text
LT down: 50 02 02 00 02 00
LT up:   50 02 02 00 00 00
```

Supported V2 compatibility commands are the official button stream (`0x02`),
axis stream (`0x01`), mouse stream (`0x0C`), five individual mouse buttons,
click (`0x04`), move (`0x0D`), raw mouse frame (`0x0B`), device (`0xB3`),
echo (`0xB4`), and version (`0xBF`).

## What LT does

Pulling LT/L2 has two simultaneous effects:

1. Its untouched controller report continues to the game.
2. If Blurred enabled `buttons`, the communicator receives mouse-right bit
   `0x02` over serial. Releasing LT sends the corresponding release snapshot.

Serial streaming is independent of which application has keyboard focus.
Blurred must have the CH343 port open and enable a button stream.
