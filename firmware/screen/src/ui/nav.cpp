// Single-stack screen navigator implementation — issue #86 Part A5.

#include "ui/nav.h"

#include <Arduino.h>

namespace {

constexpr uint8_t  NAV_MAX_DEPTH = 2;
lv_obj_t*          stack[NAV_MAX_DEPTH] = {nullptr, nullptr};
uint8_t            depth = 0;            // number of screens currently on stack

// Idle-time deferred deletion. `lv_async_call` runs once on the next LVGL
// task tick, after the current event chain unwinds — safe place to free
// the prior screen even if the call originated from one of its widgets.
// `lv_async_call` already queues this callback per-pointer, so no extra
// coordination state is needed (sourcery + cursor on PR #91).
void async_delete_cb(void* ptr) {
    if (ptr) {
        lv_obj_del((lv_obj_t*)ptr);
    }
}

}  // namespace

extern "C" void ui_nav_init(void) {
    for (uint8_t i = 0; i < NAV_MAX_DEPTH; ++i) stack[i] = nullptr;
    depth = 0;
}

extern "C" void ui_nav_push(ui_nav_factory_fn factory) {
    if (factory == nullptr) return;
    if (depth >= NAV_MAX_DEPTH) {
        // At max depth — refuse to push so we never grow unbounded.
        // Caller should pop first. Log when LVGL warnings are on so a
        // misrouted tap doesn't look like an unresponsive UI bug
        // (sourcery on PR #91).
        Serial.println("[ui_nav] push ignored: max depth reached");
        return;
    }
    lv_obj_t* next = factory();
    if (next == nullptr) return;
    stack[depth++] = next;
    lv_scr_load(next);
}

extern "C" void ui_nav_pop(void) {
    if (depth <= 1) {
        // Already at root or empty — no-op.
        return;
    }
    lv_obj_t* current = stack[depth - 1];
    lv_obj_t* previous = stack[depth - 2];
    stack[depth - 1] = nullptr;
    --depth;

    if (previous) {
        lv_scr_load(previous);
    }
    // Defer deletion of the popped screen until LVGL settles — guards
    // against the case where the pop was triggered by a widget event on
    // `current` itself.
    if (current) {
        lv_async_call(async_delete_cb, current);
    }
}

extern "C" bool ui_nav_at_root(void) {
    return depth <= 1;
}

extern "C" uint8_t ui_nav_depth(void) {
    return depth;
}
