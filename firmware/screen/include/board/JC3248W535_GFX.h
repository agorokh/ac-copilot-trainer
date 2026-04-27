// Arduino_GFX board config for the Guition JC3248W535 (ESP32-S3 + AXS15231B QSPI).
//
// Why Arduino_GFX and not LovyanGFX:
//   LovyanGFX 1.2.20 (the current Arduino-registry release) has no
//   Panel_AXS15231B class. The JC3248W535 uses the AXS15231B QSPI driver and
//   moononournation's Arduino_GFX ships Arduino_AXS15231B, which is the
//   community-standard driver for this board.
//
// WARNING - pin values are the widely shared community defaults for this board.
//   They have NOT yet been verified on-target. If the display stays black or
//   shows garbled output on the first Phase-1 boot, suspect these pins before
//   anything else. See:
//   docs/01_Vault/AcCopilotTrainer/03_Investigations/jc3248w535-board-identification-2026-04-21.md
//
// Touch controller is either CST820 or AXS5106; Phase 1 firmware does not
// use touch. Touch init is deferred to Phase-1b once we read the touch ID
// register.

#pragma once

#include <Arduino_GFX_Library.h>

// QSPI pins for the AXS15231B panel on this board.
// CS, SCK, D0..D3 per the JC3248W535 schematic / community configs.
#define JC_TFT_QSPI_CS   45
#define JC_TFT_QSPI_SCK  47
#define JC_TFT_QSPI_D0   21
#define JC_TFT_QSPI_D1   48
#define JC_TFT_QSPI_D2   40
#define JC_TFT_QSPI_D3   39
#define JC_TFT_RST       -1   // shared with board reset
#define JC_TFT_BL         1   // backlight (PWM capable)

// Panel native orientation is 320x480 portrait. We run in landscape (480x320),
// configured at construction so the panel hardware (MADCTL) and the canvas
// framebuffer match from the first byte. Calling Arduino_Canvas::setRotation
// later does NOT propagate to the underlying AXS15231B (Canvas's setRotation
// only adjusts its own coordinate transform), and the framebuffer is sized
// from construction-time WIDTH/HEIGHT — rotating the canvas after-the-fact
// makes its `_width` row stride disagree with `WIDTH`, which produced the
// "pixelish, doesn't fit the screen" diagonal-shear artefact on first flash.
//
// Source of truth for the panel's native dims lives in JC3248W535_Panel.h.
#include "JC3248W535_Panel.h"
#define JC_TFT_NATIVE_W  JC_PANEL_NATIVE_W
#define JC_TFT_NATIVE_H  JC_PANEL_NATIVE_H
// Convenience: landscape logical dimensions are the native portrait dims swapped.
#define JC_TFT_LANDSCAPE_W  JC_TFT_NATIVE_H
#define JC_TFT_LANDSCAPE_H  JC_TFT_NATIVE_W

// Build the QSPI panel + canvas. Returns the Arduino_Canvas — drawing into it
// goes to a PSRAM framebuffer; calling canvas->flush() pushes the whole frame
// to the panel in one DMA transfer.
//
// CRITICAL: AXS15231B over QSPI requires a full-framebuffer Arduino_Canvas.
// Pixel-by-pixel writes confuse the controller and produce the "black + thin
// white column" or "blue lines all over" artefacts seen in earlier attempts.
// Reference: github.com/me-processware/JC3248W535-Driver
//   - uses Arduino_AXS15231B with ips=false (no INVON for this panel)
//   - wraps in Arduino_Canvas (PSRAM framebuffer + flush())
//
// Rotation strategy: AXS15231B `rotation=0` is the only MADCTL combination
// the panel actually displays with on this board (other modes go black with
// a single white scan line — confirmed empirically; the controller likely
// requires `MX|MV` for the panel's physical mount). `rotation=0` MADCTL =
// `MX | MV | RGB` makes the controller transpose its scan, displaying the
// image in landscape from the user's POV.
//
// AXS15231B's MADCTL cases (per moononournation Arduino_GFX 1.4.7):
//   case 0 → MX | MV | RGB   ← LANDSCAPE (works on this board)
//   case 1 → MX | MY | RGB   ← black + white line on this board
//   case 2 → MY | MV | RGB   ← (untested)
//   case 3 → RGB only        ← black + white line on this board
//
// The trick to making landscape work without clipping:
//   `Arduino_TFT::setRotation` derives `_max_x = WIDTH - 1` from the ctor's
//   `w` arg. If we pass the panel as native portrait (320, 480), _max_x=319
//   and Canvas::flush()'s 480-wide draw call gets clipped to 320 cols —
//   the "not fit in wideness" bug. Solution: pass landscape dims (480, 320)
//   to the AXS15231B ctor so `_max_x=479` from the start, then build the
//   Canvas at matching landscape (480×320). LVGL renders landscape native
//   into the canvas, flush() sends 480×320 to the panel without clipping,
//   and the MV bit handles the actual physical scan rotation.
// Device is mounted PORTRAIT (iPhone-style) on the rig: user sees 320 wide
// × 480 tall. The AXS15231B in `rotation=0` (MX|MV|RGB) transposes its scan
// at the controller level — a memory image stored as W×H displays as H×W
// physically. So we render the UI directly into a NATIVE PORTRAIT canvas
// (320×480) and the MV transpose lands it on the panel correctly oriented
// for portrait viewing. Rendering 480×320 landscape into memory would put
// 480-wide content along the panel's short axis — what the user perceives
// as a 90°-rotated, sideways-reading layout.
inline Arduino_Canvas* jc3248w535_make_display() {
  Arduino_DataBus* bus = new Arduino_ESP32QSPI(
      JC_TFT_QSPI_CS, JC_TFT_QSPI_SCK,
      JC_TFT_QSPI_D0, JC_TFT_QSPI_D1, JC_TFT_QSPI_D2, JC_TFT_QSPI_D3);
  // rotation=0 → MADCTL = MX|MV|RGB. Native dims so _max_x=319, _max_y=479
  // — matches the canvas dims, no clipping. The MV bit handles the physical
  // scan transpose so portrait memory displays correctly on the device.
  Arduino_GFX* output = new Arduino_AXS15231B(
      bus, JC_TFT_RST, /*rotation=*/0, /*ips=*/false,
      JC_TFT_NATIVE_W, JC_TFT_NATIVE_H);
  Arduino_Canvas* canvas = new Arduino_Canvas(
      JC_TFT_NATIVE_W, JC_TFT_NATIVE_H, output);
  if (JC_TFT_BL >= 0) {
    pinMode(JC_TFT_BL, OUTPUT);
    digitalWrite(JC_TFT_BL, HIGH);
  }
  return canvas;
}
