// Launcher screen — issue #86 Part B (stub only in Part A).
//
// This file ships a placeholder so the Part-A LVGL bring-up has a real
// screen to load through `ui_nav_push(launcher_create)`. Part B will
// replace the body with the Menu.tsx port (3 app tiles + connection
// status pill); the factory signature stays the same.

#include "ui/screen_launcher.h"

#include "ui/tokens.h"

extern "C" lv_obj_t* launcher_create(void) {
    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* label = lv_label_create(scr);
    lv_label_set_text(label, "Launcher (Phase 2 stub)\nPart B will replace this.");
    lv_obj_set_style_text_color(label, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
    lv_obj_center(label);

    return scr;
}
