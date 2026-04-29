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

// Updated from main.cpp each `loop()` tick (after `ws_tick`).
static bool g_pt_sidecar_link_up = false;

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
    char    path[PT_SETUP_PATH_MAX];  // empty if trainer didn't ship a path
    int32_t brake_bias;
    int32_t abs;
    int32_t tc;
    int32_t wing_f;
    int32_t wing_r;
};

setup_row_t g_setups[PT_MAX_SETUPS];
int         g_setup_count = 0;

char g_car_id[32]    = {0};
char g_car_name[64]  = {0};   // human-readable; empty falls back to g_car_id
char g_car_brand[32] = {0};   // empty hides brand line
char g_track_id[32]  = {0};
char g_track_name[48] = {0};  // human-readable; empty falls back to g_track_id
char g_active_name[48] = {0}; // currently loaded setup name (from setup.active)

// Out-queue (FIFO).
pt_request_t g_req_q[PT_MAX_REQUESTS];
int          g_req_head = 0;
int          g_req_tail = 0;

// Pending row ↔ `setup.load.ack` correlation (CodeRabbit + Cursor on PR #91).
// `main.cpp` can emit several `PT_REQ_LOAD` frames per tick; each ack must
// pulse/toast the row that initiated that load, not whichever row was tapped
// last.
constexpr int PT_MAX_PENDING_LOADS = PT_MAX_REQUESTS - 1;
struct pending_load_t {
    char      name[64];
    char      path[PT_SETUP_PATH_MAX];
    lv_obj_t* row;
};
static pending_load_t g_pending_loads[PT_MAX_PENDING_LOADS];
static int            g_pending_load_n = 0;

static void pending_load_clear() {
    g_pending_load_n = 0;
}

static bool pending_load_push(const char* name, const char* path, lv_obj_t* row) {
    if (g_pending_load_n >= PT_MAX_PENDING_LOADS) return false;
    pending_load_t* p = &g_pending_loads[g_pending_load_n++];
    *p = pending_load_t{};
    if (name) {
        strncpy(p->name, name, sizeof(p->name) - 1);
        p->name[sizeof(p->name) - 1] = 0;
    }
    if (path && path[0]) {
        strncpy(p->path, path, sizeof(p->path) - 1);
        p->path[sizeof(p->path) - 1] = 0;
    }
    p->row = row;
    return true;
}

// Removes and returns the pending row for this ack. When `ack_path` is set,
// require a path match so two quick taps on different `race.ini` rows cannot
// steal each other's ack (chatgpt-codex P2 on PR #91). When `ack_path` is
// empty, only match pendings that also had no path at enqueue time so a
// path-qualified row never pairs with a bare ack.
static lv_obj_t* pending_load_take_row(const char* name, const char* ack_path) {
    if (!name || !name[0]) return nullptr;
    for (int i = 0; i < g_pending_load_n; ++i) {
        if (strcmp(g_pending_loads[i].name, name) != 0) continue;
        if (ack_path && ack_path[0]) {
            if (strcmp(g_pending_loads[i].path, ack_path) != 0) continue;
        } else {
            // Ack omitted `path`: only match pendings that also omitted a path
            // on enqueue; otherwise two same-basename rows with different paths
            // can steal each other's ack (chatgpt-codex P2 on PR #91).
            if (g_pending_loads[i].path[0] != 0) continue;
        }
        lv_obj_t* row = g_pending_loads[i].row;
        for (int j = i; j < g_pending_load_n - 1; ++j) {
            g_pending_loads[j] = g_pending_loads[j + 1];
        }
        --g_pending_load_n;
        return row;
    }
    return nullptr;
}

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
    lv_obj_t* meta_brand;
    lv_obj_t* meta_car;
    lv_obj_t* meta_active;
    lv_obj_t* list_col;        // scrollable column
    lv_obj_t* placeholder_lbl; // "Loading…" / "No setups found"
    lv_obj_t* active_row_obj;  // row being loaded (for gold pulse)
    lv_timer_t* pulse_timer;
    int       pulse_steps_left;
    char      pending_name[48];   // setup the user just tapped
    char      pending_path[PT_SETUP_PATH_MAX];  // matching path; "" if not known
};

pt_ctx_t* g_active_ctx = nullptr;

// --- Layout constants ------------------------------------------------------

// Portrait 320×480 (device mounted vertical).
constexpr int SCREEN_W   = 320;
constexpr int SCREEN_H   = 480;
constexpr int HEADER_H   = 40;
constexpr int META_H     = 84;  // TRACK / BRAND / MODEL / ACTIVE
constexpr int OUTER_PAD  = 12;
constexpr int ROW_H      = 68;  // name+best on row 1, params+date on row 2
constexpr int ROW_GAP    = 8;

// --- Helpers ---------------------------------------------------------------

void format_lap_ms(int32_t ms, char* out, size_t n) {
    if (ms <= 0) {
        snprintf(out, n, "-");
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
    int next = (g_req_tail + 1) % PT_MAX_REQUESTS;
    if (next == g_req_head) return;  // WS out-queue full
    if (g_pending_load_n >= PT_MAX_PENDING_LOADS) return;
    if (!g_pt_sidecar_link_up) return;

    // Stage `setup.load` first; only commit UI/pending correlation if the
    // request actually queued (Cursor Bugbot on PR #91).
    if (!req_q_push(PT_REQ_LOAD, s.name, s.path[0] ? s.path : nullptr)) return;
    if (!pending_load_push(s.name, s.path[0] ? s.path : nullptr, row)) {
        // Undo the queued request — pending and ring capacities should stay in
        // lockstep, but never leave a dangling LOAD without correlation.
        g_req_tail = (g_req_tail - 1 + PT_MAX_REQUESTS) % PT_MAX_REQUESTS;
        return;
    }
    strncpy(ctx->pending_name, s.name, sizeof(ctx->pending_name) - 1);
    ctx->pending_name[sizeof(ctx->pending_name) - 1] = 0;
    strncpy(ctx->pending_path, s.path, sizeof(ctx->pending_path) - 1);
    ctx->pending_path[sizeof(ctx->pending_path) - 1] = 0;
    ctx->active_row_obj = row;

    // Visual: subtle scale + spinner-like flash via a pressed style.
    lv_obj_set_style_bg_color(row, UI_BG_HEADER, LV_PART_MAIN | LV_STATE_PRESSED);
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

    // Row 1: name (left) + BEST lap (right)
    lv_obj_t* name_lbl = lv_label_create(row);
    lv_label_set_text(name_lbl, s.name);
    lv_obj_set_style_text_color(name_lbl, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_width(name_lbl, lv_pct(60));
    lv_label_set_long_mode(name_lbl, LV_LABEL_LONG_DOT);
    lv_obj_align(name_lbl, LV_ALIGN_TOP_LEFT, 0, 0);

    char lap_buf[20];
    format_lap_ms(s.best_ms, lap_buf, sizeof(lap_buf));
    lv_obj_t* best_val = lv_label_create(row);
    lv_label_set_text(best_val, lap_buf);
    lv_obj_set_style_text_color(best_val, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(best_val, LV_ALIGN_TOP_RIGHT, -16, 0);

    // Row 2: setup summary chips (left) -- BB / ABS / TC / Wings front-rear.
    // Compact single-line format keeps it readable in the 280-px row width.
    // snprintf return may exceed qrem on truncation — clamp advances so qrem
    // never goes negative (Cursor + codex on PR #91).
    char chip_buf[64];
    chip_buf[0] = '\0';
    char* q    = chip_buf;
    size_t rem = sizeof(chip_buf);
    auto append = [&](const char* fmt, int v) {
        if (rem <= 1) return;
        int n = snprintf(q, rem, fmt, v);
        if (n < 0) return;
        size_t w = (size_t)n;
        if (w >= rem) w = rem - 1;
        q += w;
        rem -= w;
    };
    if (s.brake_bias >= 0) append("BB:%d  ", (int)s.brake_bias);
    if (s.abs >= 0) append("ABS:%d  ", (int)s.abs);
    if (s.tc >= 0) append("TC:%d  ", (int)s.tc);
    if (s.wing_f >= 0 || s.wing_r >= 0) {
        char wf[6], wr[6];
        if (s.wing_f >= 0) snprintf(wf, sizeof(wf), "%d", (int)s.wing_f); else snprintf(wf, sizeof(wf), "-");
        if (s.wing_r >= 0) snprintf(wr, sizeof(wr), "%d", (int)s.wing_r); else snprintf(wr, sizeof(wr), "-");
        if (rem > 1) {
            int n = snprintf(q, rem, "W:%s/%s", wf, wr);
            if (n >= 0) {
                size_t w = (size_t)n;
                if (w >= rem) w = rem - 1;
                q += w;
                rem -= w;
            }
        }
    }
    if (chip_buf[0] == '\0') {
        snprintf(chip_buf, sizeof(chip_buf), "%s", s.mtime_iso[0] ? s.mtime_iso : "");
    }
    lv_obj_t* chips = lv_label_create(row);
    lv_label_set_text(chips, chip_buf);
    lv_obj_set_style_text_color(chips, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(chips, 1, LV_PART_MAIN);
    lv_obj_align(chips, LV_ALIGN_TOP_LEFT, 0, 26);

    lv_obj_t* chev = lv_label_create(row);
    lv_label_set_text(chev, ">");
    lv_obj_set_style_text_color(chev, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(chev, LV_ALIGN_RIGHT_MID, -4, 0);

    return row;
}

void rebuild_list_widgets(pt_ctx_t* ctx) {
    if (!ctx || !ctx->list_col) return;
    // Row widgets are about to be destroyed — drop any pending `setup.load`
    // correlation that still points at them (PR #91 review threads).
    pending_load_clear();
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

// Strip brand prefix from full car name. AC ui_car.json name reads
// Porsche 911 GT3 R 2016 with brand Porsche; the model row should be
// 911 GT3 R 2016 so the BRAND row above does not duplicate.
static const char* model_after_brand(const char* full, const char* brand) {
    if (!full || !brand || !*brand) return full;
    size_t bn = strlen(brand);
    if (strncasecmp(full, brand, bn) == 0) {
        const char* tail = full + bn;
        while (*tail == 0x20 || *tail == 0x2d || *tail == 0x2f) tail++;
        if (*tail) return tail;
    }
    return full;
}

void update_meta(pt_ctx_t* ctx) {
    if (!ctx) return;
    char buf[96];
    if (ctx->meta_track) {
        const char* t = g_track_name[0] ? g_track_name : (g_track_id[0] ? g_track_id : "-");
        snprintf(buf, sizeof(buf), "TRACK: %s", t);
        lv_label_set_text(ctx->meta_track, buf);
    }
    if (ctx->meta_brand) {
        if (g_car_brand[0]) {
            char up[32];
            size_t i = 0;
            for (; g_car_brand[i] && i < sizeof(up) - 1; ++i) {
                char c = g_car_brand[i];
                up[i] = (c >= 0x61 && c <= 0x7a) ? (char)(c - 32) : c;
            }
            up[i] = 0;
            lv_label_set_text(ctx->meta_brand, up);
            lv_obj_clear_flag(ctx->meta_brand, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(ctx->meta_brand, LV_OBJ_FLAG_HIDDEN);
        }
    }
    if (ctx->meta_car) {
        const char* full = g_car_name[0] ? g_car_name : (g_car_id[0] ? g_car_id : "-");
        const char* model = g_car_brand[0] ? model_after_brand(full, g_car_brand) : full;
        lv_label_set_text(ctx->meta_car, model);
    }
    if (ctx->meta_active) {
        if (g_active_name[0]) {
            snprintf(buf, sizeof(buf), "ACTIVE: %s", g_active_name);
            lv_label_set_text(ctx->meta_active, buf);
            lv_obj_clear_flag(ctx->meta_active, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(ctx->meta_active, LV_OBJ_FLAG_HIDDEN);
        }
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
    // Drop stale Pocket Technician loads when leaving the screen — otherwise
    // taps queued while offline fire after reconnect (Cursor Bugbot on PR #91).
    pending_load_clear();
    g_req_head = 0;
    g_req_tail = 0;
}

}  // namespace

extern "C" void screen_pocket_technician_set_sidecar_link_up(int link_up) {
    g_pt_sidecar_link_up = link_up != 0;
}

extern "C" lv_obj_t* screen_pocket_technician_create(void) {
    auto* ctx = new (std::nothrow) pt_ctx_t();
    if (!ctx) {
        Serial.println("[fatal][ui] screen_pocket_technician ctx alloc failed");
        return nullptr;
    }
    ctx->meta_track       = nullptr;
    ctx->meta_brand       = nullptr;
    ctx->meta_car         = nullptr;
    ctx->meta_active      = nullptr;
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

    // Stack: TRACK / BRAND-letterspaced / MODEL / ACTIVE.
    ctx->meta_track = lv_label_create(meta);
    lv_obj_set_style_text_color(ctx->meta_track, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->meta_track, 1, LV_PART_MAIN);
    lv_obj_set_width(ctx->meta_track, SCREEN_W - 2 * OUTER_PAD);
    lv_label_set_long_mode(ctx->meta_track, LV_LABEL_LONG_DOT);
    lv_obj_align(ctx->meta_track, LV_ALIGN_TOP_LEFT, 0, 0);

    ctx->meta_brand = lv_label_create(meta);
    lv_obj_set_style_text_color(ctx->meta_brand, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->meta_brand, 2, LV_PART_MAIN);
    lv_obj_set_width(ctx->meta_brand, SCREEN_W - 2 * OUTER_PAD);
    lv_label_set_long_mode(ctx->meta_brand, LV_LABEL_LONG_DOT);
    lv_obj_align(ctx->meta_brand, LV_ALIGN_TOP_LEFT, 0, 20);
    lv_label_set_text(ctx->meta_brand, "");
    lv_obj_add_flag(ctx->meta_brand, LV_OBJ_FLAG_HIDDEN);

    ctx->meta_car = lv_label_create(meta);
    lv_obj_set_style_text_color(ctx->meta_car, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->meta_car, 1, LV_PART_MAIN);
    lv_obj_set_width(ctx->meta_car, SCREEN_W - 2 * OUTER_PAD);
    lv_label_set_long_mode(ctx->meta_car, LV_LABEL_LONG_DOT);
    lv_obj_align(ctx->meta_car, LV_ALIGN_TOP_LEFT, 0, 40);

    ctx->meta_active = lv_label_create(meta);
    lv_obj_set_style_text_color(ctx->meta_active, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_set_style_text_letter_space(ctx->meta_active, 1, LV_PART_MAIN);
    lv_obj_set_width(ctx->meta_active, SCREEN_W - 2 * OUTER_PAD);
    lv_label_set_long_mode(ctx->meta_active, LV_LABEL_LONG_DOT);
    lv_obj_align(ctx->meta_active, LV_ALIGN_TOP_LEFT, 0, 60);
    lv_label_set_text(ctx->meta_active, "");
    lv_obj_add_flag(ctx->meta_active, LV_OBJ_FLAG_HIDDEN);

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
                                                    const char* path,
                                                    const pt_setup_summary_t* summary) {
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
    if (summary) {
        row->brake_bias = summary->brake_bias;
        row->abs        = summary->abs;
        row->tc         = summary->tc;
        row->wing_f     = summary->wing_f;
        row->wing_r     = summary->wing_r;
    } else {
        row->brake_bias = -1; row->abs = -1; row->tc = -1; row->wing_f = -1; row->wing_r = -1;
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

extern "C" void screen_pocket_technician_set_identity(const char* car_id, const char* car_name,
                                                       const char* car_brand,
                                                       const char* track_id, const char* track_name) {
    char prev_car[sizeof(g_car_id)];
    char prev_track[sizeof(g_track_id)];
    strncpy(prev_car, g_car_id, sizeof(prev_car));
    prev_car[sizeof(prev_car) - 1] = 0;
    strncpy(prev_track, g_track_id, sizeof(prev_track));
    prev_track[sizeof(prev_track) - 1] = 0;

    if (car_id) {
        strncpy(g_car_id, car_id, sizeof(g_car_id) - 1);
        g_car_id[sizeof(g_car_id) - 1] = 0;
    }
    if (car_name) {
        strncpy(g_car_name, car_name, sizeof(g_car_name) - 1);
        g_car_name[sizeof(g_car_name) - 1] = 0;
    } else {
        g_car_name[0] = 0;
    }
    if (car_brand) {
        strncpy(g_car_brand, car_brand, sizeof(g_car_brand) - 1);
        g_car_brand[sizeof(g_car_brand) - 1] = 0;
    } else {
        g_car_brand[0] = 0;
    }
    if (track_id) {
        strncpy(g_track_id, track_id, sizeof(g_track_id) - 1);
        g_track_id[sizeof(g_track_id) - 1] = 0;
    }
    if (track_name) {
        strncpy(g_track_name, track_name, sizeof(g_track_name) - 1);
        g_track_name[sizeof(g_track_name) - 1] = 0;
    } else {
        g_track_name[0] = 0;
    }
    // New list identity means any prior ACTIVE row may belong to another
    // car/track — clear until `setup.active` / a fresh load ack arrives
    // (chatgpt-codex P2 on PR #91).
    if ((car_id && strcmp(prev_car, g_car_id) != 0) ||
        (track_id && strcmp(prev_track, g_track_id) != 0)) {
        g_active_name[0] = 0;
        pending_load_clear();
    }
    if (g_active_ctx) update_meta(g_active_ctx);
}

extern "C" void screen_pocket_technician_set_active_setup(const char* name) {
    if (name) {
        strncpy(g_active_name, name, sizeof(g_active_name) - 1);
        g_active_name[sizeof(g_active_name) - 1] = 0;
    } else {
        g_active_name[0] = 0;
    }
    if (g_active_ctx) update_meta(g_active_ctx);
}

extern "C" void screen_pocket_technician_apply_load_ack(bool ok,
                                                         const char* name,
                                                         const char* path,
                                                         const char* error) {
    if (!g_active_ctx) return;
    lv_obj_t* row = nullptr;
    if (name && name[0]) {
        row = pending_load_take_row(name, path);
    }
    if (!row) {
        row = g_active_ctx->active_row_obj;
    }
    g_active_ctx->active_row_obj = row;

    if (ok) {
        // Successful load — kick off the gold pulse on the row that owns
        // this ack (Cursor Bugbot on PR #91).
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
        if (row) {
            lv_obj_set_style_bg_color(row,
                                      UI_BG_HEADER,
                                      LV_PART_MAIN | LV_STATE_PRESSED);
        }
        g_active_ctx->active_row_obj = nullptr;
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
