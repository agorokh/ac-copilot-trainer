---
type: decision
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/01_Decisions/screen-firmware-toolchain.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/_index.md
---

# Screen UI stack: LVGL 8.3 + AXS15231B touch + SquareLine

## Context

Phase-1 firmware ships with `Arduino_AXS15231B` + `Arduino_Canvas` + `flush()`
drawing a static status screen — no touch, no widgets. We need to drive
**Pocket Technician**, **Setup Exchange**, and our own Copilot Trainer
from physical touch on the JC3248W535. That requires a real UI
toolkit, not hand-rolled `gfx->fillRect()`.

## Decision

1. **Touch chip is the AXS15231B itself.** The display controller doubles
   as a single-touch I2C target at address `0x3B` (SDA=GPIO4, SCL=GPIO8).
   Drop the "CST820 vs AXS5106" framing in the board header — there is no
   separate touch IC on this board.

2. **Embed a 40-line `JC3248W535_Touch.h`** rather than pull TouchLib
   (no AXS15231 support) or me-processware's wrapper (extra dep weight).
   Send the 11-byte read command `B5 AB A5 5A 00 00 00 08 00 00 00`,
   read 8 bytes, parse `fingers = buf[1]`, `x = ((buf[2] & 0x0F) << 8) |
   buf[3]`, `y = ((buf[4] & 0x0F) << 8) | buf[5]`. Sentinel-reject any
   coord > 500. Map to landscape via `screen_x = ry; screen_y = 319 - rx`
   (verify on first finger). Source: F1ATB writeup +
   me-processware/JC3248W535-Driver.

3. **LVGL 8.3.x, NOT 9.x.** ESP32 Arduino core 2.0.17 (espressif32@6.13.0)
   is the constraint; LVGL 9.x examples target core 3.x. Keep
   `LV_COLOR_16_SWAP=1` (already set in `lv_conf.h`). Add to platformio.ini:
   `lib_deps += lvgl/lvgl @ ~8.3.11`.

4. **Canvas-aware flush bridge** (Pattern A — partial buffers, ~60 Hz cap):

   ```cpp
   void my_disp_flush(lv_disp_drv_t* drv, const lv_area_t* area, lv_color_t* color_p) {
     uint32_t w = area->x2 - area->x1 + 1;
     uint32_t h = area->y2 - area->y1 + 1;
     gfx->draw16bitBeRGBBitmap(area->x1, area->y1, (uint16_t*)&color_p->full, w, h);
     lv_disp_flush_ready(drv);
   }
   void loop() {
     lv_timer_handler();
     static uint32_t last = 0;
     if (millis() - last > 16) {
       ((Arduino_Canvas*)gfx)->flush();   // single QSPI DMA push of dirty PSRAM
       last = millis();
     }
     delay(2);
   }
   ```

   Without the explicit `canvas->flush()` call, draws stay in PSRAM and the
   panel never paints — same failure mode as the pre-canvas Phase-1 bug.

5. **SquareLine Studio for layout**, exported as **"Arduino with TFT_eSPI"
   targeting LVGL 8.3**, then *manually replace* its display init. Copy
   only `ui/*.c/.h` into `firmware/screen/src/ui/`; call `ui_init()` after
   our display+touch+LVGL bring-up. Do all rotation in
   `Arduino_AXS15231B::setRotation()`, never inside SquareLine.

## UX rules for car-cockpit screens (480×320 landscape)

- Hit targets **≥ 60×60 px** (gloves + chair vibration + 13 mm DPI).
- **Tile grid, max 6 tiles** (3×2 or 2×3); use `lv_tileview` for swipe
  between modes (Pit / Race / Tactile / Settings).
- Numerics ≥ 36 px semibold tabular figures; labels ≥ 20 px.
- **Color = state, not decoration**. Pair with shape/icon for color-blind
  safety. Pure-black bg, near-white text, saturated state colors only on
  indicators.
- **Single tap = primary action; swipe = navigation.** No long-press, no
  double-tap (invisible affordances are dangerous mid-corner).
- Destructive actions confirm via **2-second hold-to-confirm bar**, never
  modals (modals trap the eye).
- **Always-visible 24 px status strip** on top: WS state, telemetry age,
  current profile.

## Consequences

- We commit to LVGL 8.3 for the rest of Phase-2; any move to LVGL 9.x is
  gated on first upgrading to ESP32 Arduino core 3.x (separate ADR).
- The 40-line touch reader becomes the canonical input path; LVGL's
  `indev_drv.read_cb` calls `jc_touch_read()` and passes coords to LVGL.
- SquareLine projects must be re-exported when LVGL is bumped; pin a
  template repo so the export wiring is reproducible.

## Alternatives considered

- **TFT_eSPI as the display driver.** Rejected — does not ship a working
  AXS15231B QSPI driver in 2026; would require a port that duplicates
  what `Arduino_AXS15231B` already does.
- **LovyanGFX with a hand-rolled `Panel_AXS15231B`.** Rejected for now —
  upstream LovyanGFX 1.2.20 still has no AXS15231B class; rolling our own
  panel class is a side quest with no UI win over Arduino_GFX + LVGL.
- **LVGL 9.4.** Rejected for Phase-2 — requires Arduino core 3.x upgrade
  + Arduino_GFX 1.6+ which deprecates our pinned 1.4.7 lib graph.
- **Roll our own widget toolkit on top of Arduino_GFX.** Rejected — touch
  hit-testing + animation + theming is months of work LVGL gives us free.

## References

- [me-processware/JC3248W535-Driver](https://github.com/me-processware/JC3248W535-Driver)
- [F1ATB JC3248W535 setup writeup](https://f1atb.fr/home-automation/esp32-s3/esp32-s3-3-5-inch-capacitive-touch-ips-display-setup/)
- [Arduino_GFX LVGL_v8 example](https://github.com/moononournation/Arduino_GFX/blob/master/examples/LVGL/LVGL_Arduino_v8/LVGL_Arduino_v8.ino)
- [refob/Arduino_JC3248W535_LVGL9.4](https://github.com/refob/Arduino_JC3248W535_LVGL9.4) (reference for the LVGL 9 / core 3 future path)
