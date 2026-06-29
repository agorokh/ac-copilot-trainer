# Claude Design UI package

Last updated: 2026-06-29

This package is the source brief to hand to Claude Design, Figma work, or a UI
specialist before changing the rig cockpit screens or the Game Point launcher.
It explains the current screens, what technology actually renders them, what is
already implemented, and what future scope needs design room.

Use this whole file as the design prompt. The intended output is a buildable UI
spec, not a marketing page.

## Copy-paste prompt for Claude Design

You are designing the AC Copilot Trainer driver-facing UI. Produce a practical
UI design package for implementation in the existing repo, using the constraints
below.

Design the following surfaces as one coherent cockpit system:

1. ESP32 rig touchscreen, portrait 320x480, implemented in LVGL 8.3 C++.
2. Windows Game Point launcher, implemented today in Python stdlib Tkinter and
   packaged as `dist/AC-Copilot-Game-Point.exe`.
3. Assetto Corsa in-game CSP Lua app, implemented with CSP `ui.*` Dear ImGui and
   `render.*` track markers.

The design must be operational and glanceable at the wheel. Do not create a
landing page. Do not propose a browser app for the ESP32 screen. Do not require
React, CSS, HTML, SVG filters, blur, image-heavy layouts, or cloud services for
the rig screen. For every proposed screen, include dimensions, state variants,
copy, component hierarchy, touch targets, and implementation notes for LVGL or
Tkinter.

Primary user: the driver sitting in a sim rig, possibly wearing gloves, in a
vibrating seat, with minimal tolerance for reading or fiddling mid-lap.

Tone: serious racing cockpit, not toy/game-menu. High contrast, black/charcoal
surfaces, gold accent, red warning, green success. Color indicates state, not
decoration; pair color with labels/icons where possible.

Deliver:

- Screen inventory and navigation map.
- Visual system tokens: colors, spacing, typography, status colors.
- ESP32 320x480 wireframes for Launcher, AC Copilot, Pocket Technician, Setup
  Exchange, Settings/Diagnostics, and one future haptics/voice status screen.
- Windows Game Point launcher layout with status rows, buttons, settings model,
  and room for future rig functions.
- In-game HUD alignment notes so the CSP app, rig screen, and desktop launcher
  feel like one product.
- State designs for booting, disconnected, connected, stale data, busy, success,
  warning, and error.
- Implementation notes: what maps directly to LVGL widgets, what must remain
  simple because of the ESP32, what belongs in Tkinter, and what belongs in the
  CSP Lua app.

## Product model

AC Copilot Trainer has three visible UI surfaces and one state hub:

```text
Assetto Corsa + CSP Lua app
  -> Python WebSocket sidecar
      -> ESP32 rig touchscreen
      -> Windows Game Point launcher
      -> voice coach / haptics / SimHub checks
```

The driver should experience this as one "Game Point" cockpit system:

- Start and monitor the rig stack from the Desktop launcher.
- Drive with the in-game HUD and voice coach.
- Use the physical touchscreen for quick controls, setup changes, and status.
- Add future rig functions to the launcher and touchscreen instead of creating
  one-off desktop scripts.

## Current technologies

### ESP32 rig touchscreen

- Hardware: Guition JC3248W535, ESP32-S3-N16R8, 16 MB flash, 8 MB PSRAM.
- Display: 3.5 inch IPS, AXS15231B QSPI panel.
- Physical orientation: portrait, iPhone-style on the rig.
- Logical UI size: 320x480. The source code treats LVGL, panel canvas, and
  framebuffer as native portrait.
- Firmware path: `firmware/screen/`.
- Toolchain: PlatformIO, Arduino framework, Arduino_GFX 1.4.7, ArduinoJson,
  ArduinoWebsockets, LVGL 8.3.x.
- Touch: AXS15231B I2C touch path at address 0x3B.
- UI code: hand-authored LVGL C++ screens in `firmware/screen/src/ui/`.
- Navigation: single stack, max depth 2. Launcher sits at depth 0; app screens
  push on top and use a visible back affordance.
- Rendering constraints: no CSS, no browser, no webview, no heavy images, no
  blur/shadow effects. LVGL style tokens are color plus opacity.
- Font constraint: default firmware font is limited; avoid non-ASCII glyphs in
  UI copy until bundled fonts are generated with `lv_font_conv`.

### Windows Game Point launcher

- Entrypoint: `python -m tools.rig_launcher`.
- Packaged executable: `dist/AC-Copilot-Game-Point.exe`.
- Desktop shortcut: `AC Copilot Game Point.lnk`.
- UI implementation today: Python stdlib Tkinter in `tools/rig_launcher/app.py`.
- Supervisor logic: `tools/rig_launcher/supervisor.py`.
- Packaging: PyInstaller onefile/windowed via `python -m tools.rig_launcher
  --build-exe`.
- Install shortcut: `python -m tools.rig_launcher --install-shortcut`.
- Local per-user data: `%LOCALAPPDATA%\AC Copilot Trainer\GamePoint\`.
- Non-secret settings: `settings.json`, opened by the launcher Settings button.
- Secrets: environment variables only, especially `AC_COPILOT_SIDECAR_TOKEN`.

The launcher is intentionally utilitarian. It is not a consumer website; it is a
small operational panel for starting, checking, and tuning rig functions.

### Assetto Corsa in-game CSP app

- Runtime: Assetto Corsa with Custom Shaders Patch v0.2.11+.
- Language: Lua 5.1 / LuaJIT through CSP Lua apps.
- UI framework: CSP `ui.*` Dear ImGui.
- Rendering: CSP `render.*` track-surface markers and in-game overlay windows.
- Data: AC shared memory/CSP telemetry, lap archive JSON, sidecar messages.
- App path: `src/ac_copilot_trainer/`, installed to
  `assettocorsa/apps/lua/ac_copilot_trainer/`.
- It publishes live state to the sidecar and receives coaching responses.

### Python sidecar

- Entrypoint: `python -m tools.ai_sidecar`.
- Role: local state hub and protocol router. It is not the primary UI.
- Protocol: WebSocket JSON v1 plus `/health` and `/metrics`.
- Important current topics and message types:
  - `state.snapshot` with `topic="coaching.snapshot"` at 10 Hz.
  - `corner_advice` legacy event for richer corner hints.
  - `setup.list` / `setup.list.result`.
  - `setup.load` / `setup.load.ack`.
  - `setup.spinner.list` / `setup.spinner.list.result`.
  - `setup.spinner.set` / `setup.spinner.set.ack`.
  - `telemetry_tick`, `coaching.cue`, and `haptic_event` for future surfaces.

## Current screen inventory

### ESP32 Launcher

Files:

- `firmware/screen/src/ui/screen_launcher.cpp`
- `firmware/screen/include/ui/screen_launcher.h`

Current layout:

- Header, 56 px high.
- Brand label: `AC LAUNCHER`.
- Right status pill: dot plus `CONNECTING`, `CONNECTED`, or `DISCONNECTED`.
- Spinner visible when not connected.
- Three vertical tiles:
  - `AC COPILOT` - real-time coaching overlay.
  - `POCKET TECHNICIAN` - saved setups manager.
  - `SETUP EXCHANGE` - community setups browser.

Current behavior:

- Launcher is pushed immediately at boot so the device never sits on a blank
  LVGL screen while WiFi or sidecar connection is still starting.
- Tiles remain tappable even while disconnected; child screens gate their own
  dependent behavior.
- Setup Exchange is still a placeholder screen.

Design opportunities:

- Make connection state legible from two feet away.
- Add a small always-visible route back to "how to recover": sidecar stopped,
  hotspot off, token mismatch, screen waiting.
- Leave room for future launcher tiles without making the first screen dense.

### ESP32 AC Copilot mirror

Files:

- `firmware/screen/src/ui/screen_ac_copilot.cpp`
- `src/ac_copilot_trainer/modules/coaching_publisher.lua`

Current layout:

- Header: `AC COPILOT` plus `< BACK`.
- Alert card:
  - corner label
  - primary coaching line
  - secondary coaching line or corner advice override
- Telemetry panel:
  - approaching corner
  - distance to braking
  - progress bar
  - target speed
  - current speed
  - delta chip such as `TOO FAST +14 KM/H` or `ON PACE`

Current behavior:

- Lua publishes `coaching.snapshot` at 10 Hz.
- The firmware applies snapshots asynchronously through LVGL idle callbacks.
- Empty state is currently text-first: drive a lap with the trainer running.
- Current speed turns red when it is meaningfully above target.

Design opportunities:

- Improve the empty/no-reference state without adding a paragraph.
- Establish a compact hierarchy for "do this now" versus background telemetry.
- Create stale-data handling: last snapshot age, paused/not driving, no sidecar.

### ESP32 Pocket Technician

Files:

- `firmware/screen/src/ui/screen_pocket_technician.cpp`
- `src/ac_copilot_trainer/ac_copilot_trainer.lua`
- `src/ac_copilot_trainer/modules/setup_library.lua`

Current layout:

- Header: `POCKET TECHNICIAN` plus `< BACK`.
- Meta block:
  - track
  - car brand
  - car model
  - active setup
- Scrollable list column:
  - `ADJUST` section with spinner rows when active setup controls are present.
  - `SAVED` section with setup rows.

Current behavior:

- On screen open, firmware queues `setup.list` and `setup.spinner.list`.
- Setup rows show name, best lap, and compact chips: brake bias, ABS, TC, wings.
- Tapping a setup row queues `setup.load`; success pulses the row border, failure
  shows a red toast.
- Spinner rows provide `-` and `+` buttons and round trip through
  `setup.spinner.set`.
- If the sidecar is offline, setup controls show an error toast instead of
  sending edits.

Design opportunities:

- Make the top three or four controls feel like intentional cockpit controls,
  not generic table rows.
- Clarify busy states and ack latency.
- Keep saved setups readable even with long car/setup names.
- Consider separating "quick adjust" and "saved setup" into tabs only if it can
  stay one tap away.

### ESP32 Setup Exchange

Files:

- Placeholder factory in `firmware/screen/src/ui/screen_launcher.cpp`.
- Integration decision: `docs/01_Vault/AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md`.

Current state:

- Placeholder screen only.

Expected future behavior:

- Browse setups that Setup Exchange drops into `UserSetups/<carID>/`.
- Do not replace the official x4fab Setup Exchange app.
- The trainer/sidecar should coexist with Setup Exchange and use local setup
  files as the source of truth.
- Future option: sidecar proxy for remote community data, but only after the
  local file/browser workflow is stable.

Design opportunities:

- Treat this as a small local setup browser on 320x480, not a full marketplace.
- Prioritize freshness, track fit, source, and confidence over rich metadata.
- Provide clear unavailable states when Setup Exchange is not installed or no
  matching setups exist.

### Windows Game Point launcher

Files:

- `tools/rig_launcher/app.py`
- `tools/rig_launcher/supervisor.py`
- `tools/rig_launcher/settings.py`
- `docs/10_Development/14_Game_Point_Launcher.md`

Current layout:

- Window title: `AC Copilot Game Point`.
- Default geometry: 620x360; minimum 560x320.
- Header label.
- Multi-line status text.
- Buttons:
  - Start
  - Refresh
  - Logs
  - Settings
- Status path label.

Current status model:

- sidecar: stopped, starting, running, healthy, unreachable, blocked, exited.
- screen: connected, waiting, unknown.
- hotspot: on/off/probe failure.
- voice: skipped, observer-only, configured, TTS, missing reference.
- SimHub: absent, available, running, started.
- checks:
  - sidecar token required when exposing non-loopback bind.
  - voice reference required when voice playback is requested.

Design opportunities:

- Convert raw lines into status rows with icons, state color, detail, and action.
- Add a proper Settings surface for non-secret fields.
- Keep Desktop launcher compact and work-focused. It should open to status and
  controls, not a hero/marketing screen.
- Provide a visible path for "what do I click now?" when sidecar/screen/hotspot
  are not ready.

### In-game CSP Lua app

Files:

- `src/ac_copilot_trainer/ac_copilot_trainer.lua`
- `src/ac_copilot_trainer/modules/hud_settings.lua`
- `src/ac_copilot_trainer/modules/coaching_publisher.lua`

Current visible functions:

- Real-time brake-zone coaching HUD.
- Speed reference and braking distance guidance.
- Per-corner coaching lines after laps.
- 3D brake point and track markers through CSP rendering.
- Settings and diagnostics through Dear ImGui.
- Sidecar connection/status in settings.
- Setup library integration and lap archive records.
- Voice coach and sidecar-backed advisory plumbing.

Design opportunities:

- Align copy, colors, and status naming with the ESP32 and launcher.
- Keep in-game HUD extremely low-reading-load; the rig screen can carry more
  secondary data when the car is not in a critical driving moment.
- Make "voice is armed", "reference lap loaded", and "sidecar connected" states
  consistent across all surfaces.

## Existing visual tokens

Firmware tokens live in `firmware/screen/include/ui/tokens.h`.

Current semantic palette:

| Token | Meaning | Current value |
|---|---|---|
| `UI_BG_BASE` | base background | `#000000` |
| `UI_BG_PANEL` | panel surface | `#1E1E1E` at 92 percent opacity |
| `UI_BG_HEADER` | header surface | `#141414` at 95 percent opacity |
| `UI_TX_PRIMARY` | primary text | `#FFFFFF` |
| `UI_TX_MUTED` | muted text | `#A3A3A3` |
| `UI_TX_QUIET` | quiet text | `#737373` |
| `UI_ACCENT_GOLD` | primary action/accent | `#FFD700` |
| `UI_LINE_AMBER` | warning/line hint amber | `#FFC43D` |
| `UI_ALERT_RED` | alert/error | `#EF4444` |
| `UI_OK_GREEN` | success/on pace | `#22C55E` |
| `UI_RADIUS_TILE` | tile radius | `8 px` |
| `UI_TAP_MIN_PX` | minimum touch target | `60 px` |
| `UI_GAP_TILES` | tile gap | `12 px` |

Figma/brand typography intent:

- Numeric emphasis: Michroma.
- Body: Montserrat Regular/Bold.
- Branding accents: Syncopate Bold.

Implementation note: these fonts are not fully shipped to firmware yet. Designs
may specify them, but must also provide fallback sizing that works with LVGL's
current built-in font until Part A4 font conversion lands.

## Design rules for the next pass

- ESP32 screen is 320x480 portrait. Do not design 480x320 landscape screens.
- Touch targets must be at least 60 px high or wide for primary actions.
- Every important screen must have an explicit connected/disconnected/stale
  state.
- Avoid long text in motion. For driving-critical states, prefer one action line
  and one number.
- Keep status always available: sidecar, screen, telemetry age, and active mode.
- Use color as state, not decoration.
- Avoid non-ASCII symbols in firmware copy until the font bundle is confirmed.
  Use `-`, `< BACK`, `+`, and simple words instead of typographic symbols.
- Use LVGL-native widgets: labels, buttons, bars, spinners, flex/grid containers,
  scrollable columns, toasts, and simple status pills.
- Avoid nested cards. Use full-screen bands/panels and single-level tiles/rows.
- No in-app explanatory tutorials. If recovery instructions are needed, make
  them contextual status detail and next action.
- Desktop launcher should be dense, predictable, and utilitarian.
- Do not store secrets in settings UI. Settings may edit non-secret defaults;
  token setup must point to user environment variables.

## Future scope needing design space

### Game Point launcher expansion

The launcher is the canonical Windows entrypoint for driver-facing rig functions.
Future rig features the operator should start, monitor, or tune should appear in
the launcher UI/status/settings path.

Likely future sections:

- Sidecar control: start/stop/restart, bind/port, health, logs.
- Rig screen: connection, client id, firmware version, last snapshot age.
- Hotspot: current state, client count, recoverability hints.
- Voice coach: reference archive, voice bank, backend/device, cue stream status.
- SimHub/haptics: installed/running, profile state, haptic event feed.
- Setup optimization: setup store path, rebuild status, suggestion status.
- Track Titan or other coaching oracle: provider configured, last advisory age,
  personal-data warnings.

### Rig screen future screens

- Setup Exchange browser: local setup files, source, freshness, load ack.
- Settings/Diagnostics: WiFi, sidecar URL, token present/missing without showing
  token, client id, firmware version, log counters.
- Voice status: armed/off, reference source, current cue, last spoken cue.
- Haptics status: fan, shaker, pedal rumble, SimHub/native route.
- Tyre condition heatmap: temperatures/pressures/wear from telemetry tick.
- Post-lap coaching summary: ranked improvement suggestions from sidecar.
- Debug screen: protocol counters and stale-data indicators for bring-up.

### In-game HUD alignment

- Shared status terms across CSP HUD, ESP32 screen, and launcher.
- Shared coaching phrase hierarchy:
  - now: the one action to take
  - why: one short reason
  - detail: target/current/delta only when useful
- Consistent reference-lap and sidecar health display.

## Non-goals

- Do not create a standalone web app unless a future issue explicitly asks for
  a browser surface.
- Do not replace Pocket Technician or Setup Exchange. The project replicates
  the needed APIs and coexists with those apps.
- Do not propose cloud setup storage as a dependency for the cockpit UI.
- Do not put secrets into committed docs, settings JSON, launcher UI text, logs,
  or screenshots.
- Do not make the Game Point launcher a splash screen or landing page.
- Do not design firmware screens that require images, web fonts, CSS layout, or
  non-LVGL widgets.

## Requested deliverables from design

For each proposed screen, return:

- Purpose: what decision/action the driver makes here.
- Wireframe: 320x480 for ESP32 or desktop window size for launcher.
- Component tree: LVGL/Tkinter-ready widgets.
- States: booting, disconnected, connected, stale, busy, success, warning, error.
- Data bindings: protocol topic/message or supervisor status field.
- Copy: exact labels, button text, empty states, toasts.
- Interaction: tap, scroll, plus/minus, hold-to-confirm if destructive.
- Implementation notes: files to edit and constraints to respect.
- Acceptance checks: what screenshot or live state proves the design works.

## Source file map for implementation agents

Docs:

- `docs/10_Development/14_Game_Point_Launcher.md`
- `docs/10_Development/12_WS_Sidecar_Protocol.md`
- `docs/01_Vault/AcCopilotTrainer/00_System/Current Focus.md`
- `docs/01_Vault/AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md`
- `docs/01_Vault/AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md`
- `docs/01_Vault/AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md`
- `docs/01_Vault/AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md`
- `docs/01_Vault/AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md`
- `docs/01_Vault/AcCopilotTrainer/03_Investigations/screen-end-to-end-bringup-2026-04-26.md`
- `docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-86-rig-screen-hotspot-autostart-2026-06-28.md`

Firmware:

- `firmware/screen/src/main.cpp`
- `firmware/screen/src/ui/screen_launcher.cpp`
- `firmware/screen/src/ui/screen_ac_copilot.cpp`
- `firmware/screen/src/ui/screen_pocket_technician.cpp`
- `firmware/screen/include/ui/tokens.h`
- `firmware/screen/include/ui/nav.h`
- `firmware/screen/platformio.ini`

Launcher:

- `tools/rig_launcher/app.py`
- `tools/rig_launcher/supervisor.py`
- `tools/rig_launcher/settings.py`
- `tools/rig_launcher/install.py`
- `tests/test_rig_launcher.py`

CSP Lua / protocol:

- `src/ac_copilot_trainer/ac_copilot_trainer.lua`
- `src/ac_copilot_trainer/modules/coaching_publisher.lua`
- `src/ac_copilot_trainer/modules/ws_bridge.lua`
- `src/ac_copilot_trainer/modules/setup_library.lua`
- `tools/ai_sidecar/server.py`
- `tools/ai_sidecar/external_protocol.py`

## Agent instruction

When a future agent implements a UI change from this package:

1. Keep the change in the surface that owns it: LVGL firmware, Tkinter Game
   Point launcher, or CSP Lua HUD.
2. Update this package when a new screen, visible state, setting, or status row
   is added.
3. Update `docs/10_Development/14_Game_Point_Launcher.md` and the launcher
   bullet in `AGENTS.md` when a new driver-facing launcher function is added.
4. Add focused tests for launcher status/settings changes, and run the narrow
   firmware or Lua checks available for screen/protocol changes.
5. Verify visual UI changes by rendering or photographing the actual target
   surface whenever possible; a diff alone is not a UI verification.
