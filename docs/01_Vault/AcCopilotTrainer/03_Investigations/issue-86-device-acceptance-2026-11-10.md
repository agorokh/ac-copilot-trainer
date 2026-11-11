---
type: investigation
status: complete
memory_tier: canonical
created: 2026-11-11
updated: 2026-11-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-device-capture-2026-10-19.md
  - AcCopilotTrainer/03_Investigations/issue-86-pt-long-names-2026-10-18.md
  - AcCopilotTrainer/00_System/Roadmap.md
---

# #86 Physical `COM6` Pit Acceptance & Closure Receipt (2026-11-11)

Agent-executed physical device acceptance for [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) on Windows rig `pc` (Console Session 1) + ESP32-S3 JC3248W535 (`COM6`, USB CDC serial `115200`), driving Assetto Corsa (`ks_porsche_911_gt3_r_2016` @ `spa`, Practice `StartType="PIT"`, `ac.isCarResetAllowed() == true`) without human intervention.

## 1. Defects surfaced & fixed during autonomous rig acceptance

1. **Loopback touch actuation + LuaJIT `cdata` `isCallable` ([PR #949](https://github.com/agorokh/ac-copilot-trainer/pull/949), merged `185414d`):**
   - Added authenticated `screen.touch` / `screen.touch.ack` (`tap` and `drag`) across `firmware/screen/`, `tools/ai_sidecar/server.py`, and `tools/screen_capture.py` (`--touch` / `--drag`) so autonomous desktop pit sessions actuate LVGL buttons and scrollable lists directly on physical `COM6`.
   - Fixed `isCallable()` in `src/ac_copilot_trainer/modules/setup_library.lua` to treat LuaJIT FFI `cdata` functions (`ac.isCarResetAllowed`, `ac.loadCarSetup`) as callable instead of returning `false` on `type(fn) == "cdata"`.
2. **UTF-8 glyph folding, single-line spinner values & bounded serial payloads ([PR #951](https://github.com/agorokh/ac-copilot-trainer/pull/951), merged `3c746a3`):**
   - Added UTF-8 -> printable ASCII display folding (`firmware/screen/include/ui/ascii_fold.h`, `firmware/screen/src/ui/ascii_fold.cpp`, `tools/ai_sidecar/csp_setup_exchange.py`) so community setup titles containing curly quotes/dashes/accents (e.g. `"PORSCHE GT3 ’16 Hotlap V1"` -> `"PORSCHE GT3 '16 Hotlap V1"`) render crisply on subset LVGL fonts with zero missing-glyph tofu (`▯`), while keeping wire/filesystem setup identifiers lossless.
   - Added auto-fitting single-line spinner value labels (`set_spinner_value_label` + `g_spinner_value_labels`) in `screen_pocket_technician.cpp`, per-corner CSP damper disambiguation (`Bump LF`/`RF`/`LR`/`RR`) in `setup_library.lua`, and `assert_no_missing_glyphs` across `511` native simulator assertions.
   - Bounded screen/serial `setup.spinner.list.result` to `SCREEN_PEER_MAX_SPINNERS = 12` (`<= 2600` B) and `setup.list.result` to `<= 4800` B (preserving active setup), and raised `SERIAL_RX_RING_BYTES` / `SERIAL_MAX_LINE_BYTES` to `16384` in `firmware/screen/src/main.cpp` with overflow keepalive refresh so Pocket Technician's dual-list burst never overflows USB serial RX.

## 2. Deployed artifact provenance on `pc` + `COM6`

- **`pc` checkout (`C:\Users\arsen\Projects\ac-copilot-trainer`):** `main` at `3c746a3` (`PR #949` `185414d` + `PR #951` `3c746a3`), clean working tree; `AC_Copilot_Trainer` Lua junction verified live.
- **ESP32 `COM6` firmware (`jc3248w535_serial`):** built & flashed via `pio run -d firmware/screen -e jc3248w535_serial -t upload --upload-port COM6` (native LVGL simulator gate ran automatically); `esptool.py v4.11.0` verified flash hashes (`firmware.bin` SHA-256 prefix `750e106d21da7176...fddf`).
- **Packaged Game Point launcher (`dist\AC-Copilot-Game-Point.exe`):** rebuilt via `python -m tools.rig_launcher --build-exe --install-shortcut` (`SHA-256` prefix `b23455e830f53db2...9bec`); `dist\AC-Copilot-Game-Point.exe --self-test` exited `0`; Console Session 1 `/health` reported `{"status":"ok","connected_peers":2,"screen_peers":1,"build_commit":"3c746a3","build_time":"2026-11-11T02:21:39Z"}`.
- **Live Spa Practice pit session:** `acs.exe` PID `4432` (`ks_porsche_911_gt3_r_2016` @ `spa`, `StartType="PIT"`), `session.start.ack` `{"ok":true,"started":true}`, advancing shared-memory packets (`gfx=1205->2225`, `phys=2114->4116`), `is_live=true`, `is_in_pit=true`, `reset_allowed=true`, `spinner_source="csp"`.

## 3. Four-leg physical `COM6` framebuffer captures & wire receipts

All PNGs below were captured directly from the `COM6` ESP32 LVGL framebuffer (`320x480` RGB565) under `assets/issue-86-pit-capture-2026-11-10/`:

| Leg | Capture artifact | Observed on-glass & in-sim result |
| --- | --- | --- |
| **Leg 1 — Launcher** | `01-launcher-connected.png` | `AC LAUNCHER` header with `CONNECTED` status pill and all 3 tiles (`AC COPILOT`, `POCKET TECHNICIAN`, `SETUP EXCHANGE`), crisp Racing Atelier typography, zero missing glyphs. |
| **Leg 2 — AC Copilot live** | `02-ac-copilot-live.png` | Tapping `AC COPILOT` (`160, 116`) opens live Spa session mirror (`APPROACHING`, green `LIVE`, `HOLD`, `NEXT BRAKE PT 15 m`, `NOW NEXT T1 BRAKE 209`, `BRAKE ZONE -209`, `COACH NEXT: T1`); `< BACK` (`269, 458`) returns cleanly to Launcher. All 5 render differences vs `esp32_rig.png` ([comment 6260669420](https://github.com/agorokh/ac-copilot-trainer/issues/86#issuecomment-6260669420)) were accepted as-shipped on 2026-11-10. |
| **Leg 3a/3b — Pocket Technician live spinners in pits** | `03a-pocket-technician-spinners-in-pits.png`, `03b-pocket-technician-spinner-adjusted.png` | Opens with `TRACK: Spa`, `PORSCHE`, `911 GT3 R 2016`, `LIVE CAR: BB 68.0% TC 3 ABS 8`, `Setup controls: pits/reset allowed`, and bounded 12-row `SETUP VALUES` (`Brake Bias 68%`, `ABS 8`, `Traction Control 3`, `Front splitter 1`, `Rear wing 20`). Tapping `-` on `Brake Bias` (`171, 230`) confirmed `setup.spinner.set.ack` (`FRONT_BIAS = 67`, `confirmed: true`, `11 ms` RTT) and updated both spinner (`67%`) and `LIVE CAR: BB 67.0% TC 3 ABS 8`. |
| **Leg 3c — Pocket Technician saved setup load in pits** | `04-pocket-technician-setup-loaded.png` | Scrolling to `SAVED` and tapping `Realistic_BB_v2` (`160, 275`) confirmed `setup.load.ack` (`ok: true`, `7 ms` RTT), setting `ACTIVE: Realistic_BB_v2`, `LIVE CAR: BB 66.0% TC 3 ABS 7`, and updating `SETUP VALUES` (`Brake Bias 66%`, `ABS 7`, `Rear wing 18`). |
| **Leg 4a/4b — Setup Exchange community browse & install** | `05-setup-exchange-results.png`, `06-setup-exchange-installed.png` | Live `se.acstuff.club` results for `Porsche 911 GT3 R 2016` / `Spa`: `26liters` (`9696 DL`), `SPA GT3 R RACE 6 LAPS` (`7814 DL`), and `PORSCHE GT3 '16 Hotlap V1` (`2445 DL`) rendered with crisp ASCII `'` and **zero tofu (`▯`)**. Tapping `26liters` (`160, 154`) installed `26liters.ini` (`Installed: 26liters.ini`, green card border). |
| **Leg 4c/4d/4e — Installed community setup in Pocket Technician -> load -> Launcher** | `07a-pt-community-in-saved-list.png`, `07b-pocket-technician-community-loaded.png`, `08-launcher-complete.png` | Opening Pocket Technician and scrolling to `SAVED` showed `26liters` (`BB:68 ABS:8 TC:3 W:1/20`) directly below per-corner disambiguated `Bump RF` / `Bump RR` spinners; tapping `26liters` (`160, 350`) confirmed explicit `setup.load.ack` (`ok: true`, `3 ms` RTT), `ACTIVE: 26liters`, `LIVE CAR: BB 68.0% TC 3 ABS 8`, `Front splitter 1`, `Rear wing 20`; `< BACK` (`260, 26`) returned cleanly to Launcher (`08-launcher-complete.png`). |

## 4. Post-run cleanup

`acs.exe` exited cleanly via `WM_CLOSE` (`RigSessionLock` released), the test-downloaded `26liters.ini` was removed while preserving all 7 pre-existing operator Spa `.ini` setups intact, and temporary scratch scripts on `pc` were deleted.
