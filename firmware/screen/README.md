# AC Copilot Rig Screen — firmware

ESP32-S3 touchscreen companion for the sim rig. Lives under this repo so the
Lua app, Python sidecar, and firmware all move together.

Hardware: Guition JC3248W535 (ESP32-S3-N16R8, 3.5" 480×320 AXS15231B QSPI,
CST820/AXS5106 touch). Full identity + cable notes:
[docs/01_Vault/AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md](../../docs/01_Vault/AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md).

## Phase-1 acceptance

1. Board boots, backlight on, Arduino_GFX status screen renders.
2. Joins WiFi (SSID from `secrets/wifi_secrets.h`).
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
cd firmware\screen

# Copy secrets templates once, then fill in.
Copy-Item secrets\wifi_secrets.h.example secrets\wifi_secrets.h
Copy-Item secrets\sidecar.h.example secrets\sidecar.h
# edit secrets\wifi_secrets.h -> real SSID + password
# edit secrets\sidecar.h -> LAN IP of the PC + token

# Build + flash + monitor (USB-serial transport — the rig default)
pio run                          # default env = jc3248w535_serial
pio run -t upload
# NOTE: don't `pio device monitor` in serial mode — the sidecar owns the port
# (it IS the protocol link). Monitoring would fight it for COM6.

# WebSocket/hotspot variant (LAN deployments, CI build coverage):
pio run -e jc3248w535 -t upload
```

## Transport: USB serial (default) vs WebSocket (issue #463)

The rig runs the **USB-serial transport**: the screen speaks protocol v1 as
newline-delimited JSON over the native USB CDC (the same COM port used to flash),
so it needs **no WiFi and no Windows Mobile Hotspot**. This removes the failure
mode where hosting a 2.4 GHz SoftAP on the rig PC's single-radio adapter drops the
main WiFi. Selected by the `SCREEN_TRANSPORT_SERIAL=1` build flag in env
`jc3248w535_serial` (the default). The screen `secrets/wifi_secrets.h` values are
unused in this mode (only `CLIENT_ID` from `secrets/sidecar.h` is needed).

Run the sidecar pointed at the screen's COM port:

```powershell
py -3 -m tools.ai_sidecar --serial-port COM6      # or set AC_COPILOT_SIDECAR_SERIAL_PORT
```

The launcher auto-forwards `--serial-port` when `AC_COPILOT_SIDECAR_SERIAL_PORT`
is set in the user environment. The legacy WebSocket build (`jc3248w535`) is kept
for LAN deployments and CI; it still dials `ws://SIDECAR_HOST:SIDECAR_PORT/`.

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

- **Port open resets the board / screen never receives.** Native-USB CDC on the
  S3 resets on an **RTS** pulse (esptool's reset line), and only delivers RX to
  the firmware once **DTR** is asserted. The sidecar's serial transport opens with
  **DTR high, RTS low** — RX works and the board does not reset. A plain
  `pio device monitor` may toggle both and reset the board; don't run it while the
  sidecar owns the port.
- **Backlight never turns on / black screen.** Suspect the pins in
  `include/board/LGFX_JC3248W535.h` first — they are community defaults and
  have not yet been verified on this physical board.
- **WS never opens, status says "Sidecar: closed".** Verify the sidecar is started
  with an external bind and `AC_COPILOT_SIDECAR_TOKEN` matching
  `secrets/sidecar.h`:
  `py -3 -m tools.ai_sidecar --external-bind 0.0.0.0 --port 8765`.
  The sidecar now accepts authenticated external clients and keeps loopback Lua
  traffic working for in-game coaching.

### Auto-start with the in-game trainer

`src/ac_copilot_trainer/start_sidecar.bat` stays loopback-only unless a rig-screen
token is configured. To let the AC app auto-spawn the sidecar for the physical
screen, set the token in the user environment to the same value compiled into
`secrets/sidecar.h`:

```powershell
[Environment]::SetEnvironmentVariable("AC_COPILOT_SIDECAR_TOKEN", "<TOKEN>", "User")
```

Optional overrides:

```powershell
[Environment]::SetEnvironmentVariable("AC_COPILOT_SIDECAR_EXTERNAL_BIND", "0.0.0.0", "User")
[Environment]::SetEnvironmentVariable("AC_COPILOT_SIDECAR_PORT", "8765", "User")
```

Restart Content Manager / Assetto Corsa after changing user environment variables.

For the **USB-serial** rig firmware (the default) there is no hotspot and no
`SIDECAR_HOST` to match — set `AC_COPILOT_SIDECAR_SERIAL_PORT` (e.g. `COM6`) so
the launcher forwards `--serial-port` to the sidecar. `SIDECAR_HOST` / the
2.4 GHz hotspot only apply to the legacy WebSocket build (`jc3248w535`).

### Token rotation

Rotate the sidecar token whenever it may have been exposed, after a rig rebuild,
or before sharing logs/screenshots externally:

1. Generate a new random token locally and keep it out of chat, issue comments,
   screenshots, command lines, and committed files.
2. Update `firmware/screen/secrets/sidecar.h` with the new token.
3. Update the rig PC user environment:

   ```powershell
   [Environment]::SetEnvironmentVariable("AC_COPILOT_SIDECAR_TOKEN", "<NEW_TOKEN>", "User")
   ```

4. Rebuild and flash the screen firmware if the flashed firmware still contains
   the old token.
5. Restart Content Manager / Assetto Corsa and any already-running sidecar
   process so the new user environment is inherited.
6. Verify the screen reconnects and `/health` reports a current screen peer.

If rotation was caused by suspected exposure, do not reuse the old token in any
local config or firmware build.

## Polish (#677) — NVS, backpressure probe, debug screen

- **Last screen + SE sort** persist in NVS (`Preferences` namespace `acscreen`) on
  every change, not on shutdown. Power-cycle restores the last app screen and
  Setup Exchange sort (`SORT: DL` / `SORT: NAME`).
- **Debug screen:** long-press the launcher brand `AC LAUNCHER`. Shows link
  state, last-frame age, peer count, free heap, and backpressure counters.
- **Serial backpressure proof** (host owns the CDC — stop the sidecar first):

  ```powershell
  py -3 -m tools.ai_sidecar.serial_backpressure_probe --port COM6 --count 40
  ```

  Expect `PASS drop=0` (hard gate). `max_drain_ms` may be tens of ms when the
  8 KiB RX ring is saturated — that is absorption working, not a drop.
  Firmware emits `[serial][bp] ok=… drop=… max_drain_ms=…` after a ≥8-frame
  drain burst.

## Layout

```text
firmware/screen/
├── platformio.ini             PIO config (board, flags, deps)
├── default_16MB.csv           custom partition table
├── include/
│   ├── lv_conf.h              LVGL v9 minimal config
│   └── board/
│       └── JC3248W535_GFX.h   Arduino_GFX board config (pin map TBD-verified)
├── src/
│   └── main.cpp               Phase-1 firmware
├── secrets/                   gitignored — real credentials live here
│   ├── wifi_secrets.h.example
│   └── sidecar.h.example
└── _factory-backup/           gitignored binaries; keep the .sha256 locally
```
