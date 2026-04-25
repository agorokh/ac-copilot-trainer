// Launcher screen factory — issue #86 Part B (stub in Part A).

#pragma once

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

// Build and return a fresh launcher screen. Call this through `ui_nav_push`,
// not directly. Part A ships a placeholder; Part B will replace it with the
// real Menu.tsx port.
lv_obj_t* launcher_create(void);

#ifdef __cplusplus
}
#endif
