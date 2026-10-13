#pragma once
#include <stdbool.h>
// Key colors (hue value: 0..191)
#define NEO_RED 0    // red
#define NEO_YEL 32   // yellow
#define NEO_GREEN 64 // green
#define NEO_CYAN 96  // cyan
#define NEO_BLUE 128 // blue
#define NEO_MAG 160  // magenta
#define NEO_WHITE 191  // white
#define NEO_BRIGHT_KEYS 2

// show bootloader entry feedback
void led_show_bootloader_indicator(void);

// initialize LED state
void led_init(void);

// update led task
void led_update();

// Update pressed state for a logical LED index
void led_set_key_state(int key, bool pressed);

