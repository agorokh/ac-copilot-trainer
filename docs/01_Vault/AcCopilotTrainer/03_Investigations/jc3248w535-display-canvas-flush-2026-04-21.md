---
type: investigation
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/01_Decisions/screen-firmware-toolchain.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# JC3248W535 display init: Canvas + ips=false (2026-04-21)

## Symptom

After multiple PlatformIO flashes of the Phase-1 firmware, the panel showed
**black + a single white column on the right edge**. Boot serial confirmed
firmware ran end-to-end (`gfx->begin()` returned true; rotation sweeps and
chrome draws all logged successfully) but no pixels became visible.
Backlight pulse on 7 candidate GPIO pins (1, 38, 5, 16, 18, 6, 21)
produced no observable brightness change.

Restoring the factory image at `_factory-backup/jc3248w535_v0.9.1_factory.bin`
brought the stock screen back instantly, proving hardware was fine.

## Root cause

Two stacked bugs in our Arduino_GFX setup:

1. **Wrong init table.** `Arduino_AXS15231B` in
   `moononournation/GFX Library for Arduino @ 1.4.7` ships an init table
   (commands `0xA2`, `0xC1`, `0xC4`, `0xC7`, `0xD0`–`0xDF`, gamma
   `0xE0`–`0xE5`) tuned for the **1.91" 360x640 round AMOLED** variant of
   the AXS15231B. Sending those vendor-specific gamma/voltage values to the
   JC3248W535's **3.2" 320x480 IPS LCD** put the panel in a partial-init
   state.

2. **No framebuffer flush.** AXS15231B over QSPI requires writing a full
   frame in one DMA burst. Per-pixel `writePixel`/`fillRect` calls each
   trigger their own `CASET`/`RASET`/`RAMWR` cycle, which the controller
   garbles into the "blue lines all over" pattern we saw mid-debug.

## Fix

Reference: [me-processware/JC3248W535-Driver](https://github.com/me-processware/JC3248W535-Driver).

```cpp
// firmware/screen/include/board/JC3248W535_GFX.h
Arduino_DataBus* bus = new Arduino_ESP32QSPI(CS, SCK, D0, D1, D2, D3);
Arduino_GFX* output  = new Arduino_AXS15231B(bus, RST, /*rotation=*/0,
                                             /*ips=*/false, 320, 480);
Arduino_GFX* canvas  = new Arduino_Canvas(320, 480, output);  // <- the missing piece
return canvas;
```

`ips=false` skips the `INVON` step that the moononournation driver adds when
`ips=true`; the JC3248W535 is non-inverted. **Every scene must call
`canvas->flush()`** after drawing — `setup()` flushes at end of init,
`refresh_ui()` flushes only when a row changed.

Commit: [d8d3d2e](https://github.com/agorokh/ac-copilot-trainer/commit/d8d3d2e)
on `feat/issue-81-external-ws-client`.

## Things that did NOT help (and why)

- Custom `Arduino_JC3248W535` subclass with hand-rolled minimal init
  (SWRESET → SLPOUT → COLMOD → MADCTL → INVON → NORON → DISPON + GRAM
  clear). Made the panel respond ("blue lines all over") but still
  garbled because the per-pixel write path was still wrong.
- Rotation sweep (0/1/2/3) with full-screen colour fills + diagonal
  crosses — confirmed addressing was reaching some columns, but
  Arduino_GFX's per-pixel path bypasses the canvas DMA flush.
- Backlight pin sweep across {1, 38, 5, 16, 18, 6, 21} — IPS panels look
  uniformly black without any GRAM data even when BL is on, so a brightness
  change was never going to be visible until the canvas+flush fix landed.

## How to recover from a bricked-looking panel

1. Restore factory: `python esptool.py --port COM6 --chip esp32s3 write_flash 0x0
   firmware/screen/_factory-backup/jc3248w535_v0.9.1_factory.bin`.
2. If stock screen returns → our firmware is the regression; iterate.
3. If still nothing → check FPC ribbon, USB cable (data not charge-only),
   power source.
