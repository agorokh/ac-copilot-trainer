---
type: investigation
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/screen-firmware-toolchain.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# JC3248W535 board identification (2026-04-21)

## Summary

Arseny reported a newly arrived "ESP32 Development Board 3.5 Inch IPS Capacitive Touch Screen 480×320 IPS Display 8M PSRAM 16M Flash for Arduino LVGL WIFI BT" from DIYzone (AliExpress), labeled **JC3248W535 SW v0.9.1**. Before committing to a firmware toolchain we confirmed chip family, panel controller, and USB enumeration directly on the dev PC.

## Timeline

1. **Device enumeration.** `Get-PnpDevice | Where InstanceId -match 'VID_303A'` returned three entries sharing composite ID `3C:0F:02:CF:5A:20`: `USB Composite Device`, `USB Serial Device (COM6)` on interface MI_00, and `USB JTAG/serial debug unit` on interface MI_02. VID `0x303A` = Espressif, PID `0x1001` = ESP32-S3 native USB.

2. **Boot-banner capture.** Opened COM6 at 115200-8N1 with DTR/RTS off; port-open still toggled the lines and reset the board. Captured:

   ```
   [I] System start...
   ESP-ROM:esp32s3-20210327
   Build:Mar 27 2021
   rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)
   Saved PC:0x40381426
   SPIWP:0xee
   mode:DIO, clock div:1
   load:0x3fce3818,len:0x508
   ...
   entry 0x403c9880
   ```

   Factory firmware v0.9.1 is silent on serial after `entry` — it's running the LVGL demo, not a serial REPL.

3. **Cable change.** Device was first on USB-C-to-USB-A; replugged to USB-C-to-USB-C (the cable freed up from the Oculus Rift). Same COM6, same MAC, same enumeration — confirming data-capable USB-C cable.

## Root finding

- Chip: **ESP32-S3** (ROM stamp `esp32s3-20210327`), variant N16R8 (16 MB flash, 8 MB PSRAM) per marketing listing.
- Panel: **AXS15231B QSPI** controller per the JC3248W535 vendor datasheet (NOT confirmed by on-device read yet — driver choice below reflects vendor spec, not direct probe).
- Touch: CST820 / AXS5106 capacitive over I²C per vendor spec.
- USB: native ESP32-S3 (CDC + JTAG on composite). No external UART bridge. No CH340 / CP210x driver needed.

## Consequences

- Firmware toolchain decided in [`01_Decisions/screen-firmware-toolchain.md`](../01_Decisions/screen-firmware-toolchain.md): PlatformIO + LovyanGFX (for the AXS15231B driver) + LVGL v9.
- Repository layout decided in [`01_Decisions/screen-firmware-in-trainer-monorepo.md`](../01_Decisions/screen-firmware-in-trainer-monorepo.md): `firmware/screen/` in this repo.

## Follow-ups

- Read actual panel controller ID over QSPI in the first-flash bring-up to confirm the AXS15231B assumption. If the shipped panel differs (some JC3248W535 batches vary), the LovyanGFX board config needs adjusting before any rendering work.
- Verify touch controller ID over I²C at first bring-up.
