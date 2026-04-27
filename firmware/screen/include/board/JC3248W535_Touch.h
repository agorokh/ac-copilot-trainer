// AXS15231B I²C touch reader for the Guition JC3248W535.
//
// On this board the AXS15231B display controller doubles as a single-touch
// I²C slave at address 0x3B (SDA=GPIO4, SCL=GPIO8). There is NO separate
// touch IC — earlier "CST820 vs AXS5106" framing in the board header is
// obsolete (see screen-ui-stack-lvgl-touch.md).
//
// Snippet adapted verbatim from the decision ADR
//   docs/01_Vault/AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
// which in turn cites:
//   - F1ATB JC3248W535 setup writeup
//   - me-processware/JC3248W535-Driver
//
// Native panel orientation is 320×480 portrait, and the rig screen is
// MOUNTED portrait (iPhone-style), so the LVGL logical frame is also 320×480.
// Raw I²C coords come in panel-native (rx 0..319, ry 0..479) and map 1:1
// to LVGL coords with no rotation — but typically the touch axes are flipped
// from the display axes on this board, so we still apply the simple flip
// `(NATIVE_W-1)-rx` if testing reveals a mirrored axis. Start with the
// straight identity mapping and flip empirically if a finger at top-left
// reads as bottom-right.

#pragma once

#include <Arduino.h>
#include <Wire.h>

#define JC_TOUCH_I2C_ADDR  0x3B
#define JC_TOUCH_SDA       4
#define JC_TOUCH_SCL       8
// Source of truth for these dimensions is JC3248W535_Panel.h. (Sourcery
// review on PR #91 - keep display + touch in sync via a single header.)
#include "JC3248W535_Panel.h"
#define JC_TOUCH_NATIVE_W  JC_PANEL_NATIVE_W
#define JC_TOUCH_NATIVE_H  JC_PANEL_NATIVE_H

inline void jc_touch_begin() {
  Wire.begin(JC_TOUCH_SDA, JC_TOUCH_SCL, 400000);
}

// Returns true and fills *x/*y when a finger is present. Coords are in the
// portrait LVGL frame: 0..319 x 0..479 (matches panel native + portrait mount).
inline bool jc_touch_read(uint16_t* x, uint16_t* y) {
  static const uint8_t cmd[11] = {
      0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00};
  // Optional low-rate I2C error logging. Enable from PlatformIO with
  //   build_flags = -DJC_TOUCH_DEBUG_I2C
  // to distinguish "no finger" from I2C wiring/noise problems without
  // flooding the serial console. (Sourcery suggestion on PR #91.)
#ifdef JC_TOUCH_DEBUG_I2C
  static uint32_t jc_touch_i2c_err = 0;
#endif
  Wire.beginTransmission(JC_TOUCH_I2C_ADDR);
  Wire.write(cmd, sizeof(cmd));
  const uint8_t tx_status = Wire.endTransmission();
  if (tx_status != 0) {
#ifdef JC_TOUCH_DEBUG_I2C
    if ((++jc_touch_i2c_err % 128) == 0) {
      Serial.printf("[touch] I2C tx err=%u (sample %u)\n", tx_status, jc_touch_i2c_err);
    }
#endif
    return false;
  }

  const uint8_t got = Wire.requestFrom(JC_TOUCH_I2C_ADDR, (uint8_t)8);
  if (got < 8) {
#ifdef JC_TOUCH_DEBUG_I2C
    if ((++jc_touch_i2c_err % 128) == 0) {
      Serial.printf("[touch] I2C short read got=%u (sample %u)\n", got, jc_touch_i2c_err);
    }
#endif
    return false;
  }
  uint8_t buf[8];
  for (uint8_t i = 0; i < 8; ++i) buf[i] = Wire.read();

  // Some AXS15xxx variants encode status/flags in the high nibble of this
  // byte; only the low nibble is the actual finger count. Mask so a future
  // controller revision that sets status bits doesn't make us parse bogus
  // coordinates with no real touch present. (Sourcery review on PR #91.)
  uint8_t fingers = buf[1] & 0x0F;
  if (fingers == 0) return false;

  uint16_t rx = ((uint16_t)(buf[2] & 0x0F) << 8) | buf[3];
  uint16_t ry = ((uint16_t)(buf[4] & 0x0F) << 8) | buf[5];
  // Reject any frame whose raw coordinates exceed the native panel bounds.
  // The landscape mapping below computes `(NATIVE_W - 1) - rx` as a
  // `uint16_t`, so any rx >= NATIVE_W (320) would underflow and produce a
  // wrapped y in the 65k range. Clamping against the panel size — not an
  // arbitrary 500 sentinel — keeps the formula safe even on noisy I²C
  // frames. (Reported by gemini-code-assist + chatgpt-codex on PR #91.)
  if (rx >= JC_TOUCH_NATIVE_W || ry >= JC_TOUCH_NATIVE_H) return false;

  // Portrait mount: native panel coords match LVGL coords 1:1. Identity
  // mapping for now; flip a single axis here if testing shows a mirror.
  *x = rx;
  *y = ry;
  return true;
}
