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
// Native panel orientation is 320×480 portrait. main.cpp settles on
// rotation=1 (landscape 480×320) so we map raw → screen as
//     screen_x = ry
//     screen_y = (JC_TOUCH_NATIVE_W - 1) - rx
// where JC_TOUCH_NATIVE_W is the portrait width (320).

#pragma once

#include <Arduino.h>
#include <Wire.h>

#define JC_TOUCH_I2C_ADDR  0x3B
#define JC_TOUCH_SDA       4
#define JC_TOUCH_SCL       8
#define JC_TOUCH_NATIVE_W  320
#define JC_TOUCH_NATIVE_H  480

inline void jc_touch_begin() {
  Wire.begin(JC_TOUCH_SDA, JC_TOUCH_SCL, 400000);
}

// Returns true and fills *x/*y when a finger is present. Coords are in the
// landscape (rotation=1) frame: 0..479 x 0..319.
inline bool jc_touch_read(uint16_t* x, uint16_t* y) {
  static const uint8_t cmd[11] = {
      0xB5, 0xAB, 0xA5, 0x5A, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00};
  Wire.beginTransmission(JC_TOUCH_I2C_ADDR);
  Wire.write(cmd, sizeof(cmd));
  if (Wire.endTransmission() != 0) return false;

  uint8_t got = Wire.requestFrom(JC_TOUCH_I2C_ADDR, (uint8_t)8);
  if (got < 8) return false;
  uint8_t buf[8];
  for (uint8_t i = 0; i < 8; ++i) buf[i] = Wire.read();

  uint8_t fingers = buf[1];
  if (fingers == 0) return false;

  uint16_t rx = ((uint16_t)(buf[2] & 0x0F) << 8) | buf[3];
  uint16_t ry = ((uint16_t)(buf[4] & 0x0F) << 8) | buf[5];
  // Sentinel-reject obvious garbage frames.
  if (rx > 500 || ry > 500) return false;

  // Native-portrait → landscape (rotation=1) mapping. Verify on first
  // finger; flip the formula if axes come out swapped.
  *x = ry;
  *y = (uint16_t)((JC_TOUCH_NATIVE_W - 1) - rx);
  return true;
}
