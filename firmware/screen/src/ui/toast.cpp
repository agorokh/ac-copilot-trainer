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

void toast_delete_cb(lv_timer_t* t) {
    lv_obj_t* obj = static_cast<lv_obj_t*>(t->user_data);
    if (obj) {
        lv_obj_del(obj);
    }
    lv_timer_del(t);
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
    lv_timer_t* t = lv_timer_create(toast_delete_cb, ms_visible, toast);
    lv_timer_set_repeat_count(t, 1);
}

extern "C" void ui_toast_error(const char* text) {
    ui_toast_show(text, 3000);
}
