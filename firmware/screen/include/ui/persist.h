// NVS persistence for last active screen + Setup Exchange sort — issue #677 Part A.
//
// Uses ESP32 Preferences (NVS). Writes on change (not on shutdown) so a hard
// power-cut still restores the last committed values.

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    UI_SCREEN_LAUNCHER = 0,
    UI_SCREEN_AC_COPILOT = 1,
    UI_SCREEN_POCKET_TECH = 2,
    UI_SCREEN_SETUP_EXCHANGE = 3,
    UI_SCREEN_DEBUG = 4,
} ui_screen_id_t;

typedef enum {
    SE_SORT_DOWNLOADS_DESC = 0,
    SE_SORT_NAME_ASC = 1,
} se_sort_t;

// Open the NVS namespace. Safe to call more than once.
void ui_persist_begin(void);

ui_screen_id_t ui_persist_get_screen(void);
// Persist immediately when the active app screen changes.
void ui_persist_set_screen(ui_screen_id_t id);

se_sort_t ui_persist_get_se_sort(void);
void ui_persist_set_se_sort(se_sort_t sort);

// Push the persisted non-launcher screen (if any) onto the nav stack.
// Call after the launcher has been pushed at boot.
void ui_persist_restore_screen(void);

#ifdef __cplusplus
}
#endif
