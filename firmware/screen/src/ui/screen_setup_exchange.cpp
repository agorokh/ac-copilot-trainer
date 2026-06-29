// Setup Exchange browser -- issue #363.

#include "ui/screen_setup_exchange.h"

#include "ui/nav.h"
#include "ui/toast.h"
#include "ui/tokens.h"

#include <Arduino.h>
#include <new>
#include <stdio.h>
#include <string.h>

static bool g_se_sidecar_link_up = false;

namespace {

constexpr int SCREEN_W = 320;
constexpr int SCREEN_H = 480;
constexpr int HEADER_H = 40;
constexpr int META_H = 64;
constexpr int OUTER_PAD = 12;
constexpr int ROW_H = 76;
constexpr int ROW_GAP = 8;
constexpr int SE_MAX_RESULTS = 32;
constexpr int SE_MAX_REQUESTS = 4;

struct se_result_t {
    int32_t setup_id;
    int32_t downloads;
    char    name[SE_TEXT_MAX];
    char    author[48];
    char    car_id[32];
    char    track_id[32];
};

struct se_ctx_t {
    lv_obj_t* meta_car;
    lv_obj_t* meta_track;
    lv_obj_t* status;
    lv_obj_t* list_col;
    lv_obj_t* placeholder;
    lv_obj_t* active_row;
};

se_result_t g_results[SE_MAX_RESULTS];
int         g_result_count = 0;
char        g_car_id[32] = {0};
char        g_car_name[64] = {0};
char        g_track_id[32] = {0};
char        g_track_name[48] = {0};
bool        g_loading = false;
int32_t     g_pending_setup_id = -1;
se_ctx_t*   g_active_ctx = nullptr;

se_request_t g_req_q[SE_MAX_REQUESTS];
int          g_req_head = 0;
int          g_req_tail = 0;

void copy_text(char* dst, size_t dst_n, const char* src) {
    if (!dst || dst_n == 0) return;
    if (src) {
        strncpy(dst, src, dst_n - 1);
        dst[dst_n - 1] = 0;
    } else {
        dst[0] = 0;
    }
}

bool req_q_push_search(const char* search) {
    int next = (g_req_tail + 1) % SE_MAX_REQUESTS;
    if (next == g_req_head) return false;
    se_request_t* r = &g_req_q[g_req_tail];
    *r = se_request_t{};
    r->kind = SE_REQ_SEARCH;
    copy_text(r->car_id, sizeof(r->car_id), g_car_id[0] ? g_car_id : nullptr);
    copy_text(r->track_id, sizeof(r->track_id), g_track_id[0] ? g_track_id : nullptr);
    copy_text(r->search, sizeof(r->search), search);
    g_req_tail = next;
    return true;
}

bool req_q_push_download(const se_result_t& result) {
    const char* car = result.car_id[0] ? result.car_id : g_car_id;
    if (!car || !*car) return false;
    int next = (g_req_tail + 1) % SE_MAX_REQUESTS;
    if (next == g_req_head) return false;
    se_request_t* r = &g_req_q[g_req_tail];
    *r = se_request_t{};
    r->kind = SE_REQ_DOWNLOAD;
    r->setup_id = result.setup_id;
    copy_text(r->name, sizeof(r->name), result.name);
    copy_text(r->car_id, sizeof(r->car_id), car);
    const char* track = result.track_id[0] ? result.track_id : g_track_id;
    copy_text(r->track_id, sizeof(r->track_id), (track && *track) ? track : nullptr);
    g_req_tail = next;
    return true;
}

void on_back_clicked(lv_event_t*) {
    ui_nav_pop();
}

void set_status(const char* text, lv_color_t color) {
    if (!g_active_ctx || !g_active_ctx->status) return;
    lv_label_set_text(g_active_ctx->status, text ? text : "");
    lv_obj_set_style_text_color(g_active_ctx->status, color, LV_PART_MAIN);
}

bool has_pending_download() {
    return g_pending_setup_id > 0;
}

lv_obj_t* valid_active_row(se_ctx_t* ctx) {
    return (ctx && ctx->active_row) ? ctx->active_row : nullptr;
}

void update_meta(se_ctx_t* ctx) {
    if (!ctx) return;
    char buf[96];
    const char* car = g_car_name[0] ? g_car_name : (g_car_id[0] ? g_car_id : "-");
    const char* track = g_track_name[0] ? g_track_name : (g_track_id[0] ? g_track_id : "-");
    snprintf(buf, sizeof(buf), "CAR: %s", car);
    lv_label_set_text(ctx->meta_car, buf);
    snprintf(buf, sizeof(buf), "TRACK: %s", track);
    lv_label_set_text(ctx->meta_track, buf);
}

void rebuild_list(se_ctx_t* ctx);

void on_refresh_clicked(lv_event_t*) {
    if (!g_se_sidecar_link_up) {
        ui_toast_error("Setup Exchange offline");
        return;
    }
    if (has_pending_download()) {
        ui_toast_error("Download in progress");
        return;
    }
    g_loading = true;
    set_status("Searching...", UI_TX_MUTED);
    if (!req_q_push_search(nullptr)) {
        g_loading = false;
        ui_toast_error("Setup Exchange busy");
    }
    if (g_active_ctx) rebuild_list(g_active_ctx);
}

void on_row_clicked(lv_event_t* e) {
    if (!g_se_sidecar_link_up) {
        ui_toast_error("Setup Exchange offline");
        return;
    }
    auto idx = (intptr_t)lv_event_get_user_data(e);
    if (idx < 0 || idx >= g_result_count) return;
    if (has_pending_download()) {
        ui_toast_error("Download in progress");
        return;
    }
    se_result_t& result = g_results[idx];
    if (!(result.car_id[0] || g_car_id[0])) {
        ui_toast_error("Open Pocket Technician first");
        return;
    }
    if (!req_q_push_download(result)) {
        ui_toast_error("Setup Exchange busy");
        return;
    }
    g_pending_setup_id = result.setup_id;
    g_active_ctx->active_row = lv_event_get_current_target(e);
    lv_obj_set_style_border_color(g_active_ctx->active_row, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_set_style_border_opa(g_active_ctx->active_row, LV_OPA_COVER, LV_PART_MAIN);
    set_status("Downloading...", UI_ACCENT_GOLD);
}

void on_row_delete(lv_event_t* e) {
    auto* ctx = static_cast<se_ctx_t*>(lv_event_get_user_data(e));
    if (!ctx) return;
    if (ctx->active_row == lv_event_get_target(e)) ctx->active_row = nullptr;
}

lv_obj_t* make_row(se_ctx_t* ctx, int idx, const se_result_t& result) {
    if (!ctx || !ctx->list_col) return nullptr;
    lv_obj_t* parent = ctx->list_col;
    lv_obj_t* row = lv_obj_create(parent);
    lv_obj_set_size(row, lv_pct(100), ROW_H);
    lv_obj_set_style_bg_color(row, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(row, UI_BG_PANEL_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_color(row, UI_BORDER_SOFT, LV_PART_MAIN);
    lv_obj_set_style_border_opa(row, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(row, 1, LV_PART_MAIN);
    lv_obj_set_style_radius(row, UI_RADIUS_TILE, LV_PART_MAIN);
    lv_obj_set_style_pad_all(row, 8, LV_PART_MAIN);
    lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(row, on_row_clicked, LV_EVENT_CLICKED,
                        reinterpret_cast<void*>(static_cast<intptr_t>(idx)));
    lv_obj_add_event_cb(row, on_row_delete, LV_EVENT_DELETE, ctx);

    lv_obj_t* name = lv_label_create(row);
    lv_label_set_text(name, result.name);
    lv_obj_set_width(name, 232);
    lv_label_set_long_mode(name, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_color(name, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(name, LV_ALIGN_TOP_LEFT, 0, 0);

    char line[96];
    if (result.author[0]) {
        snprintf(line, sizeof(line), "BY %s", result.author);
    } else {
        snprintf(line, sizeof(line), "COMMUNITY SETUP");
    }
    lv_obj_t* author = lv_label_create(row);
    lv_label_set_text(author, line);
    lv_obj_set_width(author, 232);
    lv_label_set_long_mode(author, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_color(author, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_align(author, LV_ALIGN_TOP_LEFT, 0, 24);

    if (result.downloads >= 0) {
        snprintf(line, sizeof(line), "%ld DL", (long)result.downloads);
    } else {
        snprintf(line, sizeof(line), "TAP TO LOAD");
    }
    lv_obj_t* dl = lv_label_create(row);
    lv_label_set_text(dl, line);
    lv_obj_set_width(dl, 232);
    lv_label_set_long_mode(dl, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_color(dl, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(dl, LV_ALIGN_BOTTOM_LEFT, 0, 0);

    lv_obj_t* chevron = lv_label_create(row);
    lv_label_set_text(chevron, ">");
    lv_obj_set_style_text_color(chevron, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(chevron, LV_ALIGN_RIGHT_MID, 0, 0);
    return row;
}

void rebuild_list(se_ctx_t* ctx) {
    if (!ctx || !ctx->list_col) return;
    ctx->active_row = nullptr;
    lv_obj_clean(ctx->list_col);
    ctx->placeholder = nullptr;
    if (g_result_count == 0) {
        ctx->placeholder = lv_label_create(ctx->list_col);
        lv_label_set_text(ctx->placeholder, g_loading ? "Loading..." : "No setups found");
        lv_obj_set_style_text_color(ctx->placeholder, UI_TX_MUTED, LV_PART_MAIN);
        lv_obj_set_width(ctx->placeholder, SCREEN_W - 2 * OUTER_PAD);
        lv_label_set_long_mode(ctx->placeholder, LV_LABEL_LONG_DOT);
        return;
    }
    for (int i = 0; i < g_result_count; ++i) {
        make_row(ctx, i, g_results[i]);
    }
}

void on_screen_delete(lv_event_t* e) {
    auto* ctx = static_cast<se_ctx_t*>(lv_event_get_user_data(e));
    if (ctx == g_active_ctx) g_active_ctx = nullptr;
    delete ctx;
    g_req_head = 0;
    g_req_tail = 0;
    g_pending_setup_id = -1;
}

}  // namespace

extern "C" void screen_setup_exchange_set_sidecar_link_up(int link_up) {
    g_se_sidecar_link_up = link_up != 0;
}

extern "C" lv_obj_t* screen_setup_exchange_create(void) {
    auto* ctx = new (std::nothrow) se_ctx_t();
    if (!ctx) {
        Serial.println("[fatal][ui] setup exchange ctx alloc failed");
        return nullptr;
    }
    *ctx = se_ctx_t{};

    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(scr, on_screen_delete, LV_EVENT_DELETE, ctx);

    lv_obj_t* header = lv_obj_create(scr);
    lv_obj_set_size(header, SCREEN_W, HEADER_H);
    lv_obj_align(header, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(header, UI_BG_HEADER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(header, UI_BG_HEADER_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(header, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(header, 0, LV_PART_MAIN);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* title = lv_label_create(header);
    lv_label_set_text(title, "SETUP EXCHANGE");
    lv_obj_set_style_text_color(title, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(title, 2, LV_PART_MAIN);
    lv_obj_align(title, LV_ALIGN_LEFT_MID, 12, 0);

    lv_obj_t* back = lv_btn_create(header);
    lv_obj_set_size(back, 92, HEADER_H - 4);
    lv_obj_align(back, LV_ALIGN_RIGHT_MID, -2, 0);
    lv_obj_set_style_bg_color(back, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(back, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(back, 6, LV_PART_MAIN);
    lv_obj_set_style_border_width(back, 0, LV_PART_MAIN);
    lv_obj_add_event_cb(back, on_back_clicked, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* back_lbl = lv_label_create(back);
    lv_label_set_text(back_lbl, "< BACK");
    lv_obj_set_style_text_color(back_lbl, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_center(back_lbl);

    lv_obj_t* meta = lv_obj_create(scr);
    lv_obj_set_size(meta, SCREEN_W - 2 * OUTER_PAD, META_H);
    lv_obj_align(meta, LV_ALIGN_TOP_MID, 0, HEADER_H + 6);
    lv_obj_set_style_bg_opa(meta, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(meta, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(meta, 0, LV_PART_MAIN);
    lv_obj_clear_flag(meta, LV_OBJ_FLAG_SCROLLABLE);

    ctx->meta_car = lv_label_create(meta);
    lv_obj_set_width(ctx->meta_car, SCREEN_W - 2 * OUTER_PAD - 84);
    lv_label_set_long_mode(ctx->meta_car, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_color(ctx->meta_car, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(ctx->meta_car, LV_ALIGN_TOP_LEFT, 0, 0);

    ctx->meta_track = lv_label_create(meta);
    lv_obj_set_width(ctx->meta_track, SCREEN_W - 2 * OUTER_PAD - 84);
    lv_label_set_long_mode(ctx->meta_track, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_color(ctx->meta_track, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_align(ctx->meta_track, LV_ALIGN_TOP_LEFT, 0, 22);

    ctx->status = lv_label_create(meta);
    lv_obj_set_width(ctx->status, SCREEN_W - 2 * OUTER_PAD);
    lv_label_set_long_mode(ctx->status, LV_LABEL_LONG_DOT);
    lv_obj_set_style_text_color(ctx->status, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_align(ctx->status, LV_ALIGN_BOTTOM_LEFT, 0, 0);

    lv_obj_t* refresh = lv_btn_create(meta);
    lv_obj_set_size(refresh, 76, 34);
    lv_obj_align(refresh, LV_ALIGN_TOP_RIGHT, 0, 0);
    lv_obj_set_style_bg_color(refresh, UI_BG_HEADER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(refresh, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_radius(refresh, 6, LV_PART_MAIN);
    lv_obj_add_event_cb(refresh, on_refresh_clicked, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* refresh_lbl = lv_label_create(refresh);
    lv_label_set_text(refresh_lbl, "REFRESH");
    lv_obj_set_style_text_color(refresh_lbl, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_center(refresh_lbl);

    const int list_y = HEADER_H + 6 + META_H + 6;
    ctx->list_col = lv_obj_create(scr);
    lv_obj_set_size(ctx->list_col, SCREEN_W - 2 * OUTER_PAD, SCREEN_H - list_y - OUTER_PAD);
    lv_obj_align(ctx->list_col, LV_ALIGN_TOP_MID, 0, list_y);
    lv_obj_set_style_bg_opa(ctx->list_col, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(ctx->list_col, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(ctx->list_col, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_row(ctx->list_col, ROW_GAP, LV_PART_MAIN);
    lv_obj_set_flex_flow(ctx->list_col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(ctx->list_col, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_scroll_dir(ctx->list_col, LV_DIR_VER);
    lv_obj_add_flag(ctx->list_col, LV_OBJ_FLAG_SCROLLABLE);

    g_active_ctx = ctx;
    update_meta(ctx);
    g_loading = true;
    set_status("Searching...", UI_TX_MUTED);
    rebuild_list(ctx);
    req_q_push_search(nullptr);
    return scr;
}

extern "C" void screen_setup_exchange_set_context(const char* car_id, const char* car_name,
                                                   const char* track_id,
                                                   const char* track_name) {
    if (car_id) {
        copy_text(g_car_id, sizeof(g_car_id), car_id);
    } else {
        g_car_id[0] = 0;
    }
    if (car_name) {
        copy_text(g_car_name, sizeof(g_car_name), car_name);
    } else {
        g_car_name[0] = 0;
    }
    if (track_id) {
        copy_text(g_track_id, sizeof(g_track_id), track_id);
    } else {
        g_track_id[0] = 0;
    }
    if (track_name) {
        copy_text(g_track_name, sizeof(g_track_name), track_name);
    } else {
        g_track_name[0] = 0;
    }
    if (g_active_ctx) update_meta(g_active_ctx);
}

extern "C" void screen_setup_exchange_clear_results(void) {
    g_result_count = 0;
    g_loading = false;
}

extern "C" void screen_setup_exchange_add_result(int32_t setup_id,
                                                  const char* name,
                                                  const char* author,
                                                  int32_t downloads,
                                                  const char* car_id,
                                                  const char* track_id) {
    if (setup_id <= 0 || !name || !*name) return;
    if (g_result_count >= SE_MAX_RESULTS) return;
    se_result_t* row = &g_results[g_result_count++];
    *row = se_result_t{};
    row->setup_id = setup_id;
    row->downloads = downloads;
    copy_text(row->name, sizeof(row->name), name);
    copy_text(row->author, sizeof(row->author), author);
    copy_text(row->car_id, sizeof(row->car_id), car_id);
    copy_text(row->track_id, sizeof(row->track_id), track_id);
}

extern "C" void screen_setup_exchange_finish_results(void) {
    g_loading = false;
    set_status(g_result_count > 0 ? "Tap a setup to download" : "No community setups found",
               g_result_count > 0 ? UI_TX_MUTED : UI_ALERT_RED);
    if (g_active_ctx) rebuild_list(g_active_ctx);
}

extern "C" void screen_setup_exchange_apply_search_error(const char* error) {
    g_loading = false;
    set_status("Search failed", UI_ALERT_RED);
    if (g_active_ctx) rebuild_list(g_active_ctx);
    char msg[96];
    snprintf(msg, sizeof(msg), "Search failed: %s", error && *error ? error : "unknown");
    ui_toast_error(msg);
}

extern "C" void screen_setup_exchange_apply_download_ack(bool ok,
                                                          int32_t setup_id,
                                                          const char* name,
                                                          const char* path,
                                                          const char* error) {
    if (ok) {
        g_pending_setup_id = -1;
        lv_obj_t* row = valid_active_row(g_active_ctx);
        if (row) {
            lv_obj_set_style_border_color(row, UI_OK_GREEN, LV_PART_MAIN);
            lv_obj_set_style_border_opa(row, LV_OPA_COVER, LV_PART_MAIN);
            g_active_ctx->active_row = nullptr;
        }
        char msg[96];
        snprintf(msg, sizeof(msg), "Installed: %s", name && *name ? name : "setup");
        set_status(msg, UI_OK_GREEN);
        (void)path;
    } else {
        if (setup_id == g_pending_setup_id) g_pending_setup_id = -1;
        lv_obj_t* row = valid_active_row(g_active_ctx);
        if (row) {
            lv_obj_set_style_border_color(row, UI_ALERT_RED, LV_PART_MAIN);
            lv_obj_set_style_border_opa(row, LV_OPA_COVER, LV_PART_MAIN);
            g_active_ctx->active_row = nullptr;
        }
        set_status("Download failed", UI_ALERT_RED);
        char msg[96];
        snprintf(msg, sizeof(msg), "Download failed: %s", error && *error ? error : "unknown");
        ui_toast_error(msg);
    }
}

extern "C" se_request_t screen_setup_exchange_pop_request(void) {
    se_request_t out;
    out.kind = SE_REQ_NONE;
    out.setup_id = 0;
    out.name[0] = 0;
    out.car_id[0] = 0;
    out.track_id[0] = 0;
    out.search[0] = 0;
    if (g_req_head == g_req_tail) return out;
    out = g_req_q[g_req_head];
    g_req_head = (g_req_head + 1) % SE_MAX_REQUESTS;
    return out;
}
