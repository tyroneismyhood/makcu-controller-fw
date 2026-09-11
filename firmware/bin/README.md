# Prebuilt flash images

Merged full-flash images built from **this branch's** source, flashed at
offset `0x0` (bootloader + partition table + app in one file). The images
always match the checked-out branch — different branches ship different
bins.

**This build: 2026-09-11, `track-b/matrix-translation` branch** (Track B
Matrix-feel Class 2 — quiet Left + Right GIP host).

| File | MCU | Build |
|------|-----|-------|
| `MERGED_left.bin` | Left (USB1, console-facing) | Quiet build (`COM3_LOG=0` `KM_DIAG=0` `KM_RING=0` `LAT_DIAG=0`) — idle_dz default 0, KMH telemetry, GIP EP 0x81\|0x82, Track A wire-perfect when injection off, XIM-fit curve C=5046 P=0.40 |
| `MERGED_right.bin` | Right (USB3, controller host) | Includes the GIP init fix |

Check what is actually flashed on a board: `python accessibility/makcu_access.py`
— the `km.version()` reply contains the Left build date (`Sep 11 2026` = this
Track B build; `Jul  8 2026` = old `main` release bins — reflash both MCUs).

Or from the 2nd PC over USB2 CH343 @ 4e6:

```bash
python tools/swipe_test.py COM5
```

Target: ESP32-S3, 4 MB flash, DIO @ 80 MHz (do not re-merge with QIO — it
won't boot).

`../flash_tool.py` looks for these files here by default. Flash manually
with:

```bash
esptool.py --chip esp32s3 --port <COM> --baud 921600 write_flash 0x0 <file>
```

If you build from source yourself, the PlatformIO output lands in each
project's `.pio/build/<env>/` — either flash those images directly with
PlatformIO's `-t upload`, or drop your own merged images here (same names)
for the flash tool to pick up. Merge with:

```bash
esptool --chip esp32s3 merge-bin --flash-mode dio --flash-freq 80m --flash-size 4MB \
  -o firmware/bin/MERGED_left.bin \
  0x0  .pio/build/LEFT_IDF/bootloader.bin \
  0x8000 .pio/build/LEFT_IDF/partitions.bin \
  0x10000 .pio/build/LEFT_IDF/firmware.bin
```

**`stock/` (not in the repo):** put saved vendor stock binaries here if you
want a rollback path — see the Rollback section of
[../../FLASHING.md](../../FLASHING.md). Vendor binaries are not distributed
with this repo.
