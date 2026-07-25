// Hidden debug / diagnostics screen — issue #677 Part C.
//
// Opened from the launcher via a long-press on the "AC LAUNCHER" brand label.
// Shows connection state, last-frame age, peer count, free heap, and
// backpressure counters (frames ok / overflow drops / max drain).

#pragma once

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

lv_obj_t* screen_debug_create(void);

#ifdef __cplusplus
}
#endif
