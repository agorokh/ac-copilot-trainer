---
type: decision
status: superseded-in-part
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-board-identification-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md
  - AcCopilotTrainer/01_Decisions/_index.md
---

# Screen firmware toolchain

## Context

The rig-mounted touchscreen is a Guition JC3248W535 — ESP32-S3 with an **AXS15231B QSPI** panel and a **CST820/AXS5106** I²C capacitive touch controller. Board identity confirmed in [`03_Investigations/jc3248w535-board-identification-2026-04-21.md`](../03_Investigations/jc3248w535-board-identification-2026-04-21.md). The firmware has to drive that panel, run an LVGL UI, join WiFi, maintain a WebSocket connection to our existing Python sidecar, and parse/emit JSON.

The panel is **not RGB-parallel**, so graphics libraries that assume an i80 / RGB bus (stock TFT_eSPI setups) will not work without a patched driver.

## Decision

Adopt this stack:

| Layer | Choice |
|---|---|
| IDE | **PlatformIO** inside VS Code |
| Framework | `espressif32 @ ^6.x` + Arduino |
| GFX driver | **LovyanGFX** (supports AXS15231B natively; cleaner per-board config than a Bodmer TFT_eSPI fork) |
| UI engine | **LVGL v9** (display + input device bindings via LovyanGFX) |
| UI authoring | **SquareLine Studio** (exports LVGL C for the Phase 2 screens) |
| WebSocket client | `links2004/arduinoWebSockets` or `gilmaimon/ArduinoWebsockets` |
| JSON | `bblanchon/ArduinoJson v7` |

## Consequences

- No Arduino-IDE complexity; shares VS Code with the rest of the repo.
- No third-party USB serial driver needed on the dev PC (ESP32-S3 native USB).
- SquareLine Studio becomes a hard dependency for anyone editing Phase 2 UI — must note in `WARP.md` dev setup.
- Cable matters: USB-C to USB-C must be data-capable (observed 2026-04-21 — the Oculus Rift USB-C cable works).

## Alternatives considered

- **ESP-IDF + LVGL** — more control, but overkill for our scope and pulls the firmware out of the Arduino ecosystem the team already knows.
- **MicroPython + LVGL** — works on ESP32-S3 but the WebSocket client + ArduinoJson-equivalent stack is less mature; Python-inside-Python indirection is unappealing.
- **Bodmer TFT_eSPI with AXS15231B patch** — the patch exists as community forks but is drift-prone. LovyanGFX upstream support is cleaner.

## Open questions

- Whether to pin LVGL to a specific minor version in `platformio.ini` or track `^9.x`. Pin initially to avoid breakage mid-Phase-1.

## Addendum — Shipped 2026-04-21 (Phase 1)

Reality diverged from the decision table above in two places. Keeping the decision shape (IDE / Framework / GFX / UI / WS / JSON) but flagging the concretes that changed:

| Layer | Original decision | Shipped in Phase 1 | Reason |
|---|---|---|---|
| GFX driver | **LovyanGFX** | **moononournation/GFX Library for Arduino @ 1.4.7** | LovyanGFX 1.2.20 has no `Panel_AXS15231B` (confirmed by searching its `panel/` folder). Arduino_GFX ships `Arduino_AXS15231B` + `Arduino_ESP32QSPI` and is the community-standard driver for JC3248W535 boards. **Must pin 1.4.x** — 1.5.x+ requires `esp32-hal-periman.h` from ESP32 Arduino core 3.x; our `espressif32@6.13.0` + Arduino core 2.0.17 is on 2.x by design. |
| UI engine | **LVGL v9** | **Deferred to Phase 2** | LVGL + LovyanGFX double-define `LV_COLOR_FORMAT_UNKNOWN`; with the GFX pivot the Phase-2 bring-up is LVGL-on-Arduino_GFX instead, which needs its own lv_conf.h + display-flush bridge. Phase 1 ships plain Arduino_GFX drawing and hits the milestones (boot → WiFi → WS → status screen) without the UI engine. |
| Framework pin | `espressif32 @ ^6.x` | `espressif32 @ 6.13.0` exact | Pin to avoid Arduino-core 3.x breaking the Arduino_GFX 1.4.x pin. |
| Extras (not in original table) | — | `pre:tools/long_cmd_fix.py` + `post:tools/long_cmd_fix_post.py` | Windows 8191-char command-line limit forces SCons `TEMPFILE` wrapping for `CCCOM` / `CXXCOM` / `LINKCOM` / `ARCOM`. Pre-only or middle-only hooks don't propagate to FrameworkArduino's cloned env — the pre+post split does. See [`03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md`](../03_Investigations/screen-firmware-windows-build-gotchas-2026-04-21.md). |
| Extras (not in original table) | — | Secrets header **must not** be `wifi.h` | Windows case-insensitive filesystem collides with framework `<WiFi.h>`. We use `secrets/wifi_secrets.h` + `secrets/sidecar.h`. |

**What didn't change**: PlatformIO in VS Code, Arduino framework, ArduinoWebsockets, ArduinoJson v7, SquareLine Studio for Phase-2 authoring. The ADR's alternatives analysis (ESP-IDF, MicroPython, TFT_eSPI forks) is still correct and the Arduino-side decision still stands.

**Revisit when**: upgrading to ESP32 Arduino core 3.x (enables Arduino_GFX 1.5.x+) — do that in its own PR, not stacked with the LVGL Phase-2 bring-up.
