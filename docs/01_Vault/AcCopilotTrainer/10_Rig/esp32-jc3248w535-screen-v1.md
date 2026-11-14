---
type: state
status: active
created: 2026-04-21
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/10_Rig/_index.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-board-identification-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/screen-debugging-journey-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md
  - AcCopilotTrainer/01_Decisions/screen-firmware-toolchain.md
  - AcCopilotTrainer/01_Decisions/screen-firmware-in-trainer-monorepo.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - 00_Graph_Schema.md
---

# ESP32 rig touchscreen — Guition JC3248W535 v1

Rig-mounted 3.5" capacitive touchscreen that acts as a **WebSocket client of the AC Copilot Trainer sidecar**, exposing trainer settings and actions without the user reaching for the keyboard during hotlap practice.

## Hardware

| Item | Value |
|---|---|
| Board | Guition JC3248W535 (ESP32-S3-N16R8) |
| MCU | ESP32-S3 (ROM stamp `esp32s3-20210327`) |
| Flash | 16 MB |
| PSRAM | 8 MB octal |
| Display | 3.5" 480×320 IPS, **AXS15231B QSPI** controller (NOT RGB-parallel) |
| Touch | Capacitive single-point, **AXS15231B itself at I²C 0x3B** (SDA=4, SCL=8). No separate touch IC. |
| USB | Native ESP32-S3 (CDC + JTAG composite); USB-C port |
| Wireless | WiFi 2.4 GHz + BT 5 |
| Extras | Onboard speaker amp, LiPo connector, optional RGB LED |

## USB identity on the dev PC (2026-04-21)

- VID/PID `0x303A / 0x1001` (Espressif, ESP32-S3 native USB)
- MAC-style composite ID `3C:0F:02:CF:5A:20`
- Assigned **COM6** (CDC). JTAG on interface MI_02.
- No CH340 / CP210x bridge → zero driver install.

Identity confirmation procedure: see [`03_Investigations/jc3248w535-board-identification-2026-04-21.md`](../03_Investigations/jc3248w535-board-identification-2026-04-21.md).

## Current state — Phase 1 SHIPPED 2026-04-21

- **Firmware**: our Phase-1 firmware running. Factory `SW v0.9.1` backed up to `firmware/screen/_factory-backup/jc3248w535_v0.9.1_factory.bin` (16 MB, SHA recorded).
- **Boot evidence** captured on COM6 at 16:55 local after `esptool chip_id` hard-reset:
  - `[   191][I][esp32-hal-psram.c:96] psramInit(): PSRAM enabled`
  - `[boot] AC Copilot Screen ac-copilot-screen-01` (our Serial banner — setup() completed; display init didn't crash)
  - `[wifi] up  192.168.0.220` (joined `AHOME5G`)
  - `[ws] dial ws://192.168.4.26:8765/` → `[ws] connect returned false` (loop, no crash)
- **WS connect fails** only because the sidecar still binds `127.0.0.1`. PC↔ESP LAN ping works (PC on `192.168.4.26`, ESP on `192.168.0.220`, router bridges across the /22). Landing [`01_Decisions/external-ws-client-protocol-extension.md`](../01_Decisions/external-ws-client-protocol-extension.md) / gh [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81) unblocks the next phase.
- **Firmware size**: 923 KB flash (14.1% of 6.25 MB app partition), 46 KB RAM (14.1% of 320 KB) — plenty of headroom for LVGL return in Phase 2.
- **Mount**: not yet printed. 3D-printed bracket to follow the same pattern as the SRP brake bracket.
- **Network**: rig PC WiFi `AHOME5G`. Secret values live in gitignored `firmware/screen/secrets/wifi_secrets.h` (name **must not** be `wifi.h` — Windows case-insensitive FS collides with framework `<WiFi.h>`, see gotchas note).

## Integration contract

Speaks protocol v1 over WebSocket to `ws://<PC-LAN-IP>:8765` (the existing `tools/ai_sidecar`). Adds no new daemon. New message namespace defined in [`01_Decisions/external-ws-client-protocol-extension.md`](../01_Decisions/external-ws-client-protocol-extension.md).

## Firmware location (in this repo)

Monorepo: firmware lives under `firmware/screen/` inside `ac-copilot-trainer`. Rationale in [`01_Decisions/screen-firmware-in-trainer-monorepo.md`](../01_Decisions/screen-firmware-in-trainer-monorepo.md).

Toolchain choice lives in [`01_Decisions/screen-firmware-toolchain.md`](../01_Decisions/screen-firmware-toolchain.md). **Shipped toolchain differs from the original ADR** — LovyanGFX 1.2.20 has no `Panel_AXS15231B`, so Phase 1 uses `moononournation/GFX Library for Arduino @ 1.4.7` and LVGL is deferred to Phase 2. See ADR addendum + [`03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md`](../03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md) for the reasons and the Windows build-pipeline fixes.

## Safety / recovery

- Back up factory firmware before first flash:
  ```
  esptool.py --port COM6 --baud 921600 read_flash 0 0x1000000 jc3248w535_v0.9.1_factory.bin
  ```
- Hold **BOOT** during USB replug to force ROM DFU if a flash bricks the app.
- Opening COM6 via .NET `SerialPort` toggles DTR/RTS → board resets. Don't passively sniff serial while the user is using the LVGL demo on-screen.
- USB-C to USB-C cables are not all data-capable. Current working cable: the one previously used by the Oculus Rift (confirmed data-capable by CDC enumeration).

## Phase 1 scope — tracking

1. Back up factory firmware. ✅ (2026-04-21, file at `_factory-backup/jc3248w535_v0.9.1_factory.bin`)
2. Scaffold `firmware/screen/` in this repo. ✅
3. Firmware hello-world: boot → WiFi → WebSocket connect → render connection state. No real UI. ✅ (boot serial confirms all four stages run; status screen rendered on panel)
4. Sidecar diff: bind flag + `X-AC-Copilot-Token` header + protocol v1 message-type extension, feature-flagged off. ⏳ tracked in gh [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81)
5. Lua `ws_bridge.pollInbound` extension for `config.set` / `action` routing. ⏳ rolls into #81.

**Acceptance**: tapping a button on the ESP32 changes `approachMeters` in `AC_Copilot_Trainer`, HUD re-renders in session. (Pending #81; the firmware side already emits a demo `{v:1, type:"action", name:"toggleFocusPractice"}` every 10 s once the WS opens — can verify with no UI code as soon as the sidecar accepts LAN clients with the token header.)

## Resume checklist for next session

Picking this up with Claude Code — the firmware is good; the work is server-side. Concretely:

1. Implement gh #81 scope in `tools/ai_sidecar` (see ADR `external-ws-client-protocol-extension.md` for details): `--external-bind <host>`, `--token <value>`, `X-AC-Copilot-Token` upgrade check, and protocol additions (`hello`, `config.get/set`, `action`, `state.subscribe/snapshot`).
2. Extend `src/ac_copilot_trainer/modules/ws_bridge.lua` `pollInbound` routing to handle the new message types; fan `config.set` through the existing Settings-window code path; register an action dispatch table.
3. Generate a token via `py -3 -c "import secrets; print(secrets.token_urlsafe(24))"`, paste into gitignored `firmware/screen/secrets/sidecar.h` (`SIDECAR_TOKEN`), launch sidecar with `--external-bind 0.0.0.0 --token <x>`, press reset on the board (or re-upload firmware). Status screen should flip to `WS: Open` and the demo `toggleFocusPractice` should fire every 10 s.
4. Only **after** those green: start SquareLine-authored real UI (Phase 2).

## Phase 2+ scope (not yet started)

- SquareLine Studio-authored LVGL screens (settings tiles, quick-toggles, live telemetry readouts).
- Setup loader (file-stage + in-sim reload; pit-only due to AC physics lock).
- Third-party app control via HID-button actions (PocketTechnician, SetupExchange).
- OTA update path.

## Change log

- **2026-04-21 (early)** — Node created. Board identity confirmed, toolchain + monorepo + protocol extension decisions recorded.
- **2026-04-21 (late)** — Phase 1 firmware SHIPPED. Build succeeds (135 s), flash succeeds (29 s), board boots cleanly, joins `AHOME5G`, runs WS retry loop against sidecar URL. Toolchain pivoted from LovyanGFX+LVGL to `Arduino_GFX@1.4.7` (no LVGL) — see ADR addendum and windows-build-gotchas investigation. Next gate = sidecar external-bind (gh #81).
- **2026-04-21 (~21:00 PT)** — **End-to-end working.** PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) lands the sidecar `--external-bind`/`--token`, protocol v1 `{v,type}` extension, Lua `ws_bridge` action+config bridge, and the firmware fixes. Two key fixes that took most of today: (a) display now uses `Arduino_AXS15231B` + `Arduino_Canvas` + `ips=false` + `flush()` — the moononournation init table is for a 1.91" AMOLED variant, see [`03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md`](../03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md). (b) router AHOME5G mesh drops cross-AP TCP between PC (192.168.4.x) and device (192.168.0.x); workaround is Windows Mobile Hotspot `AG_PC 7933` so both peers share `192.168.137.x`, see [`03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md`](../03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md). Sidecar log: `INFO ws upgrade accepted client=ac-copilot-screen-01 peer=('192.168.137.25', 57810)`; device emits `{v:1,type:"action",name:"toggleFocusPractice"}` every 10 s. Touch is unverified; LVGL not yet bring-up'd.
- **Phase-2 stack chosen**: LVGL 8.3 + 40-line AXS15231B I²C touch reader + SquareLine export. See [`01_Decisions/screen-ui-stack-lvgl-touch.md`](../01_Decisions/screen-ui-stack-lvgl-touch.md).
- **2026-04-22** — **PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) MERGED** at head `caa8a9ad` after review-fix push (`1f24999`) covering sidecar auth hardening + protocol validation + Lua config bridge cleanup. Zero-sampling closure audit: 145 review threads, 0 unresolved non-outdated, 0 check-runs non-success, 0 agorokh-authored unresolved. PR #84 (vault post-merge handoff) merged 17:34.
- **2026-04-22** — Dead-end investigations captured in [`screen-debugging-journey-2026-04-21`](../03_Investigations/screen-debugging-journey-2026-04-21.md) so next session doesn't re-walk the 7-pin BL sweep / custom `JC3248W535_GFX.h` subclass / cycling-color diagnostic paths. EPIC context now in [`physical-rig-integration-epic-59`](physical-rig-integration-epic-59.md). Figma design source of truth in [`01_Decisions/dashboard-visual-design-figma`](../01_Decisions/dashboard-visual-design-figma.md).
- **Issue #81 housekeeping:** still OPEN on GitHub despite #83 merging. Needs `gh issue close 81` next session.
- **2026-04-25** — **Phase-2 Part A + Part B in flight on PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91)** (branch `feat/issue-86-rig-screen-phase2-launcher-and-apps`). Part A (commit `4557da5`) brought up LVGL 8.3 on top of the `Arduino_Canvas` + `flush()` model from PR #83 with 40-line AXS15231B touch driver, single-stack navigator (max depth 2), Figma design tokens, and TTF font staging (the `lv_font_conv` outputs are user-driven; default falls back to LVGL Montserrat 14). Part B (commit `8f88881`) ports `Menu.tsx` to LVGL — header + connection pill + three vertical app tiles (AC COPILOT, POCKET TECHNICIAN, SETUP EXCHANGE) each pushing a placeholder screen via `ui_nav_push`. The disconnect threshold (3 s grace before flipping the pill to DISCONNECTED) is enforced in `main.cpp` via `WS_DISCONNECT_GRACE_MS`. Same commit folds 8 bot-review fixes from PR #91 commit `4557da5`: touch coord underflow clamp (gemini P1), launcher pushed at boot not on first WS open (chatgpt-codex P1), `ESP.restart()` on PSRAM alloc fail (sourcery), `LV_TICK_CUSTOM=0` (Copilot), nav `pending_delete` removed (sourcery+cursor), `volatile` dropped from `app_state_t` (sourcery), `<esp_heap_caps.h>` include (Copilot), fonts `.gitignore` rewritten to actually ignore generated outputs. Original CI failure on commit `4557da5` was only `ci-conventional` — the PR title was renamed *after* CI captured the event payload. Parts C–F (AC Copilot mirror, Pocket Technician custom picker, Setup Exchange browser, polish) continue as follow-up commits on the same branch.
