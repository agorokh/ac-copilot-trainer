// AC Copilot mirror screen -- issue #86 Part C/F.
//
// Racing Atelier rig-screen pass: carbon ground, brass structure, a single
// command, LVGL-drawn segment cells, and a signed delta block. The public
// snapshot API is unchanged; this file only changes how cached coaching state
// is rendered on the JC3248W535.

#include "ui/screen_ac_copilot.h"

#include "ui/nav.h"
#include "ui/tokens.h"

#include <Arduino.h>
#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <new>

namespace {

coaching_snapshot_t g_snap = {};
char                g_advice_corner[32] = {0};
char                g_advice_text[160] = {0};
uint32_t            g_last_snapshot_ms = 0;

constexpr int SCREEN_W = 320;
constexpr int SCREEN_H = 480;
constexpr int HEADER_H = 28;
constexpr int FOOTER_H = 36;
constexpr int PAD = 13;
constexpr int SEGMENT_COUNT = 12;
constexpr uint32_t SNAPSHOT_STALE_MS = 3000;

struct ac_copilot_ctx_t {
    lv_obj_t* status_dot;
    lv_obj_t* status_label;
    lv_obj_t* mode_label;
    lv_obj_t* corner_badge;
    lv_obj_t* corner_label;
    lv_obj_t* current_speed;
    lv_obj_t* command_label;
    lv_obj_t* command_marker;
    lv_obj_t* brake_distance;
    lv_obj_t* brake_unit;
    lv_obj_t* segment_cells[SEGMENT_COUNT];
    lv_obj_t* delta_fill;
    lv_obj_t* delta_value;
    lv_obj_t* delta_meta;
    lv_obj_t* advice_delta;
    lv_obj_t* advice_text;
    lv_timer_t* stale_timer;
};

ac_copilot_ctx_t* g_active_ctx = nullptr;

void uppercase_copy(const char* src, char* dst, size_t n) {
    if (!dst || n == 0) return;
    if (!src) {
        dst[0] = 0;
        return;
    }
    size_t i = 0;
    for (; src[i] && i < n - 1; ++i) {
        unsigned char c = static_cast<unsigned char>(src[i]);
        dst[i] = static_cast<char>(toupper(c));
    }
    dst[i] = 0;
}

bool contains_ascii(const char* haystack, const char* needle) {
    if (!haystack || !needle || !*needle) return false;
    // Case-insensitive substring scan over the full strings — no fixed-size
    // copy, so keywords are still found past the old 48-char buffer (e.g.
    // "brake"/"lift" late in the 96-char primary_line).
    for (const char* h = haystack; *h; ++h) {
        const char* hp = h;
        const char* np = needle;
        while (*hp && *np &&
               toupper((unsigned char)*hp) == toupper((unsigned char)*np)) {
            ++hp;
            ++np;
        }
        if (!*np) return true;
    }
    return false;
}

bool snapshot_is_stale() {
    // `!has_data` already covers "no snapshot yet"; a separate
    // `g_last_snapshot_ms == 0` guard would wedge staleness off forever if the
    // first snapshot happened to land at millis() == 0 right after boot.
    if (!g_snap.has_data) return false;
    return (uint32_t)(millis() - g_last_snapshot_ms) > SNAPSHOT_STALE_MS;
}

const char* command_for_snapshot(bool stale) {
    if (!g_snap.has_data) return "WAIT";
    if (stale) return "STALE";
    if (contains_ascii(g_snap.kind, "brake") ||
        contains_ascii(g_snap.primary_line, "brake")) {
        return "BRAKE";
    }
    if (contains_ascii(g_snap.primary_line, "lift") ||
        contains_ascii(g_snap.kind, "line")) {
        return "LIFT";
    }
    if (g_snap.target_speed_kmh > 0 && g_snap.current_speed_kmh >= 0) {
        int32_t delta = g_snap.current_speed_kmh - g_snap.target_speed_kmh;
        if (delta > 8) return "BRAKE";
        if (delta <= 0) return "CLEAR";
    }
    if (contains_ascii(g_snap.kind, "info")) return "INFO";
    return "HOLD";
}

lv_color_t command_color(const char* command) {
    if (strcmp(command, "BRAKE") == 0 || strcmp(command, "STALE") == 0) {
        return UI_ALERT_RED;
    }
    if (strcmp(command, "LIFT") == 0 || strcmp(command, "WAIT") == 0) {
        return UI_LINE_AMBER;
    }
    if (strcmp(command, "CLEAR") == 0) {
        return UI_OK_GREEN;
    }
    return UI_DATA_CYAN;
}

void corner_badge_text(const char* corner, char* out, size_t n) {
    if (!out || n == 0) return;
    out[0] = 0;
    if (!corner || !*corner) {
        snprintf(out, n, "T-");
        return;
    }
    // Prefer digits after an explicit T/t marker ("T3", "T10"); otherwise fall
    // back to the first digit run anywhere in the label so descriptive corner
    // names ("Lesmo 1") still surface a number instead of "T?".
    const char* t = strchr(corner, 'T');
    if (!t) t = strchr(corner, 't');
    const char* d = (t && t[1] >= '0' && t[1] <= '9') ? t + 1 : nullptr;
    if (!d) {
        for (const char* p = corner; *p; ++p) {
            if (*p >= '0' && *p <= '9') {
                d = p;
                break;
            }
        }
    }
    if (d) {
        // Copy "T" + the full consecutive digit run so "T10"/"T12" do not
        // collapse to "T1" (single-digit copy misreports the corner).
        size_t w = 0;
        if (n > 1) out[w++] = 'T';
        for (; *d >= '0' && *d <= '9' && w + 1 < n; ++d) {
            out[w++] = *d;
        }
        out[w] = 0;
        return;
    }
    snprintf(out, n, "T?");
}

void set_label(lv_obj_t* obj, const char* text) {
    if (obj) lv_label_set_text(obj, text ? text : "");
}

void style_label(lv_obj_t* obj, const lv_font_t* font, lv_color_t color) {
    lv_obj_set_style_text_font(obj, font, LV_PART_MAIN);
    lv_obj_set_style_text_color(obj, color, LV_PART_MAIN);
}

lv_obj_t* make_line(lv_obj_t* parent, int y) {
    lv_obj_t* line = lv_obj_create(parent);
    lv_obj_set_size(line, SCREEN_W - 2 * PAD, 1);
    lv_obj_set_pos(line, PAD, y);
    lv_obj_set_style_bg_color(line, UI_BORDER_SOFT, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(line, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(line, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(line, 0, LV_PART_MAIN);
    lv_obj_clear_flag(line, LV_OBJ_FLAG_SCROLLABLE);
    return line;
}

lv_obj_t* make_label(lv_obj_t* parent, const char* text, const lv_font_t* font,
                     lv_color_t color, int x, int y, int w) {
    lv_obj_t* label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_font(label, font, LV_PART_MAIN);
    lv_obj_set_style_text_color(label, color, LV_PART_MAIN);
    if (w > 0) {
        lv_obj_set_width(label, w);
        lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
    }
    lv_obj_set_pos(label, x, y);
    return label;
}

void on_back_clicked(lv_event_t*) {
    ui_nav_pop();
}

void update_segments(ac_copilot_ctx_t* ctx, bool stale) {
    if (!ctx) return;
    int progress = g_snap.has_data ? g_snap.progress_pct : 0;
    if (progress < 0) progress = 0;
    if (progress > 100) progress = 100;
    int lit = (progress * SEGMENT_COUNT + 99) / 100;
    if (!g_snap.has_data || stale) lit = 0;
    const int zone_start = 8;
    for (int i = 0; i < SEGMENT_COUNT; ++i) {
        lv_color_t color = UI_BG_RAISE;
        if (i < lit) {
            color = (i >= zone_start) ? UI_ALERT_RED : UI_TX_PRIMARY;
        } else if (i == lit && g_snap.has_data && !stale) {
            color = UI_LINE_AMBER;
        } else if (i >= zone_start) {
            color = lv_color_hex(0x2A0D0A);
        }
        lv_obj_set_style_bg_color(ctx->segment_cells[i], color, LV_PART_MAIN);
    }
}

void update_delta(ac_copilot_ctx_t* ctx, bool stale) {
    if (!ctx) return;
    const int trough_x = PAD;
    const int trough_y = 312;
    const int trough_w = SCREEN_W - 2 * PAD - 104;
    const int center_x = trough_x + trough_w / 2;
    const int max_w = trough_w / 2;

    if (!g_snap.has_data || stale ||
        g_snap.target_speed_kmh <= 0 || g_snap.current_speed_kmh < 0) {
        lv_obj_add_flag(ctx->delta_fill, LV_OBJ_FLAG_HIDDEN);
        set_label(ctx->delta_value, "--");
        set_label(ctx->delta_meta, "ENTRY D - REF --");
        return;
    }

    int32_t delta = g_snap.current_speed_kmh - g_snap.target_speed_kmh;
    int32_t capped = delta;
    if (capped > 20) capped = 20;
    if (capped < -20) capped = -20;
    int width = (abs(capped) * max_w) / 20;
    if (width < 3) width = 3;
    // Positive delta grows right of center, negative grows left. An exact
    // zero (current == target) straddles the center line so an on-target
    // reading does not lean right and imply a positive delta.
    int x = capped > 0 ? center_x
          : capped < 0 ? center_x - width
                       : center_x - width / 2;
    lv_obj_set_pos(ctx->delta_fill, x, trough_y);
    lv_obj_set_size(ctx->delta_fill, width, 20);
    lv_obj_set_style_bg_color(ctx->delta_fill,
                              delta > 8 ? UI_ALERT_RED :
                              delta <= 0 ? UI_OK_GREEN : UI_LINE_AMBER,
                              LV_PART_MAIN);
    lv_obj_clear_flag(ctx->delta_fill, LV_OBJ_FLAG_HIDDEN);

    char buf[32];
    snprintf(buf, sizeof(buf), "%+ld", (long)delta);
    set_label(ctx->delta_value, buf);
    lv_obj_set_style_text_color(ctx->delta_value,
                                delta > 8 ? UI_ALERT_RED :
                                delta <= 0 ? UI_OK_GREEN : UI_LINE_AMBER,
                                LV_PART_MAIN);
    snprintf(buf, sizeof(buf), "ENTRY D - REF %ld", (long)g_snap.target_speed_kmh);
    set_label(ctx->delta_meta, buf);
}

void apply_to_widgets(ac_copilot_ctx_t* ctx) {
    if (!ctx) return;
    const bool stale = snapshot_is_stale();
    const char* command = command_for_snapshot(stale);
    lv_color_t cmd_color = command_color(command);

    const bool live = g_snap.has_data && !stale;
    lv_obj_set_style_bg_color(ctx->status_dot,
                              live ? UI_OK_GREEN : (g_snap.has_data ? UI_LINE_AMBER : UI_TX_FAINT),
                              LV_PART_MAIN);
    set_label(ctx->status_label, live ? "LIVE" : (g_snap.has_data ? "STALE" : "WAITING"));
    lv_obj_set_style_text_color(ctx->status_label,
                                live ? UI_OK_GREEN : (g_snap.has_data ? UI_LINE_AMBER : UI_TX_QUIET),
                                LV_PART_MAIN);

    char buf[96];
    if (g_snap.sub_state[0]) uppercase_copy(g_snap.sub_state, buf, sizeof(buf));
    else snprintf(buf, sizeof(buf), "AC COPILOT");
    set_label(ctx->mode_label, buf);

    corner_badge_text(g_snap.corner_label, buf, sizeof(buf));
    set_label(ctx->corner_badge, buf);

    if (g_snap.corner_label[0]) uppercase_copy(g_snap.corner_label, buf, sizeof(buf));
    else snprintf(buf, sizeof(buf), "--");
    set_label(ctx->corner_label, buf);

    if (g_snap.current_speed_kmh >= 0 && !stale) {
        snprintf(buf, sizeof(buf), "%ld", (long)g_snap.current_speed_kmh);
    } else {
        snprintf(buf, sizeof(buf), "--");
    }
    set_label(ctx->current_speed, buf);

    set_label(ctx->command_label, command);
    lv_obj_set_style_text_color(ctx->command_label, cmd_color, LV_PART_MAIN);
    lv_obj_set_style_text_color(ctx->command_marker, cmd_color, LV_PART_MAIN);

    if (g_snap.dist_to_brake_m >= 0 && !stale) {
        snprintf(buf, sizeof(buf), "%ld", (long)g_snap.dist_to_brake_m);
    } else {
        snprintf(buf, sizeof(buf), "--");
    }
    set_label(ctx->brake_distance, buf);
    lv_obj_set_style_text_color(ctx->brake_distance,
                                g_snap.has_data && !stale ? UI_TX_PRIMARY : UI_TX_FAINT,
                                LV_PART_MAIN);
    lv_obj_set_style_text_color(ctx->brake_unit,
                                g_snap.has_data && !stale ? UI_TX_MUTED : UI_TX_FAINT,
                                LV_PART_MAIN);

    update_segments(ctx, stale);
    update_delta(ctx, stale);

    const char* advice = g_snap.secondary_line;
    if (g_advice_text[0] && g_advice_corner[0] && g_snap.corner_label[0] &&
        strncmp(g_advice_corner, g_snap.corner_label, sizeof(g_advice_corner)) == 0) {
        advice = g_advice_text;
    }
    if (!g_snap.has_data) {
        set_label(ctx->advice_delta, "--");
        set_label(ctx->advice_text, "waiting for coaching snapshot");
    } else if (stale) {
        set_label(ctx->advice_delta, "stale");
        set_label(ctx->advice_text, "no fresh sidecar data");
    } else {
        set_label(ctx->advice_delta, g_snap.primary_line[0] ? g_snap.primary_line : "live");
        set_label(ctx->advice_text, advice && advice[0] ? advice : "hold the line");
    }
}

void stale_timer_cb(lv_timer_t* t) {
    auto* ctx = static_cast<ac_copilot_ctx_t*>(t->user_data);
    if (ctx == g_active_ctx) apply_to_widgets(ctx);
}

void async_refresh_cb(void* user) {
    auto* ctx = static_cast<ac_copilot_ctx_t*>(user);
    if (ctx == g_active_ctx) apply_to_widgets(ctx);
}

void on_screen_delete(lv_event_t* e) {
    auto* ctx = static_cast<ac_copilot_ctx_t*>(lv_event_get_user_data(e));
    if (ctx == g_active_ctx) g_active_ctx = nullptr;
    if (ctx) {
        if (ctx->stale_timer) lv_timer_del(ctx->stale_timer);
        delete ctx;
    }
}

void build_segments(lv_obj_t* scr, ac_copilot_ctx_t* ctx) {
    lv_obj_t* row = lv_obj_create(scr);
    lv_obj_set_size(row, SCREEN_W - 2 * PAD, 24);
    lv_obj_set_pos(row, PAD, 252);
    lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(row, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(row, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_column(row, 4, LV_PART_MAIN);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);

    for (int i = 0; i < SEGMENT_COUNT; ++i) {
        ctx->segment_cells[i] = lv_obj_create(row);
        lv_obj_set_size(ctx->segment_cells[i], 19, 22);
        lv_obj_set_style_bg_color(ctx->segment_cells[i], UI_BG_RAISE, LV_PART_MAIN);
        lv_obj_set_style_bg_opa(ctx->segment_cells[i], LV_OPA_COVER, LV_PART_MAIN);
        lv_obj_set_style_border_width(ctx->segment_cells[i], 0, LV_PART_MAIN);
        lv_obj_set_style_radius(ctx->segment_cells[i], 0, LV_PART_MAIN);
        lv_obj_clear_flag(ctx->segment_cells[i], LV_OBJ_FLAG_SCROLLABLE);
    }
}

}  // namespace

extern "C" lv_obj_t* screen_ac_copilot_create(void) {
    auto* ctx = new (std::nothrow) ac_copilot_ctx_t();
    if (!ctx) {
        Serial.println("[fatal][ui] screen_ac_copilot ctx alloc failed");
        return nullptr;
    }
    *ctx = ac_copilot_ctx_t{};

    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(scr, on_screen_delete, LV_EVENT_DELETE, ctx);

    lv_obj_t* header = lv_obj_create(scr);
    lv_obj_set_size(header, SCREEN_W, HEADER_H);
    lv_obj_set_pos(header, 0, 0);
    lv_obj_set_style_bg_color(header, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(header, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_color(header, UI_BORDER_SOFT, LV_PART_MAIN);
    lv_obj_set_style_border_opa(header, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_side(header, LV_BORDER_SIDE_BOTTOM, LV_PART_MAIN);
    lv_obj_set_style_border_width(header, 1, LV_PART_MAIN);
    lv_obj_set_style_pad_all(header, 0, LV_PART_MAIN);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    ctx->mode_label = make_label(header, "AC COPILOT", UI_FONT_MONO_XS,
                                 UI_TX_QUIET, PAD, 8, 170);
    ctx->status_dot = lv_obj_create(header);
    lv_obj_set_size(ctx->status_dot, 7, 7);
    lv_obj_set_style_radius(ctx->status_dot, LV_RADIUS_CIRCLE, LV_PART_MAIN);
    lv_obj_set_style_border_width(ctx->status_dot, 0, LV_PART_MAIN);
    lv_obj_align(ctx->status_dot, LV_ALIGN_RIGHT_MID, -56, 0);
    ctx->status_label = make_label(header, "WAITING", UI_FONT_LABEL_SM,
                                   UI_TX_QUIET, SCREEN_W - 50, 6, 48);

    ctx->corner_badge = lv_label_create(scr);
    lv_label_set_text(ctx->corner_badge, "T-");
    style_label(ctx->corner_badge, UI_FONT_LABEL_MD, UI_BRASS_INK);
    lv_obj_set_size(ctx->corner_badge, 38, 30);
    lv_obj_set_pos(ctx->corner_badge, PAD, 52);
    lv_obj_set_style_bg_color(ctx->corner_badge, UI_BRASS, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(ctx->corner_badge, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_text_align(ctx->corner_badge, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);

    ctx->corner_label = make_label(scr, "--", UI_FONT_COMMAND_SM,
                                   UI_TX_PRIMARY, PAD + 50, 50, 166);
    ctx->current_speed = make_label(scr, "--", UI_FONT_READ_LG,
                                    UI_TX_PRIMARY, SCREEN_W - 82, 48, 68);
    lv_obj_set_style_text_align(ctx->current_speed, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN);
    make_line(scr, 110);

    ctx->command_label = make_label(scr, "WAIT", UI_FONT_COMMAND_HERO,
                                    UI_LINE_AMBER, PAD, 132, 180);
    ctx->command_marker = make_label(scr, "v", UI_FONT_COMMAND_SM,
                                     UI_LINE_AMBER, PAD + 4, 184, 24);

    make_label(scr, "BRAKE PT", UI_FONT_LABEL_XS, UI_TX_QUIET,
               SCREEN_W - 104, 142, 86);
    ctx->brake_distance = make_label(scr, "--", UI_FONT_READ_XL,
                                     UI_TX_FAINT, SCREEN_W - 104, 160, 80);
    lv_obj_set_style_text_align(ctx->brake_distance, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN);
    ctx->brake_unit = make_label(scr, "m", UI_FONT_MONO_MD,
                                 UI_TX_FAINT, SCREEN_W - 22, 196, 16);

    build_segments(scr, ctx);
    make_label(scr, "NOW", UI_FONT_LABEL_XS, UI_TX_QUIET, PAD, 282, 80);
    make_label(scr, "BRAKE ZONE", UI_FONT_LABEL_XS, UI_ALERT_RED,
               SCREEN_W - 104, 282, 91);

    ctx->delta_meta = make_label(scr, "ENTRY D - REF --", UI_FONT_LABEL_SM,
                                 UI_TX_MUTED, PAD, 304, 190);
    lv_obj_t* trough = lv_obj_create(scr);
    lv_obj_set_size(trough, SCREEN_W - 2 * PAD - 104, 20);
    lv_obj_set_pos(trough, PAD, 312);
    lv_obj_set_style_bg_color(trough, UI_BG_RAISE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(trough, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_width(trough, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(trough, 0, LV_PART_MAIN);
    lv_obj_clear_flag(trough, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t* center = lv_obj_create(scr);
    lv_obj_set_size(center, 2, 28);
    lv_obj_set_pos(center, PAD + (SCREEN_W - 2 * PAD - 104) / 2, 308);
    lv_obj_set_style_bg_color(center, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_border_width(center, 0, LV_PART_MAIN);
    lv_obj_clear_flag(center, LV_OBJ_FLAG_SCROLLABLE);
    ctx->delta_fill = lv_obj_create(scr);
    lv_obj_set_size(ctx->delta_fill, 3, 20);
    lv_obj_set_pos(ctx->delta_fill, PAD + 86, 312);
    lv_obj_set_style_border_width(ctx->delta_fill, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(ctx->delta_fill, 0, LV_PART_MAIN);
    lv_obj_add_flag(ctx->delta_fill, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(ctx->delta_fill, LV_OBJ_FLAG_SCROLLABLE);
    ctx->delta_value = make_label(scr, "--", UI_FONT_READ_XL,
                                  UI_TX_FAINT, SCREEN_W - 95, 296, 82);
    lv_obj_set_style_text_align(ctx->delta_value, LV_TEXT_ALIGN_RIGHT, LV_PART_MAIN);

    ctx->advice_delta = make_label(scr, "--", UI_FONT_LABEL_SM,
                                   UI_ALERT_RED, PAD, 404, 84);
    ctx->advice_text = make_label(scr, "waiting for coaching snapshot",
                                  UI_FONT_MONO_XS, UI_TX_MUTED, PAD + 66, 405, 220);

    lv_obj_t* footer = lv_obj_create(scr);
    lv_obj_set_size(footer, SCREEN_W, FOOTER_H);
    lv_obj_align(footer, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_bg_color(footer, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(footer, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_border_color(footer, UI_BORDER_SOFT, LV_PART_MAIN);
    lv_obj_set_style_border_opa(footer, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_side(footer, LV_BORDER_SIDE_TOP, LV_PART_MAIN);
    lv_obj_set_style_border_width(footer, 1, LV_PART_MAIN);
    lv_obj_set_style_pad_all(footer, 0, LV_PART_MAIN);
    lv_obj_clear_flag(footer, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t* mark = lv_obj_create(footer);
    lv_obj_set_size(mark, 4, 14);
    lv_obj_set_pos(mark, PAD, 11);
    lv_obj_set_style_bg_color(mark, UI_BRASS, LV_PART_MAIN);
    lv_obj_set_style_border_width(mark, 0, LV_PART_MAIN);
    lv_obj_clear_flag(mark, LV_OBJ_FLAG_SCROLLABLE);
    make_label(footer, "AC COPILOT", UI_FONT_LABEL_XS, UI_TX_QUIET, PAD + 12, 10, 120);
    lv_obj_t* back = lv_btn_create(footer);
    lv_obj_set_size(back, 78, 28);
    lv_obj_align(back, LV_ALIGN_RIGHT_MID, -PAD, 0);
    lv_obj_set_style_bg_opa(back, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_color(back, UI_BRASS, LV_PART_MAIN);
    lv_obj_set_style_border_width(back, 1, LV_PART_MAIN);
    lv_obj_set_style_radius(back, 0, LV_PART_MAIN);
    lv_obj_add_event_cb(back, on_back_clicked, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* back_lbl = lv_label_create(back);
    lv_label_set_text(back_lbl, "< BACK");
    style_label(back_lbl, UI_FONT_LABEL_XS, UI_BRASS);
    lv_obj_center(back_lbl);

    g_active_ctx = ctx;
    ctx->stale_timer = lv_timer_create(stale_timer_cb, 500, ctx);
    apply_to_widgets(ctx);
    return scr;
}

extern "C" void screen_ac_copilot_apply_snapshot(const coaching_snapshot_t* snap) {
    if (!snap) return;
    g_snap = *snap;
    g_snap.has_data = true;
    g_last_snapshot_ms = millis();
    if (g_active_ctx) lv_async_call(async_refresh_cb, g_active_ctx);
}

extern "C" void screen_ac_copilot_apply_corner_advice(const char* corner_id, const char* text) {
    if (corner_id == nullptr || *corner_id == 0) {
        g_advice_corner[0] = 0;
        g_advice_text[0] = 0;
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
    if (g_active_ctx) lv_async_call(async_refresh_cb, g_active_ctx);
}
