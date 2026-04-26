// Toast singleton — issue #86 Part D6.

#include "ui/toast.h"
#include "ui/tokens.h"

#include <Arduino.h>

namespace {

constexpr int TOAST_H        = 36;
constexpr int TOAST_PAD_X    = 16;
constexpr int TOAST_BOTTOM_OFFSET = 8;

// Per-screen toast — we deliberately do NOT hold a static cross-screen
// pointer because `ui_nav_pop()` deletes the previous screen and would
// invalidate any cached widget. Each call creates a fresh toast on the
// currently active screen and arms a one-shot timer to delete it.
//
// Lifetime invariant (Cursor / CodeRabbit on PR #91): when LVGL deletes
// the toast — either because its timer fired naturally OR because the
// parent screen was popped before the timer fired — we must cancel the
// pending timer so it does not later fire on a freed object. We hook
// `LV_EVENT_DELETE` on the toast to do exactly this. A pointer to the
// timer is stashed in the toast's `user_data` field; the deletion-event
// callback reads it, deletes the timer, and clears the field. The timer
// callback in turn nulls its own `user_data` on the toast first so the
// deletion callback (triggered by `lv_obj_del`) becomes a no-op.

void toast_timer_cb(lv_timer_t* t) {
    lv_obj_t* obj = static_cast<lv_obj_t*>(t->user_data);
    if (obj) {
        // Detach so the LV_EVENT_DELETE handler does not double-delete the
        // timer when LVGL recursively deletes the toast.
        lv_obj_set_user_data(obj, nullptr);
        lv_obj_del(obj);
    }
    // The timer is one-shot; LVGL does not auto-delete it after the call,
    // so we must explicitly remove it here. Safe because we are returning
    // to LVGL's own timer dispatch loop.
    lv_timer_del(t);
}

void toast_obj_delete_cb(lv_event_t* e) {
    auto* obj = lv_event_get_target(e);
    if (obj == nullptr) return;
    auto* t = static_cast<lv_timer_t*>(lv_obj_get_user_data(obj));
    if (t != nullptr) {
        lv_obj_set_user_data(obj, nullptr);
        lv_timer_del(t);
    }
}

}  // namespace

extern "C" void ui_toast_show(const char* text, uint32_t ms_visible) {
    if (text == nullptr) return;
    lv_obj_t* scr = lv_scr_act();
    if (scr == nullptr) return;

    lv_obj_t* toast = lv_obj_create(scr);
    lv_obj_set_size(toast, lv_pct(96), TOAST_H);
    lv_obj_align(toast, LV_ALIGN_BOTTOM_MID, 0, -TOAST_BOTTOM_OFFSET);
    lv_obj_set_style_bg_color(toast, UI_ALERT_RED, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(toast, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_width(toast, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(toast, 6, LV_PART_MAIN);
    lv_obj_set_style_pad_left(toast, TOAST_PAD_X, LV_PART_MAIN);
    lv_obj_set_style_pad_right(toast, TOAST_PAD_X, LV_PART_MAIN);
    lv_obj_set_style_pad_top(toast, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_bottom(toast, 0, LV_PART_MAIN);
    lv_obj_clear_flag(toast, LV_OBJ_FLAG_SCROLLABLE);
    // Toast stays above the rest of the screen even when the screen is
    // scrollable (Pocket Technician's setup list).
    lv_obj_move_foreground(toast);

    lv_obj_t* lbl = lv_label_create(toast);
    lv_label_set_text(lbl, text);
    lv_obj_set_style_text_color(lbl, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(lbl, LV_ALIGN_LEFT_MID, 0, 0);

    if (ms_visible == 0) {
        ms_visible = 3000;
    }
    lv_timer_t* t = lv_timer_create(toast_timer_cb, ms_visible, toast);
    lv_timer_set_repeat_count(t, 1);
    // Cross-link toast <-> timer so navigation-induced deletes cancel the
    // pending fire (use-after-free guard, reported by Cursor + CodeRabbit
    // on PR #91).
    lv_obj_set_user_data(toast, t);
    lv_obj_add_event_cb(toast, toast_obj_delete_cb, LV_EVENT_DELETE, nullptr);
}

extern "C" void ui_toast_error(const char* text) {
    ui_toast_show(text, 3000);
}
