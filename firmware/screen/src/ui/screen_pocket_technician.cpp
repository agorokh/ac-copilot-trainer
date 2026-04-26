// Pocket Technician — issue #86 Part D.
//
// Layout (rotation=1, 480×320):
//
//   ┌────────────────────────────────────────────────────────────┐  40 px
//   │ POCKET TECHNICIAN                          ◀ BACK          │ header
//   ├────────────────────────────────────────────────────────────┤
//   │ CURRENT TRACK: monza             CAR: ks_porsche_911        │  20 px
//   ├────────────────────────────────────────────────────────────┤
//   │ ┌─ aggressive_quali ───────────── BEST 1:48.123  >  ┐      │
//   │ ├─ rain_setup       ───────────── BEST  —          >  ┤    │
//   │ ├─ baseline_v3      ───────────── BEST 1:51.040  >  ┤      │
//   │ │                  …list scrollable                  │      │
//   │ └─────────────────────────────────────────────────────┘    │
//   └────────────────────────────────────────────────────────────┘
//
// Tapping a row scales-to-0.98, shows a small spinner, then either
// pulses a gold border on the row (success) or surfaces a red toast
// (error). The trainer-side handler enforces the in-pits gate so this
// module never speaks Lua / CSP — it just renders the ack.

#include "ui/screen_pocket_technician.h"

#include "ui/nav.h"
#include "ui/toast.h"
#include "ui/tokens.h"

#include <Arduino.h>
#include <stdio.h>
#include <string.h>
#include <new>

namespace {

// ---- Module-static cache -------------------------------------------------

constexpr int  PT_MAX_SETUPS    = 64;     // bounded list cache
// Effective capacity of a one-slot-wasted ring is N-1, so we size the array
// at 5 to honor the documented depth of 4 in-flight requests (CodeRabbit on
// PR #91). On creation we already enqueue PT_REQ_LIST once, so a user who
// quickly taps three setups before the WS drains used to lose the third
// tap silently with capacity 4.
constexpr int  PT_MAX_REQUESTS  = 5;

struct setup_row_t {
    char    name[48];
    char    mtime_iso[32];
    int32_t best_ms;       // -1 = unknown
    char    path[160];     // empty if trainer didn't ship a path
};

setup_row_t g_setups[PT_MAX_SETUPS];
int         g_setup_count = 0;

char g_car_id[32]    = {0};
char g_track_id[32]  = {0};
char g_active_name[48] = {0};

// Out-queue (FIFO).
pt_request_t g_req_q[PT_MAX_REQUESTS];
int          g_req_head = 0;
int          g_req_tail = 0;

bool req_q_push(pt_request_kind_t kind, const char* name, const char* path) {
    int next = (g_req_tail + 1) % PT_MAX_REQUESTS;
    if (next == g_req_head) return false;  // full
    pt_request_t* r = &g_req_q[g_req_tail];
    r->kind = kind;
    if (name) {
        strncpy(r->name, name, sizeof(r->name) - 1);
        r->name[sizeof(r->name) - 1] = 0;
    } else {
        r->name[0] = 0;
    }
    if (path) {
        strncpy(r->path, path, sizeof(r->path) - 1);
        r->path[sizeof(r->path) - 1] = 0;
    } else {
        r->path[0] = 0;
    }
    g_req_tail = next;
    return true;
}

// ---- Per-screen ctx ------------------------------------------------------

struct pt_ctx_t {
    lv_obj_t* meta_track;
    lv_obj_t* meta_car;
    lv_obj_t* list_col;        // scrollable column
    lv_obj_t* placeholder_lbl; // "Loading…" / "No setups found"
    lv_obj_t* active_row_obj;  // row being loaded (for gold pulse)
    lv_timer_t* pulse_timer;
    int       pulse_steps_left;
    char      pending_name[48];   // setup the user just tapped
    char      pending_path[160];  // matching path; "" if not known
};

pt_ctx_t* g_active_ctx = nullptr;

// --- Layout constants ------------------------------------------------------

constexpr int SCREEN_W   = 480;
constexpr int SCREEN_H   = 320;
constexpr int HEADER_H   = 40;
constexpr int META_H     = 24;
constexpr int OUTER_PAD  = 12;
constexpr int ROW_H      = 56;
constexpr int ROW_GAP    = 8;

// --- Helpers ---------------------------------------------------------------

void format_lap_ms(int32_t ms, char* out, size_t n) {
    if (ms <= 0) {
        snprintf(out, n, "—");
        return;
    }
    int total_ms = (int)ms;
    int minutes  = total_ms / 60000;
    int rem_ms   = total_ms % 60000;
    int seconds  = rem_ms / 1000;
    int millis   = rem_ms % 1000;
    snprintf(out, n, "%d:%02d.%03d", minutes, seconds, millis);
}

void on_back_clicked(lv_event_t*) {
    ui_nav_pop();
}

void rebuild_list_widgets(pt_ctx_t* ctx);
lv_obj_t* make_row(lv_obj_t* parent, int idx, const setup_row_t& s);

void on_row_clicked(lv_event_t* e) {
    auto* ctx = g_active_ctx;
    if (!ctx) return;
    auto* row = lv_event_get_current_target(e);
    auto idx = (intptr_t)lv_event_get_user_data(e);
    if (idx < 0 || idx >= g_setup_count) return;
    const setup_row_t& s = g_setups[idx];
    strncpy(ctx->pending_name, s.name, sizeof(ctx->pending_name) - 1);
    ctx->pending_name[sizeof(ctx->pending_name) - 1] = 0;
    strncpy(ctx->pending_path, s.path, sizeof(ctx->pending_path) - 1);
    ctx->pending_path[sizeof(ctx->pending_path) - 1] = 0;
    ctx->active_row_obj = row;

    // Visual: subtle scale + spinner-like flash via a pressed style.
    lv_obj_set_style_bg_color(row, UI_BG_HEADER, LV_PART_MAIN | LV_STATE_PRESSED);

    // Stage `setup.load` for main.cpp to pick up. Drop silently if the
    // queue is full — the user will see no toast which matches their
    // mental model of "I tapped, nothing happened, let me tap again."
    // Carry the path so the Lua handler can disambiguate setups that
    // share a basename across track/layout folders.
    req_q_push(PT_REQ_LOAD, s.name, s.path[0] ? s.path : nullptr);
}

void pulse_step_cb(lv_timer_t* t) {
    auto* ctx = static_cast<pt_ctx_t*>(t->user_data);
    if (!ctx || !ctx->active_row_obj) {
        lv_timer_del(t);
        if (ctx) ctx->pulse_timer = nullptr;
        return;
    }
    // 6-step pulse: gold border in/out for ~480 ms total.
    int step = ctx->pulse_steps_left;
    if (step <= 0) {
        // Restore default border.
        lv_obj_set_style_border_color(ctx->active_row_obj, UI_BORDER_SOFT, LV_PART_MAIN);
        lv_obj_set_style_border_opa(ctx->active_row_obj, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
        lv_obj_set_style_border_width(ctx->active_row_obj, 1, LV_PART_MAIN);
        ctx->active_row_obj = nullptr;
        ctx->pulse_timer = nullptr;
        lv_timer_del(t);
        return;
    }
    bool on = (step % 2) == 0;
    lv_obj_set_style_border_color(ctx->active_row_obj, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_set_style_border_opa(ctx->active_row_obj, on ? LV_OPA_COVER : (lv_opa_t)80, LV_PART_MAIN);
    lv_obj_set_style_border_width(ctx->active_row_obj, on ? 2 : 1, LV_PART_MAIN);
    ctx->pulse_steps_left = step - 1;
}

void start_gold_pulse(pt_ctx_t* ctx) {
    if (!ctx || !ctx->active_row_obj) return;
    if (ctx->pulse_timer) {
        lv_timer_del(ctx->pulse_timer);
        ctx->pulse_timer = nullptr;
    }
    ctx->pulse_steps_left = 6;
    ctx->pulse_timer = lv_timer_create(pulse_step_cb, 80, ctx);
}

lv_obj_t* make_row(lv_obj_t* parent, int idx, const setup_row_t& s) {
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
    lv_obj_set_style_bg_color(row, UI_BG_HEADER, LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_add_event_cb(row, on_row_clicked, LV_EVENT_CLICKED,
                        reinterpret_cast<void*>(static_cast<intptr_t>(idx)));

    lv_obj_t* name_lbl = lv_label_create(row);
    lv_label_set_text(name_lbl, s.name);
    lv_obj_set_style_text_color(name_lbl, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(name_lbl, LV_ALIGN_TOP_LEFT, 0, 0);

    lv_obj_t* date_lbl = lv_label_create(row);
    lv_label_set_text(date_lbl, s.mtime_iso[0] ? s.mtime_iso : "—");
    lv_obj_set_style_text_color(date_lbl, UI_TX_QUIET, LV_PART_MAIN);
    lv_obj_align(date_lbl, LV_ALIGN_TOP_LEFT, 0, 22);

    lv_obj_t* best_lbl_static = lv_label_create(row);
    lv_label_set_text(best_lbl_static, "BEST");
    lv_obj_set_style_text_color(best_lbl_static, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(best_lbl_static, 1, LV_PART_MAIN);
    lv_obj_align(best_lbl_static, LV_ALIGN_TOP_RIGHT, -100, 0);

    char lap_buf[20];
    format_lap_ms(s.best_ms, lap_buf, sizeof(lap_buf));
    lv_obj_t* best_val = lv_label_create(row);
    lv_label_set_text(best_val, lap_buf);
    lv_obj_set_style_text_color(best_val, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(best_val, LV_ALIGN_TOP_RIGHT, -32, 0);

    lv_obj_t* chev = lv_label_create(row);
    lv_label_set_text(chev, ">");
    lv_obj_set_style_text_color(chev, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(chev, LV_ALIGN_RIGHT_MID, -4, 0);

    return row;
}

void rebuild_list_widgets(pt_ctx_t* ctx) {
    if (!ctx || !ctx->list_col) return;
    // Clear existing children.
    lv_obj_clean(ctx->list_col);
    ctx->active_row_obj = nullptr;

    if (g_setup_count == 0) {
        ctx->placeholder_lbl = lv_label_create(ctx->list_col);
        lv_label_set_text(ctx->placeholder_lbl,
                          g_car_id[0] ? "No setups for this car" : "Loading…");
        lv_obj_set_style_text_color(ctx->placeholder_lbl, UI_TX_MUTED, LV_PART_MAIN);
        return;
    }
    ctx->placeholder_lbl = nullptr;

    for (int i = 0; i < g_setup_count; ++i) {
        make_row(ctx->list_col, i, g_setups[i]);
    }
}

void update_meta(pt_ctx_t* ctx) {
    if (!ctx) return;
    char buf[80];
    if (ctx->meta_track) {
        snprintf(buf, sizeof(buf), "TRACK: %s", g_track_id[0] ? g_track_id : "—");
        lv_label_set_text(ctx->meta_track, buf);
    }
    if (ctx->meta_car) {
        snprintf(buf, sizeof(buf), "CAR: %s", g_car_id[0] ? g_car_id : "—");
        lv_label_set_text(ctx->meta_car, buf);
    }
}

void on_screen_delete(lv_event_t* e) {
    auto* ctx = static_cast<pt_ctx_t*>(lv_event_get_user_data(e));
    if (ctx == g_active_ctx) g_active_ctx = nullptr;
    if (ctx) {
        if (ctx->pulse_timer) {
            lv_timer_del(ctx->pulse_timer);
        }
        delete ctx;
    }
}

}  // namespace

extern "C" lv_obj_t* screen_pocket_technician_create(void) {
    auto* ctx = new (std::nothrow) pt_ctx_t();
    if (!ctx) {
        Serial.println("[fatal][ui] screen_pocket_technician ctx alloc failed");
        return nullptr;
    }
    ctx->meta_track       = nullptr;
    ctx->meta_car         = nullptr;
    ctx->list_col         = nullptr;
    ctx->placeholder_lbl  = nullptr;
    ctx->active_row_obj   = nullptr;
    ctx->pulse_timer      = nullptr;
    ctx->pulse_steps_left = 0;
    ctx->pending_name[0]  = 0;
    ctx->pending_path[0]  = 0;

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
    lv_label_set_text(title, "POCKET TECHNICIAN");
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

    // ---- Meta bar ----------------------------------------------------------
    lv_obj_t* meta = lv_obj_create(scr);
    lv_obj_set_size(meta, SCREEN_W - 2 * OUTER_PAD, META_H);
    lv_obj_align(meta, LV_ALIGN_TOP_MID, 0, HEADER_H + 6);
    lv_obj_set_style_bg_opa(meta, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(meta, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(meta, 0, LV_PART_MAIN);
    lv_obj_clear_flag(meta, LV_OBJ_FLAG_SCROLLABLE);

    ctx->meta_track = lv_label_create(meta);
    lv_obj_set_style_text_color(ctx->meta_track, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->meta_track, 1, LV_PART_MAIN);
    lv_obj_align(ctx->meta_track, LV_ALIGN_LEFT_MID, 0, 0);

    ctx->meta_car = lv_label_create(meta);
    lv_obj_set_style_text_color(ctx->meta_car, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->meta_car, 1, LV_PART_MAIN);
    lv_obj_align(ctx->meta_car, LV_ALIGN_RIGHT_MID, 0, 0);

    // ---- Setup list (scrollable) -------------------------------------------
    const int list_y = HEADER_H + 6 + META_H + 6;
    ctx->list_col = lv_obj_create(scr);
    lv_obj_set_size(ctx->list_col,
                    SCREEN_W - 2 * OUTER_PAD,
                    SCREEN_H - list_y - OUTER_PAD);
    lv_obj_align(ctx->list_col, LV_ALIGN_TOP_MID, 0, list_y);
    lv_obj_set_style_bg_opa(ctx->list_col, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(ctx->list_col, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(ctx->list_col, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_row(ctx->list_col, ROW_GAP, LV_PART_MAIN);
    lv_obj_set_flex_flow(ctx->list_col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(ctx->list_col, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    // Vertical scroll lets long setup directories paginate naturally.
    lv_obj_set_scroll_dir(ctx->list_col, LV_DIR_VER);
    lv_obj_add_flag(ctx->list_col, LV_OBJ_FLAG_SCROLLABLE);

    g_active_ctx = ctx;

    // Initial paint from cached state.
    update_meta(ctx);
    rebuild_list_widgets(ctx);

    // Stage the `setup.list` request — main.cpp will forward it on the next
    // loop tick. The trainer's response (setup.list.result) reaches us via
    // screen_pocket_technician_clear_setups + add_setup, then a final
    // rebuild via set_identity / set_active_setup callbacks.
    req_q_push(PT_REQ_LIST, nullptr, nullptr);

    return scr;
}

extern "C" void screen_pocket_technician_clear_setups(void) {
    g_setup_count = 0;
    // Full rebuild on the clear-edge only - keeps the list-arrival path at
    // O(N) total widget creations instead of O(N^2) (CodeRabbit + Cursor on
    // PR #91). main.cpp's `setup.list.result` dispatch always calls
    // clear_setups() before streaming add_setup(), so this is the canonical
    // place to drop+rebuild the column.
    if (g_active_ctx) {
        rebuild_list_widgets(g_active_ctx);
    }
}

extern "C" void screen_pocket_technician_add_setup(const char* name,
                                                    const char* mtime_iso,
                                                    int32_t best_ms,
                                                    const char* path) {
    if (!name || !*name) return;
    if (g_setup_count >= PT_MAX_SETUPS) return;
    setup_row_t* row = &g_setups[g_setup_count];
    strncpy(row->name, name, sizeof(row->name) - 1);
    row->name[sizeof(row->name) - 1] = 0;
    if (mtime_iso) {
        strncpy(row->mtime_iso, mtime_iso, sizeof(row->mtime_iso) - 1);
        row->mtime_iso[sizeof(row->mtime_iso) - 1] = 0;
    } else {
        row->mtime_iso[0] = 0;
    }
    row->best_ms = best_ms;
    if (path) {
        strncpy(row->path, path, sizeof(row->path) - 1);
        row->path[sizeof(row->path) - 1] = 0;
    } else {
        row->path[0] = 0;
    }
    int idx = g_setup_count++;

    if (g_active_ctx && g_active_ctx->list_col) {
        // Append-only: drop the placeholder on the very first entry, then
        // create exactly one new row widget. No churn on the existing rows.
        if (g_active_ctx->placeholder_lbl) {
            lv_obj_del(g_active_ctx->placeholder_lbl);
            g_active_ctx->placeholder_lbl = nullptr;
        }
        make_row(g_active_ctx->list_col, idx, *row);
    }
}

extern "C" void screen_pocket_technician_set_identity(const char* car_id, const char* track_id) {
    if (car_id) {
        strncpy(g_car_id, car_id, sizeof(g_car_id) - 1);
        g_car_id[sizeof(g_car_id) - 1] = 0;
    }
    if (track_id) {
        strncpy(g_track_id, track_id, sizeof(g_track_id) - 1);
        g_track_id[sizeof(g_track_id) - 1] = 0;
    }
    if (g_active_ctx) update_meta(g_active_ctx);
}

extern "C" void screen_pocket_technician_set_active_setup(const char* name) {
    if (!name) return;
    strncpy(g_active_name, name, sizeof(g_active_name) - 1);
    g_active_name[sizeof(g_active_name) - 1] = 0;
    // No widget hooks here — Part D leaves the "active row highlight" for
    // a follow-up. The cached name is kept so a future visual can opt in.
}

extern "C" void screen_pocket_technician_apply_load_ack(bool ok,
                                                         const char* /*name*/,
                                                         const char* error) {
    if (!g_active_ctx) return;
    if (ok) {
        // Successful load — kick off the gold pulse on the active row.
        start_gold_pulse(g_active_ctx);
        // Re-fetch the list so any "BEST" recomputation lands.
        req_q_push(PT_REQ_LIST, nullptr, nullptr);
    } else {
        // Reset any pressed visual then surface the toast. The row's
        // PRESSED-state bg was originally UI_BG_HEADER (matching the
        // header pill), so restore THAT, not UI_BG_PANEL -- overriding
        // to the unpressed colour permanently kills pressed-state
        // feedback on the failed row even after the toast clears
        // (Cursor Bugbot LOW on PR #91).
        if (g_active_ctx->active_row_obj) {
            lv_obj_set_style_bg_color(g_active_ctx->active_row_obj,
                                      UI_BG_HEADER,
                                      LV_PART_MAIN | LV_STATE_PRESSED);
            g_active_ctx->active_row_obj = nullptr;
        }
        char msg[80];
        snprintf(msg, sizeof(msg), "Load failed: %s", error ? error : "unknown");
        ui_toast_error(msg);
    }
}

extern "C" pt_request_t screen_pocket_technician_pop_request(void) {
    pt_request_t out;
    out.kind = PT_REQ_NONE;
    out.name[0] = 0;
    out.path[0] = 0;
    if (g_req_head == g_req_tail) return out;
    out = g_req_q[g_req_head];
    g_req_head = (g_req_head + 1) % PT_MAX_REQUESTS;
    return out;
}
