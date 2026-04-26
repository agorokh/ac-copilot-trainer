// Toast — issue #86 Part D6.
//
// Screen-level singleton red bottom-bar toast (3 s default). Used by the
// Pocket Technician screen for setup-load failures (must-be-in-pits etc.)
// and reserved for Part E (Setup Exchange) to share the same widget.
//
// The toast attaches itself to the *currently active screen* on each call,
// so it persists across screen pushes/pops only as long as the user stays
// on the originating screen. Auto-deletes after the timeout via
// `lv_timer_t` one-shot. Safe to call before the LVGL display is fully
// ready (no-ops if `lv_scr_act()` returns nullptr).

#pragma once

#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

// Show a red toast on the active screen for `ms_visible` milliseconds.
// `text` is copied into the label so the caller may free its buffer
// immediately after the call returns.
void ui_toast_show(const char* text, uint32_t ms_visible);

// Convenience: 3 s display, the canonical duration from issue #86 D6.
void ui_toast_error(const char* text);

#ifdef __cplusplus
}
#endif
