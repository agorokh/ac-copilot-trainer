// AC Copilot mirror screen — issue #86 Part C.
//
// Layout (rotation=1, 480×320):
//
//   ┌────────────────────────────────────────────────────────────┐  40 px
//   │ AC COPILOT                                  ◀ BACK         │ header
//   ├────────────────────────────────────────────────────────────┤
//   │ ┌─ Alert card ───────────────────────────────────────────┐ │
//   │ │ ● TURN 3 • LESMO 1                                     │ │  80 px
//   │ │ Brake at 100m marker. Trail brake to apex.             │ │
//   │ │ Early throttle helps rotation.                         │ │
//   │ └────────────────────────────────────────────────────────┘ │
//   │ ┌─ Telemetry ───────────────────────────────────────────┐  │
//   │ │ APPROACHING                              TURN 3       │  │
//   │ │ DISTANCE TO BRAKING                       247 M       │  │
//   │ │ ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  35%         │  │
//   │ │ TARGET 142 KM/H        CURRENT 156 KM/H               │  │
//   │ │ TOO FAST +14 KM/H                                     │  │
//   │ └───────────────────────────────────────────────────────┘  │
//   └────────────────────────────────────────────────────────────┘
//
// The dedicated BACK chevron in the header is the discoverable affordance.
// Subscribes to `state.snapshot topic="coaching.snapshot"` (10 Hz from the
// trainer) plus the older `corner_advice` event for richer LLM hints.
//
// `screen_ac_copilot_apply_snapshot()` (called from `main.cpp`'s WS dispatch)
// updates a static cache and queues an `lv_async_call` redraw against the
// currently active ctx — see `g_active_ctx` below. If the screen is not the
// active one, the cache update is enough; the next push of the screen
// renders from cache.

#include "ui/screen_ac_copilot.h"

#include "ui/nav.h"
#include "ui/tokens.h"

#include <Arduino.h>
#include <stdio.h>
#include <string.h>
#include <new>

namespace {

// Module-static snapshot + LLM advice cache. Owned by this module so the
// screen is self-contained; main.cpp talks to us only through the public
// `apply_snapshot` / `apply_corner_advice` setters.
coaching_snapshot_t g_snap = {};
char                g_advice_corner[32]  = {0};
char                g_advice_text[160]   = {0};

// --- Per-screen widget cache ------------------------------------------------

struct ac_copilot_ctx_t {
    lv_obj_t* alert_meta_label;     // "TURN 3 • LESMO 1"
    lv_obj_t* alert_primary;        // primary_line
    lv_obj_t* alert_secondary;      // secondary_line (or LLM advice override)
    lv_obj_t* approaching_corner;   // big "TURN 3" on right
    lv_obj_t* dist_value;           // "247 M"
    lv_obj_t* dist_bar;             // progress bar
    lv_obj_t* target_value;         // "142 KM/H"
    lv_obj_t* current_value;        // "156 KM/H"
    lv_obj_t* delta_chip;           // "TOO FAST +14" / "ON PACE"
};

// One singleton so async refresh doesn't have to search the LVGL tree.
// Set in create(), cleared in on_screen_delete(). Stale-pointer-safe
// because LV_EVENT_DELETE always fires before LVGL frees the screen.
ac_copilot_ctx_t* g_active_ctx = nullptr;

// --- Helpers ---------------------------------------------------------------

// Portrait 320×480 (device mounted vertical).
constexpr int SCREEN_W   = 320;
constexpr int SCREEN_H   = 480;
constexpr int HEADER_H   = 40;
constexpr int CARD_PAD   = 12;
constexpr int OUTER_PAD  = 12;
constexpr int ALERT_H    = 110;   // taller in portrait so 2 wrap-lines fit
constexpr int CARD_GAP   = 8;

void on_back_clicked(lv_event_t*) {
    ui_nav_pop();
}

void apply_to_widgets(ac_copilot_ctx_t* ctx) {
    if (!ctx) return;
    const coaching_snapshot_t& s = g_snap;

    if (ctx->alert_meta_label) {
        lv_label_set_text(ctx->alert_meta_label,
                          s.corner_label[0] ? s.corner_label : "-");
    }

    // LLM advice override on the secondary line — only when the cached
    // advice corner matches the current snapshot's corner. The trainer
    // already enforces the 6 s sim-time TTL (see ws_bridge.takeCornerAdvisory),
    // so the screen just renders whatever it last received.
    const char* secondary = s.secondary_line;
    if (g_advice_text[0] != 0 && g_advice_corner[0] != 0
        && s.corner_label[0] != 0
        && strncmp(g_advice_corner, s.corner_label, sizeof(g_advice_corner)) == 0) {
        secondary = g_advice_text;
    }

    if (ctx->alert_primary) {
        lv_label_set_text(ctx->alert_primary,
                          s.primary_line[0] ? s.primary_line : "");
    }
    if (ctx->alert_secondary) {
        lv_label_set_text(ctx->alert_secondary,
                          (secondary && secondary[0]) ? secondary : "");
    }

    if (ctx->approaching_corner) {
        lv_label_set_text(ctx->approaching_corner,
                          s.corner_label[0] ? s.corner_label : "-");
    }

    char buf[40];
    if (ctx->dist_value) {
        if (s.dist_to_brake_m >= 0) {
            snprintf(buf, sizeof(buf), "%d M", (int)s.dist_to_brake_m);
        } else {
            snprintf(buf, sizeof(buf), "-");
        }
        lv_label_set_text(ctx->dist_value, buf);
    }

    if (ctx->dist_bar) {
        int p = s.progress_pct;
        if (p < 0) p = 0;
        if (p > 100) p = 100;
        lv_bar_set_value(ctx->dist_bar, p, LV_ANIM_OFF);
    }

    if (ctx->target_value) {
        if (s.target_speed_kmh > 0) {
            snprintf(buf, sizeof(buf), "%d KM/H", (int)s.target_speed_kmh);
        } else {
            snprintf(buf, sizeof(buf), "-");
        }
        lv_label_set_text(ctx->target_value, buf);
    }

    if (ctx->current_value) {
        if (s.current_speed_kmh >= 0) {
            snprintf(buf, sizeof(buf), "%d KM/H", (int)s.current_speed_kmh);
        } else {
            snprintf(buf, sizeof(buf), "-");
        }
        lv_label_set_text(ctx->current_value, buf);
        // CURRENT goes red when current > target + 8 (issue #86 C2).
        const bool too_fast = (s.target_speed_kmh > 0
                               && s.current_speed_kmh > s.target_speed_kmh + 8);
        lv_obj_set_style_text_color(
            ctx->current_value,
            too_fast ? UI_ALERT_RED : UI_TX_PRIMARY,
            LV_PART_MAIN);
    }

    if (ctx->delta_chip) {
        if (s.target_speed_kmh > 0 && s.current_speed_kmh >= 0) {
            int delta = s.current_speed_kmh - s.target_speed_kmh;
            if (delta > 8) {
                snprintf(buf, sizeof(buf), "TOO FAST +%d KM/H", delta);
                lv_label_set_text(ctx->delta_chip, buf);
                lv_obj_set_style_text_color(ctx->delta_chip, UI_ALERT_RED, LV_PART_MAIN);
                lv_obj_clear_flag(ctx->delta_chip, LV_OBJ_FLAG_HIDDEN);
            } else if (delta <= 0) {
                lv_label_set_text(ctx->delta_chip, "ON PACE");
                lv_obj_set_style_text_color(ctx->delta_chip, UI_OK_GREEN, LV_PART_MAIN);
                lv_obj_clear_flag(ctx->delta_chip, LV_OBJ_FLAG_HIDDEN);
            } else {
                // Within tolerance — hide chip per Part C2.
                lv_obj_add_flag(ctx->delta_chip, LV_OBJ_FLAG_HIDDEN);
            }
        } else {
            lv_obj_add_flag(ctx->delta_chip, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

// `lv_async_call` callback — runs from the LVGL idle, so widget mutations
// here are safe even if the trigger came from the WS dispatch context.
void async_refresh_cb(void* user) {
    auto* ctx = static_cast<ac_copilot_ctx_t*>(user);
    // Re-check g_active_ctx — the screen could have been popped between
    // the async_call enqueue and this callback firing. Comparing pointers
    // is safe because g_active_ctx is cleared synchronously in
    // on_screen_delete (LV_EVENT_DELETE fires before lv_async_call drains).
    if (ctx == nullptr || ctx != g_active_ctx) return;
    apply_to_widgets(ctx);
}

void on_screen_delete(lv_event_t* e) {
    auto* ctx = static_cast<ac_copilot_ctx_t*>(lv_event_get_user_data(e));
    if (ctx == g_active_ctx) {
        g_active_ctx = nullptr;
    }
    if (ctx) {
        delete ctx;
    }
}

}  // namespace

extern "C" lv_obj_t* screen_ac_copilot_create(void) {
    auto* ctx = new (std::nothrow) ac_copilot_ctx_t();
    if (!ctx) {
        Serial.println("[fatal][ui] screen_ac_copilot ctx alloc failed");
        return nullptr;
    }

    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(scr, on_screen_delete, LV_EVENT_DELETE, ctx);

    // ---- Header ------------------------------------------------------------
    lv_obj_t* header = lv_obj_create(scr);
    lv_obj_set_size(header, SCREEN_W, HEADER_H);
    lv_obj_align(header, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(header, UI_BG_HEADER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(header, UI_BG_HEADER_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(header, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(header, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_left(header, 12, LV_PART_MAIN);
    lv_obj_set_style_pad_right(header, 12, LV_PART_MAIN);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* title = lv_label_create(header);
    lv_label_set_text(title, "AC COPILOT");
    lv_obj_set_style_text_color(title, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(title, 2, LV_PART_MAIN);
    lv_obj_align(title, LV_ALIGN_LEFT_MID, 0, 0);

    lv_obj_t* back = lv_btn_create(header);
    lv_obj_set_size(back, 100, HEADER_H - 4);
    lv_obj_align(back, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_set_style_bg_color(back, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(back, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_width(back, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(back, 6, LV_PART_MAIN);
    lv_obj_add_event_cb(back, on_back_clicked, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* back_lbl = lv_label_create(back);
    lv_label_set_text(back_lbl, "< BACK");
    lv_obj_set_style_text_color(back_lbl, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_center(back_lbl);

    // ---- Alert card --------------------------------------------------------
    lv_obj_t* alert = lv_obj_create(scr);
    lv_obj_set_size(alert, SCREEN_W - 2 * OUTER_PAD, ALERT_H);
    lv_obj_align(alert, LV_ALIGN_TOP_MID, 0, HEADER_H + CARD_GAP);
    lv_obj_set_style_bg_color(alert, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(alert, UI_BG_PANEL_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_color(alert, UI_BORDER_ALERT, LV_PART_MAIN);
    lv_obj_set_style_border_opa(alert, UI_BORDER_ALERT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(alert, 1, LV_PART_MAIN);
    lv_obj_set_style_radius(alert, UI_RADIUS_TILE, LV_PART_MAIN);
    lv_obj_set_style_pad_all(alert, CARD_PAD, LV_PART_MAIN);
    lv_obj_clear_flag(alert, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* dot = lv_obj_create(alert);
    lv_obj_set_size(dot, 8, 8);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, LV_PART_MAIN);
    lv_obj_set_style_bg_color(dot, UI_ALERT_RED, LV_PART_MAIN);
    lv_obj_set_style_border_width(dot, 0, LV_PART_MAIN);
    lv_obj_align(dot, LV_ALIGN_TOP_LEFT, 0, 4);

    ctx->alert_meta_label = lv_label_create(alert);
    lv_obj_align(ctx->alert_meta_label, LV_ALIGN_TOP_LEFT, 16, 0);
    lv_obj_set_style_text_color(ctx->alert_meta_label, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->alert_meta_label, 1, LV_PART_MAIN);
    lv_label_set_text(ctx->alert_meta_label, "-");

    ctx->alert_primary = lv_label_create(alert);
    lv_obj_align(ctx->alert_primary, LV_ALIGN_TOP_LEFT, 0, 22);
    lv_obj_set_width(ctx->alert_primary, SCREEN_W - 2 * OUTER_PAD - 2 * CARD_PAD);
    lv_label_set_long_mode(ctx->alert_primary, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_color(ctx->alert_primary, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_label_set_text(ctx->alert_primary, "WAITING FOR DATA");

    ctx->alert_secondary = lv_label_create(alert);
    lv_obj_align(ctx->alert_secondary, LV_ALIGN_TOP_LEFT, 0, 44);
    lv_obj_set_width(ctx->alert_secondary, SCREEN_W - 2 * OUTER_PAD - 2 * CARD_PAD);
    lv_label_set_long_mode(ctx->alert_secondary, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_color(ctx->alert_secondary, UI_TX_MUTED, LV_PART_MAIN);
    lv_label_set_text(ctx->alert_secondary, "Drive a lap with the trainer running to populate this screen");

    // ---- Telemetry panel ---------------------------------------------------
    const int tele_y = HEADER_H + CARD_GAP + ALERT_H + CARD_GAP;
    lv_obj_t* tele = lv_obj_create(scr);
    lv_obj_set_size(tele, SCREEN_W - 2 * OUTER_PAD,
                    SCREEN_H - tele_y - CARD_GAP);
    lv_obj_align(tele, LV_ALIGN_TOP_MID, 0, tele_y);
    lv_obj_set_style_bg_color(tele, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(tele, UI_BG_PANEL_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_color(tele, UI_BORDER_SOFT, LV_PART_MAIN);
    lv_obj_set_style_border_opa(tele, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(tele, 1, LV_PART_MAIN);
    lv_obj_set_style_radius(tele, UI_RADIUS_TILE, LV_PART_MAIN);
    lv_obj_set_style_pad_all(tele, CARD_PAD, LV_PART_MAIN);
    lv_obj_clear_flag(tele, LV_OBJ_FLAG_SCROLLABLE);

    // APPROACHING + corner big text
    lv_obj_t* approaching_lbl = lv_label_create(tele);
    lv_label_set_text(approaching_lbl, "APPROACHING");
    lv_obj_set_style_text_color(approaching_lbl, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(approaching_lbl, 2, LV_PART_MAIN);
    lv_obj_align(approaching_lbl, LV_ALIGN_TOP_LEFT, 0, 0);

    ctx->approaching_corner = lv_label_create(tele);
    lv_obj_set_style_text_color(ctx->approaching_corner, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->approaching_corner, 2, LV_PART_MAIN);
    lv_obj_align(ctx->approaching_corner, LV_ALIGN_TOP_RIGHT, 0, 0);
    lv_label_set_text(ctx->approaching_corner, "-");

    // DISTANCE TO BRAKING + value + bar
    lv_obj_t* dist_lbl = lv_label_create(tele);
    lv_label_set_text(dist_lbl, "DISTANCE TO BRAKING");
    lv_obj_set_style_text_color(dist_lbl, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(dist_lbl, 1, LV_PART_MAIN);
    lv_obj_align(dist_lbl, LV_ALIGN_TOP_LEFT, 0, 32);

    ctx->dist_value = lv_label_create(tele);
    lv_obj_set_style_text_color(ctx->dist_value, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->dist_value, 1, LV_PART_MAIN);
    lv_obj_align(ctx->dist_value, LV_ALIGN_TOP_RIGHT, 0, 32);
    lv_label_set_text(ctx->dist_value, "-");

    ctx->dist_bar = lv_bar_create(tele);
    lv_obj_set_size(ctx->dist_bar, SCREEN_W - 2 * OUTER_PAD - 2 * CARD_PAD, 4);
    lv_obj_align(ctx->dist_bar, LV_ALIGN_TOP_LEFT, 0, 56);
    lv_bar_set_range(ctx->dist_bar, 0, 100);
    lv_bar_set_value(ctx->dist_bar, 0, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(ctx->dist_bar, UI_BG_HEADER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(ctx->dist_bar, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_bg_color(ctx->dist_bar, UI_ACCENT_GOLD, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(ctx->dist_bar, LV_OPA_COVER, LV_PART_INDICATOR);

    // TARGET / CURRENT — stacked vertically in portrait (no room for the
    // two-column landscape layout at 320px wide). LABEL on the left, value
    // on the right of the same row. CURRENT directly below TARGET.
    lv_obj_t* target_lbl = lv_label_create(tele);
    lv_label_set_text(target_lbl, "TARGET");
    lv_obj_set_style_text_color(target_lbl, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(target_lbl, 1, LV_PART_MAIN);
    lv_obj_align(target_lbl, LV_ALIGN_TOP_LEFT, 0, 76);

    ctx->target_value = lv_label_create(tele);
    lv_obj_set_style_text_color(ctx->target_value, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->target_value, 1, LV_PART_MAIN);
    lv_obj_align(ctx->target_value, LV_ALIGN_TOP_RIGHT, 0, 76);
    lv_label_set_text(ctx->target_value, "-");

    lv_obj_t* current_lbl = lv_label_create(tele);
    lv_label_set_text(current_lbl, "CURRENT");
    lv_obj_set_style_text_color(current_lbl, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(current_lbl, 1, LV_PART_MAIN);
    lv_obj_align(current_lbl, LV_ALIGN_TOP_LEFT, 0, 100);

    ctx->current_value = lv_label_create(tele);
    lv_obj_set_style_text_color(ctx->current_value, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->current_value, 1, LV_PART_MAIN);
    lv_obj_align(ctx->current_value, LV_ALIGN_TOP_RIGHT, 0, 100);
    lv_label_set_text(ctx->current_value, "-");

    // Delta chip (bottom)
    ctx->delta_chip = lv_label_create(tele);
    lv_obj_set_style_text_color(ctx->delta_chip, UI_OK_GREEN, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->delta_chip, 1, LV_PART_MAIN);
    lv_obj_align(ctx->delta_chip, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    lv_label_set_text(ctx->delta_chip, "");
    lv_obj_add_flag(ctx->delta_chip, LV_OBJ_FLAG_HIDDEN);

    // Register as the active ctx so apply_snapshot() / apply_corner_advice()
    // can push live updates without searching the LVGL tree. Two AC Copilot
    // screens cannot exist concurrently because nav max depth is 2 and
    // launcher always sits at depth 0 — but defensively replace any prior
    // pointer (we own the new one anyway).
    g_active_ctx = ctx;
    if (g_snap.has_data) {
        apply_to_widgets(ctx);
    }

    return scr;
}

extern "C" void screen_ac_copilot_apply_snapshot(const coaching_snapshot_t* snap) {
    if (!snap) return;
    g_snap = *snap;
    g_snap.has_data = true;
    if (g_active_ctx) {
        // Defer widget mutation to LVGL idle so the WS dispatch path
        // doesn't have to hold any LVGL invariants. Idempotent if the
        // user pops the screen between enqueue and fire — see
        // async_refresh_cb's pointer check.
        lv_async_call(async_refresh_cb, g_active_ctx);
    }
}

extern "C" void screen_ac_copilot_apply_corner_advice(const char* corner_id, const char* text) {
    if (corner_id == nullptr) {
        g_advice_corner[0] = 0;
        g_advice_text[0]   = 0;
    } else {
        strncpy(g_advice_corner, corner_id, sizeof(g_advice_corner) - 1);
        g_advice_corner[sizeof(g_advice_corner) - 1] = 0;
        if (text) {
            strncpy(g_advice_text, text, sizeof(g_advice_text) - 1);
            g_advice_text[sizeof(g_advice_text) - 1] = 0;
        } else {
            g_advice_text[0] = 0;
        }
    }
    if (g_active_ctx) {
        lv_async_call(async_refresh_cb, g_active_ctx);
    }
}
