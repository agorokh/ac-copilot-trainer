// Launcher screen factory — issue #86 Part B (stub in Part A).

#pragma once

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

// Build and return a fresh launcher screen. Call this through `ui_nav_push`,
// not directly. Part B ships the Menu.tsx port; later parts extend the other
// app tiles without changing this factory's contract.
lv_obj_t* launcher_create(void);

#ifdef __cplusplus
}
#endif
