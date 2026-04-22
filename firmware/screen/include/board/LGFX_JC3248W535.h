// LovyanGFX board config for the Guition JC3248W535 (ESP32-S3 + AXS15231B QSPI).
//
// WARNING — pin values are the widely shared community defaults for this board
// (see the JC3248W535 vendor examples and the Makerfabs / Guition forum
// references). They have NOT yet been verified on-target. If the display stays
// black or shows garbled output on the first Phase-1 boot, suspect these pins
// before anything else. See:
//   docs/01_Vault/AcCopilotTrainer/03_Investigations/jc3248w535-board-identification-2026-04-21.md
//
// Touch controller is either CST820 or AXS5106; we hook it up here but the
// Phase-1 firmware does not rely on it. Touch init is deferred to Phase-1b
// once we read the touch ID register.

#pragma once

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

class LGFX_JC3248W535 : public lgfx::LGFX_Device {
  lgfx::Panel_AXS15231B _panel_instance;
  lgfx::Bus_QSPI        _bus_instance;
  lgfx::Light_PWM       _light_instance;

 public:
  LGFX_JC3248W535() {
    {  // QSPI bus for the AXS15231B panel.
      auto cfg = _bus_instance.config();
      cfg.spi_host      = SPI2_HOST;
      cfg.spi_mode      = 0;
      cfg.freq_write    = 40 * 1000 * 1000;
      cfg.freq_read     = 16 * 1000 * 1000;
      cfg.pin_sclk      = 47;
      cfg.pin_io0       = 21;
      cfg.pin_io1       = 48;
      cfg.pin_io2       = 40;
      cfg.pin_io3       = 39;
      cfg.use_lock      = true;
      cfg.dma_channel   = SPI_DMA_CH_AUTO;
      _bus_instance.config(cfg);
      _panel_instance.setBus(&_bus_instance);
    }

    {  // Panel geometry and control pins.
      auto cfg = _panel_instance.config();
      cfg.pin_cs           = 45;
      cfg.pin_rst          = -1;   // shared with board reset
      cfg.pin_busy         = -1;
      cfg.panel_width      = 320;
      cfg.panel_height     = 480;
      cfg.offset_x         = 0;
      cfg.offset_y         = 0;
      cfg.offset_rotation  = 0;
      cfg.dummy_read_pixel = 8;
      cfg.dummy_read_bits  = 1;
      cfg.readable         = false;
      cfg.invert           = true;
      cfg.rgb_order        = false;
      cfg.dlen_16bit       = false;
      cfg.bus_shared       = false;
      _panel_instance.config(cfg);
    }

    {  // Backlight (PWM) — GPIO 1 on this board per community configs.
      auto cfg = _light_instance.config();
      cfg.pin_bl      = 1;
      cfg.invert      = false;
      cfg.freq        = 44100;
      cfg.pwm_channel = 7;
      _light_instance.config(cfg);
      _panel_instance.setLight(&_light_instance);
    }

    setPanel(&_panel_instance);
  }
};
