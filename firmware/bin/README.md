# Prebuilt flash images

Merged full-flash images built from **this branch's** source, flashed at
offset `0x0` (bootloader + partition table + app in one file). The images
always match the checked-out branch — different branches ship different
bins.

**This build: 2026-09-12, `cursor/km-buttons-stream-90d4` branch.**

| File | MCU | Build |
|------|-----|-------|
| `MERGED_left.bin` | Left (USB1, console-facing) | Quiet build (`COM3_LOG=0`) + official legacy/V2 controller bridge |
| `MERGED_right.bin` | Right (USB3, controller host) | Includes the GIP init fix |

SHA-256:

```text
0cdae691cbe32b0565ad6d07d0591e290935b1634162cf1300901e71a22fc458  MERGED_left.bin
decbcaa73350becd6c16e36d997c57f7f4100de68f188f93ac040a2b96fc5c9f  MERGED_right.bin
```

After flashing, send `km.version()\r\n` at 4 Mbaud on the middle CH343
port. The Left firmware replies `km.MAKCU\r\n>>> `.

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
for the flash tool to pick up.

**`stock/` (not in the repo):** put saved vendor stock binaries here if you
want a rollback path — see the Rollback section of
[../../FLASHING.md](../../FLASHING.md). Vendor binaries are not distributed
with this repo.
