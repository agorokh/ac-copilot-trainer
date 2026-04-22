# AC Copilot Rig Screen — firmware

ESP32-S3 touchscreen companion for the sim rig. Lives under this repo so the
Lua app, Python sidecar, and firmware all move together.

Hardware: Guition JC3248W535 (ESP32-S3-N16R8, 3.5" 480×320 AXS15231B QSPI,
CST820/AXS5106 touch). Full identity + cable notes:
[docs/01_Vault/AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md](../../docs/01_Vault/AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md).

## Phase-1 acceptance

1. Board boots, backlight on, LVGL status screen renders.
2. Joins WiFi (SSID from `secrets/wifi.h`).
3. Dials the sidecar WS at `ws://SIDECAR_HOST:SIDECAR_PORT/` with an
   `X-AC-Copilot-Token` header.
4. Status labels live-update (WiFi state, WS state, last error).
5. Demo button sends `{"v":1,"type":"action","name":"toggleFocusPractice"}`
   so we can prove the full round-trip once the Lua + sidecar side lands
   ([ADR external-ws-client-protocol-extension](../../docs/01_Vault/AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md)).

Nothing beyond this is in scope yet. Real UI screens are Phase 2.

## Prereqs (one-time)

```powershell
# PlatformIO Core (standalone, not the VS Code extension)
py -3 -m pip install --user platformio
# esptool (needed for factory firmware backup; PlatformIO ships its own too)
py -3 -m pip install --user esptool
```

Confirm `pio` and `esptool.py` resolve on PATH; you may need to add
`%APPDATA%\Python\Python313\Scripts` to the user PATH.

## Build, flash, monitor

```powershell
cd C:\Users\arsen\Projects\ac-copilot-trainer\firmware\screen

# Copy secrets templates once, then fill in.
Copy-Item secrets\wifi.h.example    secrets\wifi.h
Copy-Item secrets\sidecar.h.example secrets\sidecar.h
# edit secrets\wifi.h    -> real SSID + password
# edit secrets\sidecar.h -> LAN IP of the PC + token

# Build + flash + monitor
pio run -e jc3248w535
pio run -e jc3248w535 -t upload
pio device monitor -e jc3248w535
```

## Before you flash: back up the factory firmware

This board ships with a factory LVGL demo labelled `SW v0.9.1`. Back it up so
we can restore if we ever brick a flash. Do this ONCE:

```powershell
# From firmware/screen/ so the bin lands under _factory-backup/
py -3 -m esptool --port COM6 --baud 921600 `
    read_flash 0 0x1000000 _factory-backup\jc3248w535_v0.9.1_factory.bin

# Integrity hash (commit nothing but this hash file is optional too).
(Get-FileHash _factory-backup\jc3248w535_v0.9.1_factory.bin -Algorithm SHA256).Hash `
    | Out-File _factory-backup\jc3248w535_v0.9.1_factory.sha256
```

If a flash ever bricks: hold the BOOT button on the board while plugging USB
to force ROM DFU, then `esptool.py ... write_flash 0 <factory.bin>`.

## Troubleshooting

- **Port open resets the board.** Native-USB CDC on the S3 toggles DTR/RTS on
  `open`. Don't monitor the port from two processes at once.
- **Backlight never turns on / black screen.** Suspect the pins in
  `include/board/LGFX_JC3248W535.h` first — they are community defaults and
  have not yet been verified on this physical board.
- **WS never opens, status says "Sidecar: closed".** Today that's expected —
  the sidecar still binds loopback and doesn't accept tokens. Lua + sidecar
  work is tracked under the `external-ws-client-protocol-extension` ADR.

## Layout

```
firmware/screen/
├── platformio.ini             PIO config (board, flags, deps)
├── default_16MB.csv           custom partition table
├── include/
│   ├── lv_conf.h              LVGL v9 minimal config
│   └── board/
│       └── LGFX_JC3248W535.h  LovyanGFX board config (pin map TBD-verified)
├── src/
│   └── main.cpp               Phase-1 firmware
├── secrets/                   gitignored — real credentials live here
│   ├── wifi.h.example
│   └── sidecar.h.example
└── _factory-backup/           gitignored binaries; keep the .sha256 locally
```
