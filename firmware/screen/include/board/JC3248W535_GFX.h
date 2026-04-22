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

// Panel native orientation is 320x480 portrait. We rotate at runtime to
// landscape (480x320). Arduino_AXS15231B accepts width/height in its ctor
// as the *native* portrait dimensions; rotation is applied via setRotation.
#define JC_TFT_NATIVE_W  320
#define JC_TFT_NATIVE_H  480

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
inline Arduino_GFX* jc3248w535_make_display() {
  Arduino_DataBus* bus = new Arduino_ESP32QSPI(
      JC_TFT_QSPI_CS, JC_TFT_QSPI_SCK,
      JC_TFT_QSPI_D0, JC_TFT_QSPI_D1, JC_TFT_QSPI_D2, JC_TFT_QSPI_D3);
  Arduino_GFX* output = new Arduino_AXS15231B(
      bus, JC_TFT_RST, /*rotation=*/0, /*ips=*/false,
      JC_TFT_NATIVE_W, JC_TFT_NATIVE_H);
  Arduino_GFX* canvas = new Arduino_Canvas(
      JC_TFT_NATIVE_W, JC_TFT_NATIVE_H, output);
  if (JC_TFT_BL >= 0) {
    pinMode(JC_TFT_BL, OUTPUT);
    digitalWrite(JC_TFT_BL, HIGH);
  }
  return canvas;
}
