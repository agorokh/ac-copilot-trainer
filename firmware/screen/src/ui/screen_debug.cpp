// Hidden debug / diagnostics screen — issue #677 Part C.

#include "ui/screen_debug.h"

#include "ui/app_state.h"
#include "ui/link_stats.h"
#include "ui/nav.h"
#include "ui/persist.h"
#include "ui/tokens.h"

#include <Arduino.h>
#include <new>
#include <stdio.h>

namespace {

constexpr int SCREEN_W = 320;
constexpr int HEADER_H = 40;
constexpr int OUTER_PAD = 12;
constexpr int ROW_H = 22;

struct debug_ctx_t {
    lv_obj_t* link_lbl;
    lv_obj_t* last_lbl;
    lv_obj_t* peers_lbl;
    lv_obj_t* heap_lbl;
    lv_obj_t* frames_lbl;
    lv_obj_t* drop_lbl;
    lv_obj_t* drain_lbl;
    lv_timer_t* poll_timer;
};

const char* link_text(app_state_t s, int linked) {
    if (linked) return "UP";
    switch (s) {
        case APP_BOOTING:       return "BOOTING";
        case APP_DISCONNECTED:  return "DOWN";
        case APP_CONNECTED:
        case APP_LAUNCHER_IDLE: return "CONNECTING";
        default:                return "?";
    }
}

void refresh(debug_ctx_t* ctx) {
    if (!ctx) return;
    const link_stats_t* st = link_stats_get();
    char buf[96];

    snprintf(buf, sizeof(buf), "LINK: %s", link_text(app_state_get(), st->linked));
    lv_label_set_text(ctx->link_lbl, buf);

    if (st->last_frame_ms == 0) {
        snprintf(buf, sizeof(buf), "LAST FRAME: never");
    } else {
        uint32_t age = millis() - st->last_frame_ms;
        snprintf(buf, sizeof(buf), "LAST FRAME: %lu ms ago",
                 static_cast<unsigned long>(age));
    }
    lv_label_set_text(ctx->last_lbl, buf);

    snprintf(buf, sizeof(buf), "PEERS: %u", static_cast<unsigned>(st->peer_count));
    lv_label_set_text(ctx->peers_lbl, buf);

    snprintf(buf, sizeof(buf), "FREE HEAP: %u B (min %u)",
             static_cast<unsigned>(ESP.getFreeHeap()),
             static_cast<unsigned>(ESP.getMinFreeHeap()));
    lv_label_set_text(ctx->heap_lbl, buf);

    snprintf(buf, sizeof(buf), "FRAMES OK: %lu",
             static_cast<unsigned long>(st->frames_ok));
    lv_label_set_text(ctx->frames_lbl, buf);

    snprintf(buf, sizeof(buf), "DROPS: ovf=%lu parse=%lu",
             static_cast<unsigned long>(st->overflow_drops),
             static_cast<unsigned long>(st->parse_drops));
    lv_label_set_text(ctx->drop_lbl, buf);

    snprintf(buf, sizeof(buf), "BP: max_avail=%lu max_drain=%lu ms",
             static_cast<unsigned long>(st->max_rx_available),
             static_cast<unsigned long>(st->max_drain_ms));
    lv_label_set_text(ctx->drain_lbl, buf);
}

void poll_cb(lv_timer_t* t) {
    refresh(static_cast<debug_ctx_t*>(t->user_data));
}

void on_back(lv_event_t*) {
    ui_persist_set_screen(UI_SCREEN_LAUNCHER);
    ui_nav_pop();
}

void on_delete(lv_event_t* e) {
    auto* ctx = static_cast<debug_ctx_t*>(lv_event_get_user_data(e));
    if (!ctx) return;
    if (ctx->poll_timer) {
        lv_timer_del(ctx->poll_timer);
        ctx->poll_timer = nullptr;
    }
    delete ctx;
}

lv_obj_t* make_row(lv_obj_t* parent, int y) {
    lv_obj_t* lbl = lv_label_create(parent);
    lv_obj_set_width(lbl, SCREEN_W - 2 * OUTER_PAD);
    lv_label_set_long_mode(lbl, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_font(lbl, UI_FONT_MONO_SM, LV_PART_MAIN);
    lv_obj_set_style_text_color(lbl, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(lbl, LV_ALIGN_TOP_LEFT, OUTER_PAD, y);
    return lbl;
}

}  // namespace

extern "C" lv_obj_t* screen_debug_create(void) {
    auto* ctx = new (std::nothrow) debug_ctx_t();
    if (!ctx) {
        Serial.println("[fatal][ui] screen_debug ctx alloc failed");
        return nullptr;
    }
    *ctx = debug_ctx_t{};

    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(scr, on_delete, LV_EVENT_DELETE, ctx);

    lv_obj_t* header = lv_obj_create(scr);
    lv_obj_set_size(header, SCREEN_W, HEADER_H);
    lv_obj_align(header, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(header, UI_BG_HEADER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(header, UI_BG_HEADER_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(header, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(header, 0, LV_PART_MAIN);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* title = lv_label_create(header);
    lv_label_set_text(title, "DEBUG");
    lv_obj_set_style_text_font(title, UI_FONT_LABEL_SM, LV_PART_MAIN);
    lv_obj_set_style_text_color(title, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(title, 2, LV_PART_MAIN);
    lv_obj_align(title, LV_ALIGN_LEFT_MID, 12, 0);

    lv_obj_t* back = lv_btn_create(header);
    lv_obj_set_size(back, 92, HEADER_H - 4);
    lv_obj_align(back, LV_ALIGN_RIGHT_MID, -2, 0);
    lv_obj_set_style_bg_color(back, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(back, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(back, UI_RADIUS_TILE, LV_PART_MAIN);
    lv_obj_set_style_border_width(back, 0, LV_PART_MAIN);
    lv_obj_add_event_cb(back, on_back, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* back_lbl = lv_label_create(back);
    lv_label_set_text(back_lbl, "< BACK");
    lv_obj_set_style_text_font(back_lbl, UI_FONT_LABEL_XS, LV_PART_MAIN);
    lv_obj_set_style_text_color(back_lbl, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_center(back_lbl);

    int y = HEADER_H + OUTER_PAD;
    ctx->link_lbl = make_row(scr, y); y += ROW_H;
    ctx->last_lbl = make_row(scr, y); y += ROW_H;
    ctx->peers_lbl = make_row(scr, y); y += ROW_H;
    ctx->heap_lbl = make_row(scr, y); y += ROW_H + 8;
    ctx->frames_lbl = make_row(scr, y); y += ROW_H;
    ctx->drop_lbl = make_row(scr, y); y += ROW_H;
    ctx->drain_lbl = make_row(scr, y);

    lv_obj_t* hint = lv_label_create(scr);
    lv_label_set_text(hint, "Long-press AC LAUNCHER to reopen");
    lv_obj_set_style_text_font(hint, UI_FONT_MONO_XS, LV_PART_MAIN);
    lv_obj_set_style_text_color(hint, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_align(hint, LV_ALIGN_BOTTOM_MID, 0, -OUTER_PAD);

    refresh(ctx);
    ctx->poll_timer = lv_timer_create(poll_cb, 250, ctx);
    return scr;
}
