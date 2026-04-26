// AC Copilot mirror screen — issue #86 Part C.
//
// Read-only mirror of the trainer's live coaching state. Subscribes to
// `state.snapshot topic="coaching.snapshot"` (10 Hz from the trainer) plus
// the older `corner_advice` event for richer LLM hints. Layout ports
// `ACCopilot.tsx` from `agorokh/Ingamecoachingtrainerdesign`.
//
// The screen owns a small `coaching_snapshot_t` cached by `main.cpp`'s
// WS dispatch — the WS code calls `screen_ac_copilot_apply_snapshot()`
// when a frame arrives, and the screen redraws its labels. If the screen
// is not currently active (user navigated away), the apply call updates
// the static cache only — the next push of the screen renders from cache.

#pragma once

#include <lvgl.h>
#include <stdint.h>
#ifdef __cplusplus
#include <cstdbool>
#else
#include <stdbool.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    char        primary_line[96];
    char        secondary_line[160];
    char        corner_label[32];   // e.g. "Lesmo 1" or "T3"
    char        kind[24];           // "brake" | "line" | "info" | "placeholder"
    char        sub_state[24];      // "approaching" | "in_corner" | ...
    int32_t     target_speed_kmh;   // -1 = unknown
    int32_t     current_speed_kmh;  // -1 = unknown
    int32_t     dist_to_brake_m;    // -1 = unknown
    int32_t     progress_pct;       // 0..100
    bool        has_data;           // false until first apply
} coaching_snapshot_t;

// Build the screen. Reads the cached snapshot — paint nothing-yet copy
// when `has_data` is false, otherwise the live values. Takes ownership
// of the rendering only; the cache is owned by `main.cpp`.
lv_obj_t* screen_ac_copilot_create(void);

// WS dispatch entry point. Updates the static snapshot cache and, if the
// screen is currently active, queues an `lv_async_call` to refresh the
// labels without doing widget mutations from the WS callback context.
//
// Safe to call from any thread / context that holds the LVGL mutex on
// hosts that have one — on Arduino + LVGL 8.3 there is no mutex, so the
// call must happen from the main loop, which is where `main.cpp`'s WS
// dispatch already lives.
void screen_ac_copilot_apply_snapshot(const coaching_snapshot_t* snap);

// Override the secondary line with a richer LLM advice (corner_advice
// pipeline from PR #75). Stores the override against `corner_id`; the
// screen swaps in the override only when the live snapshot's
// corner_label matches. Pass an empty `text` to clear.
void screen_ac_copilot_apply_corner_advice(const char* corner_id, const char* text);

#ifdef __cplusplus
}
#endif
