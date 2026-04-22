---
type: investigation
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/screen-firmware-toolchain.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-board-identification-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Screen firmware — Windows build gotchas (2026-04-21)

First-build notes for `firmware/screen/` on Windows that cost real time to diagnose. Durable because none of them surface in the ESP32 docs, the JC3248W535 vendor repo, or the PlatformIO Arduino docs. Whoever touches the screen firmware next will hit them again if they're not documented.

## TL;DR

Four concrete surprises, each with a fix already in the tree:

1. **LovyanGFX 1.2.20 has no `Panel_AXS15231B`**, so the original ADR's LovyanGFX + LVGL path doesn't compile against this panel without a community fork. We pivoted to `moononournation/GFX Library for Arduino @ 1.4.7`, which ships `Arduino_AXS15231B` + `Arduino_ESP32QSPI` and is the de-facto community driver for JC3248W535 boards.
2. **Arduino_GFX must be pinned to 1.4.x.** 1.5.x+ pulls `esp32-hal-periman.h`, which only exists in ESP32 Arduino core 3.x. Our board/framework pin (`espressif32@6.13.0` → Arduino core 2.0.17) is on 2.x by design; upgrading to core 3.x is its own investigation we're not doing this sprint.
3. **Windows case-insensitive filesystem collision on `wifi.h`.** Arduino framework ships `<WiFi.h>`; naming our secrets header `secrets/wifi.h` made `#include "wifi.h"` resolve to the framework file — our `WIFI_SSID` / `WIFI_PASSWORD` defines silently vanished. Rename to `wifi_secrets.h` (or anything non-colliding); the repo now standardises on `secrets/wifi_secrets.h` + `secrets/sidecar.h`.
4. **Windows 8191-char command-line limit.** LovyanGFX + LVGL + ArduinoWebsockets built command lines of 25 094 chars. SCons needs explicit `TEMPFILE` wrapping for `CCCOM` / `CXXCOM` / `LINKCOM` / `ARCOM` on Windows. But: if the wrapping is applied in the wrong SCons phase, the FrameworkArduino sub-environment still uses bare-name compilers and the build fails at `Esp.cpp.o`. The fix is a pre/post hook split (see below).

## Root cause of the SCons phase trap

PlatformIO loads `extra_scripts` in three phases:

```
pre:  ← runs BEFORE the platform script (framework-arduinoespressif32/builder/main.py)
      platform script runs, sets CC / CXX to bare names ("xtensa-esp32s3-elf-g++")
      middle ← runs AFTER platform script, but BEFORE lib builders spawn child envs
      lib/framework envs are cloned from env (env.Clone())
post: ← runs LAST, after every env.Clone() has happened
```

A pre-only hook that calls `env.Replace(CXX=...)` gets **clobbered** by the platform script. A middle-only hook that calls `env.Replace(CXX=...)` fixes the top-level env but is **too late** for FrameworkArduino — that env was already cloned before the middle phase ran. The combination that actually works:

- **Pre-phase** patches `PATH` only, on both `env['ENV']['PATH']` and `os.environ['PATH']`. The `os.environ` half cascades into every subprocess via normal parent-inheritance, so even envs we don't touch can still resolve `xtensa-esp32s3-elf-g++` from the toolchain bin.
- **Post-phase** does the `env.Replace(CC/CXX/AR/LINK)` + `TEMPFILE` wrapping, on `env`, `projenv`, AND every lib builder (`env.GetLibBuilders()` walk). Post-phase runs last, so `env.Replace` wins over the platform script's bare-name CC/CXX — and touching `lb.env` for each lib builder reaches FrameworkArduino.

Code lives in `firmware/screen/tools/long_cmd_fix.py` (pre) and `firmware/screen/tools/long_cmd_fix_post.py` (post). `platformio.ini` registers both:

```ini
extra_scripts =
    pre:tools/long_cmd_fix.py
    post:tools/long_cmd_fix_post.py
```

## Validation evidence (2026-04-21)

- `pio run` (clean) completes in **135 s**. Before the split, the build failed at `FrameworkArduinoEsp32/Esp.cpp.o` with "The command line is too long."
- `pio run -t upload --upload-port COM6` completes in **29 s**, writes 923 KB / 14.1% of the 6.25 MB app partition.
- First boot after flash logs `[boot] AC Copilot Screen ac-copilot-screen-01` on native USB CDC (COM6), PSRAM init succeeds, WiFi associates, WebSocket retry loop runs against the configured sidecar URL without crashing.

## Consequences for future work

- Any time we add a library that significantly widens the link line (LVGL in Phase 2, TinyUSB, BLE, extra sensor stacks), **keep the post-phase hook wired** — don't assume it's needed only because LVGL was in the tree. The FrameworkArduino compile step alone can exceed the limit on Windows once the include path set gets long enough.
- If we upgrade to ESP32 Arduino core 3.x later, Arduino_GFX can move to 1.5.x+ and the Arduino_ESP32QSPI driver gets `periman` pin-muxing instead of the 2.x shim. Don't do that upgrade and the LVGL Phase-2 bring-up in the same PR.
- The original ADR `screen-firmware-toolchain.md` still correctly identifies the layer split (GFX vs UI vs WS vs JSON). Only the GFX and UI layer concretes changed; see the ADR's 2026-04-21 addendum.

## Follow-ups

- Consider upstreaming a note to the JC3248W535 vendor README pointing at Arduino_GFX 1.4.x explicitly — community issue trackers are full of first-timers hitting the 1.5.x+ `periman` compile failure.
- When Phase 2 LVGL bring-up lands, the LovyanGFX `#define LV_COLOR_FORMAT_UNKNOWN` clash is no longer a concern (we're not using LovyanGFX at all), but LVGL's own `lv_conf.h` still needs `LV_COLOR_DEPTH=16` + `LV_COLOR_16_SWAP=1` to match Arduino_AXS15231B byte order — verify at first-pixel before investing in screen authoring.
