// Single-stack screen navigator — issue #86 Part A5.
//
// Max depth 2 (Launcher → app screen). Destroy-and-recreate model: each
// push runs the supplied factory to create a fresh `lv_obj_t*` screen,
// activates it via `lv_scr_load`, and remembers it on the back-stack so
// `ui_nav_pop` can return to the previous screen and delete the current.
//
// This keeps RAM low (only the two visible screens occupy heap at any
// time) at the cost of state — screens are responsible for re-fetching
// their data on `factory()`. Styles should be allocated once at
// `ui_nav_init()` time and reused.

#pragma once

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef lv_obj_t* (*ui_nav_factory_fn)(void);

// Initialize the navigator. Must be called after `lv_init()` and the
// display driver registration, and before any `ui_nav_push`.
void ui_nav_init(void);

// Push a new screen by running `factory` on the current LVGL context. The
// returned screen is loaded and remembered. No-op if the stack is full
// (depth 2). Safe to call from event callbacks (the previous screen is
// deleted on the next LVGL idle to avoid dangling event handlers).
void ui_nav_push(ui_nav_factory_fn factory);

// Pop back to the previous screen, deleting the current one. No-op when
// at the root screen.
void ui_nav_pop(void);

// True when the current screen is the root (Launcher).
bool ui_nav_at_root(void);

// Current depth (0..2).
uint8_t ui_nav_depth(void);

#ifdef __cplusplus
}
#endif
