// Minimal LVGL v9 config for the Phase-1 status screen.
// Copy + prune of the upstream lv_conf_template.h; only the flags we care
// about are annotated. Everything else uses upstream defaults.

#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

/* ------------------ COLOR ------------------ */
#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 1  // AXS15231B big-endian byte order

/* ------------------ MEMORY ----------------- */
#define LV_MEM_SIZE (48U * 1024U)   // small heap; draw buf lives in PSRAM
#define LV_MEM_ADR  0
#define LV_MEM_AUTO_DEFRAG 1

/* ------------------ HAL -------------------- */
#define LV_TICK_CUSTOM          1
#define LV_TICK_CUSTOM_INCLUDE  "Arduino.h"
#define LV_TICK_CUSTOM_SYS_TIME_EXPR (millis())

#define LV_USE_PERF_MONITOR 0
#define LV_USE_MEM_MONITOR  0
#define LV_USE_LOG          1
#define LV_LOG_LEVEL        LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF       1

/* ------------------ FEATURES --------------- */
#define LV_USE_FLEX          1
#define LV_USE_GRID          1
#define LV_USE_ANIMATION     1

/* Widgets used by the status screen. */
#define LV_USE_LABEL    1
#define LV_USE_BTN      1
#define LV_USE_BAR      1
#define LV_USE_OBJ      1

/* Fonts: Montserrat 14 is plenty for a status screen. */
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_DEFAULT &lv_font_montserrat_14

/* We manually drive lv_tick_inc via millis(). */
#define LV_USE_OS LV_OS_NONE

#endif /* LV_CONF_H */
