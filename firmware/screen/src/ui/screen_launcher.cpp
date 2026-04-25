// Launcher screen — issue #86 Part B (Menu.tsx port).
//
// Three vertical app tiles + live CONNECTED/DISCONNECTED status pill,
// matching the Figma "Menu" component (see
// docs/01_Vault/AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
// and the TSX reference under
// agorokh/Ingamecoachingtrainerdesign/src/app/components/mobile/Menu.tsx).
//
// Layout (rotation=1, 480×320 landscape):
//   ┌────────────────────────────────────────────────────────────────┐
//   │ AC LAUNCHER                            ● CONNECTED  (header)   │  56 px
//   ├────────────────────────────────────────────────────────────────┤
//   │ ┌────────────────────────────────────────────────────────────┐ │
//   │ │ AC COPILOT                                            ›    │ │  72 px
//   │ │ Real-time coaching overlay                                  │ │
//   │ └────────────────────────────────────────────────────────────┘ │
//   │ (12 px gap)                                                     │
//   │ ┌────────────────────────────────────────────────────────────┐ │  72 px
//   │ │ POCKET TECHNICIAN                                     ›    │ │
//   │ │ Saved setups manager                                        │ │
//   │ └────────────────────────────────────────────────────────────┘ │
//   │ (12 px gap)                                                     │
//   │ ┌────────────────────────────────────────────────────────────┐ │  72 px
//   │ │ SETUP EXCHANGE                                        ›    │ │
//   │ │ Community setups browser                                    │ │
//   │ └────────────────────────────────────────────────────────────┘ │
//   └────────────────────────────────────────────────────────────────┘
//
// Status pill is driven by `app_state_get()` via a 500 ms timer. The
// disconnect threshold (3 s, per issue #86 Part B3) is enforced in
// `main.cpp`'s WS state transitions which call `app_state_set(...)`; the
// pill simply mirrors whatever `app_state_t` is current. Tiles remain
// tappable even when disconnected — Parts C–E will gate dependent
// behavior on their own.

#include "ui/screen_launcher.h"

#include "ui/app_state.h"
#include "ui/nav.h"
#include "ui/tokens.h"

#include <Arduino.h>

namespace {

// --- Layout constants (landscape 480×320) ----------------------------------
constexpr int LAUNCHER_W      = 480;
constexpr int LAUNCHER_H      = 320;
constexpr int HEADER_H        = 56;
// Horizontal pad for the header and content column (breathing room on the
// left/right edges). Vertical pad is split out separately because the
// content area only has `LAUNCHER_H - HEADER_H = 264` px and the three
// 72 px tiles plus two 12 px gaps already consume 240 px — leaving exactly
// 24 px for top + bottom inset combined. Keeping a single 16 px pad on
// both axes overflows the column by 8 px and clips the bottom of the
// third tile (Cursor Bugbot on PR #91).
constexpr int CONTENT_PAD_H   = 16;
constexpr int CONTENT_PAD_V   = 12;   // 264 - 240 = 24 px → 12 px top + 12 px bottom
constexpr int TILE_H          = 72;
constexpr int TILE_GAP        = UI_GAP_TILES;       // 12 px (tokens.h)
constexpr int CHEVRON_W       = 18;
constexpr int STATUS_DOT_DIA  = 10;

// --- App identifiers -------------------------------------------------------
typedef enum {
    LAUNCHER_APP_AC_COPILOT = 0,
    LAUNCHER_APP_POCKET_TECH,
    LAUNCHER_APP_SETUP_EXCHANGE,
} launcher_app_t;

// --- Per-screen widget cache, owned by the screen via user_data -----------
struct launcher_ctx_t {
    lv_obj_t*  status_dot;     // colored dot in the header pill
    lv_obj_t*  status_label;   // "CONNECTED" / "DISCONNECTED" text
    lv_obj_t*  spinner;        // reconnect spinner (visible only when disconnected)
    lv_timer_t* poll_timer;    // 500 ms tick to refresh the pill
    app_state_t last_state;    // last value seen by the timer
    bool        first_render;  // true until the first apply_pill_state() call
};

// --- Helpers ---------------------------------------------------------------

// Apply the connected/disconnected look to the status pill widgets.
void apply_pill_state(launcher_ctx_t* ctx, app_state_t s) {
    const bool connected = (s == APP_CONNECTED || s == APP_LAUNCHER_IDLE);
    const lv_color_t dot_color = connected ? UI_ACCENT_GOLD : UI_ALERT_RED;
    const char*      pill_text = connected ? "CONNECTED" : "DISCONNECTED";
    if (ctx->status_dot) {
        lv_obj_set_style_bg_color(ctx->status_dot, dot_color, LV_PART_MAIN);
    }
    if (ctx->status_label) {
        lv_label_set_text(ctx->status_label, pill_text);
        lv_obj_set_style_text_color(
            ctx->status_label,
            connected ? UI_TX_PRIMARY : UI_ALERT_RED,
            LV_PART_MAIN);
    }
    if (ctx->spinner) {
        if (connected) {
            lv_obj_add_flag(ctx->spinner, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_clear_flag(ctx->spinner, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

void poll_state_cb(lv_timer_t* t) {
    auto* ctx = static_cast<launcher_ctx_t*>(t->user_data);
    if (!ctx) return;
    app_state_t now = app_state_get();
    if (ctx->first_render || now != ctx->last_state) {
        apply_pill_state(ctx, now);
        ctx->last_state    = now;
        ctx->first_render  = false;
    }
}

void on_screen_delete(lv_event_t* e) {
    auto* ctx = static_cast<launcher_ctx_t*>(lv_event_get_user_data(e));
    if (!ctx) return;
    if (ctx->poll_timer) {
        lv_timer_del(ctx->poll_timer);
        ctx->poll_timer = nullptr;
    }
    delete ctx;
}

// Placeholder factories for screens that arrive in Parts C–E. Each
// returns a screen with a centered "Coming soon" label so navigation
// works end-to-end on Part B alone. Parts C/D/E will replace these.
lv_obj_t* placeholder_screen(const char* title) {
    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* heading = lv_label_create(scr);
    lv_label_set_text(heading, title);
    lv_obj_set_style_text_color(heading, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(heading, LV_ALIGN_TOP_MID, 0, 32);

    lv_obj_t* body = lv_label_create(scr);
    lv_label_set_text(body, "Coming soon\nTap to return");
    lv_obj_set_style_text_color(body, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_set_style_text_align(body, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN);
    lv_obj_center(body);

    // Whole-screen tap returns to launcher.
    lv_obj_add_flag(scr, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(
        scr,
        [](lv_event_t*) { ui_nav_pop(); },
        LV_EVENT_CLICKED,
        nullptr);
    return scr;
}

lv_obj_t* ac_copilot_create(void)      { return placeholder_screen("AC COPILOT"); }
lv_obj_t* pocket_tech_create(void)     { return placeholder_screen("POCKET TECHNICIAN"); }
lv_obj_t* setup_exchange_create(void)  { return placeholder_screen("SETUP EXCHANGE"); }

void on_tile_clicked(lv_event_t* e) {
    auto app = static_cast<launcher_app_t>(
        reinterpret_cast<uintptr_t>(lv_event_get_user_data(e)));
    switch (app) {
        case LAUNCHER_APP_AC_COPILOT:
            ui_nav_push(ac_copilot_create);
            break;
        case LAUNCHER_APP_POCKET_TECH:
            ui_nav_push(pocket_tech_create);
            break;
        case LAUNCHER_APP_SETUP_EXCHANGE:
            ui_nav_push(setup_exchange_create);
            break;
    }
}

// Build one app tile. Returns the outer container so the caller can
// position it via grid/flex.
lv_obj_t* make_tile(lv_obj_t* parent,
                    const char* title,
                    const char* subtitle,
                    launcher_app_t app) {
    lv_obj_t* tile = lv_obj_create(parent);
    lv_obj_set_size(tile, lv_pct(100), TILE_H);
    lv_obj_set_style_bg_color(tile, UI_BG_PANEL, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(tile, UI_BG_PANEL_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_color(tile, UI_BORDER_SOFT, LV_PART_MAIN);
    lv_obj_set_style_border_opa(tile, UI_BORDER_SOFT_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(tile, 1, LV_PART_MAIN);
    lv_obj_set_style_radius(tile, UI_RADIUS_TILE, LV_PART_MAIN);
    lv_obj_set_style_pad_all(tile, 12, LV_PART_MAIN);
    lv_obj_clear_flag(tile, LV_OBJ_FLAG_SCROLLABLE);
    // Pressed-state visual feedback (Part A7): subtle tile background dim.
    lv_obj_set_style_bg_color(tile, UI_BG_HEADER, LV_PART_MAIN | LV_STATE_PRESSED);
    lv_obj_add_flag(tile, LV_OBJ_FLAG_CLICKABLE);

    // Title (top-left).
    lv_obj_t* title_lbl = lv_label_create(tile);
    lv_label_set_text(title_lbl, title);
    lv_obj_set_style_text_color(title_lbl, UI_TX_PRIMARY, LV_PART_MAIN);
    lv_obj_align(title_lbl, LV_ALIGN_TOP_LEFT, 0, 0);

    // Subtitle below title.
    lv_obj_t* sub_lbl = lv_label_create(tile);
    lv_label_set_text(sub_lbl, subtitle);
    lv_obj_set_style_text_color(sub_lbl, UI_TX_MUTED, LV_PART_MAIN);
    lv_obj_align(sub_lbl, LV_ALIGN_TOP_LEFT, 0, 22);

    // Right chevron in gold.
    lv_obj_t* chev = lv_label_create(tile);
    lv_label_set_text(chev, ">");
    lv_obj_set_style_text_color(chev, UI_ACCENT_GOLD, LV_PART_MAIN);
    lv_obj_align(chev, LV_ALIGN_RIGHT_MID, -4, 0);
    lv_obj_set_width(chev, CHEVRON_W);

    // Tap target floor: tile is 72 px tall × full content width — well
    // above the 60 px minimum from Part A7.
    lv_obj_add_event_cb(
        tile,
        on_tile_clicked,
        LV_EVENT_CLICKED,
        reinterpret_cast<void*>(static_cast<uintptr_t>(app)));

    return tile;
}

// Build the header strip (title + status pill). The pill widgets are
// stashed back into `ctx` so the poll timer can update them.
void make_header(lv_obj_t* parent, launcher_ctx_t* ctx) {
    lv_obj_t* header = lv_obj_create(parent);
    lv_obj_set_size(header, LAUNCHER_W, HEADER_H);
    lv_obj_align(header, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(header, UI_BG_HEADER, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(header, UI_BG_HEADER_OPA, LV_PART_MAIN);
    lv_obj_set_style_border_width(header, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(header, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_left(header, CONTENT_PAD_H, LV_PART_MAIN);
    lv_obj_set_style_pad_right(header, CONTENT_PAD_H, LV_PART_MAIN);
    lv_obj_set_style_pad_top(header, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_bottom(header, 0, LV_PART_MAIN);
    lv_obj_clear_flag(header, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t* brand = lv_label_create(header);
    lv_label_set_text(brand, "AC LAUNCHER");
    lv_obj_set_style_text_color(brand, UI_TX_PRIMARY, LV_PART_MAIN);
    // Letter-spacing approximation: LVGL 8.3 supports `text_letter_space`.
    lv_obj_set_style_text_letter_space(brand, 2, LV_PART_MAIN);
    lv_obj_align(brand, LV_ALIGN_LEFT_MID, 0, 0);

    // Right-aligned status pill: [dot] [label] [spinner-when-disconnected]
    lv_obj_t* pill = lv_obj_create(header);
    lv_obj_set_size(pill, 180, 32);
    lv_obj_align(pill, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_set_style_bg_opa(pill, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(pill, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(pill, 0, LV_PART_MAIN);
    lv_obj_clear_flag(pill, LV_OBJ_FLAG_SCROLLABLE);

    ctx->status_dot = lv_obj_create(pill);
    lv_obj_set_size(ctx->status_dot, STATUS_DOT_DIA, STATUS_DOT_DIA);
    lv_obj_set_style_radius(ctx->status_dot, LV_RADIUS_CIRCLE, LV_PART_MAIN);
    lv_obj_set_style_border_width(ctx->status_dot, 0, LV_PART_MAIN);
    lv_obj_align(ctx->status_dot, LV_ALIGN_LEFT_MID, 0, 0);

    ctx->status_label = lv_label_create(pill);
    lv_label_set_text(ctx->status_label, "DISCONNECTED");
    lv_obj_align(ctx->status_label, LV_ALIGN_LEFT_MID, STATUS_DOT_DIA + 8, 0);

    ctx->spinner = lv_spinner_create(pill, /*time=*/1000, /*arc length=*/60);
    lv_obj_set_size(ctx->spinner, 22, 22);
    lv_obj_align(ctx->spinner, LV_ALIGN_RIGHT_MID, 0, 0);
    lv_obj_add_flag(ctx->spinner, LV_OBJ_FLAG_HIDDEN);
}

}  // namespace

extern "C" lv_obj_t* launcher_create(void) {
    // ESP32 Arduino is built with -fno-exceptions, so `new` returns nullptr
    // on OOM rather than throwing. Guard so we don't crash on the very next
    // ctx-> dereference; ui_nav_push() refuses null factories. (CodeRabbit
    // P1 on PR #91.)
    auto* ctx = new launcher_ctx_t{};
    if (!ctx) {
        Serial.println("[fatal][ui] launcher ctx alloc failed");
        return nullptr;
    }
    // Use a dedicated `first_render` flag instead of casting an out-of-range
    // 0xFF to `app_state_t` (UB on -fshort-enums). (CodeRabbit P1 on PR #91.)
    ctx->first_render = true;

    lv_obj_t* scr = lv_obj_create(nullptr);
    lv_obj_set_style_bg_color(scr, UI_BG_BASE, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    // Free the context + timer when LVGL deletes the screen.
    lv_obj_add_event_cb(scr, on_screen_delete, LV_EVENT_DELETE, ctx);

    make_header(scr, ctx);

    // Content column under the header.
    lv_obj_t* col = lv_obj_create(scr);
    lv_obj_set_size(col, LAUNCHER_W - 2 * CONTENT_PAD_H,
                    LAUNCHER_H - HEADER_H - 2 * CONTENT_PAD_V);
    lv_obj_align(col, LV_ALIGN_TOP_MID, 0, HEADER_H + CONTENT_PAD_V);
    lv_obj_set_style_bg_opa(col, LV_OPA_TRANSP, LV_PART_MAIN);
    lv_obj_set_style_border_width(col, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(col, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_row(col, TILE_GAP, LV_PART_MAIN);
    lv_obj_set_flex_flow(col, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(col, LV_FLEX_ALIGN_START,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_clear_flag(col, LV_OBJ_FLAG_SCROLLABLE);

    make_tile(col, "AC COPILOT",
              "Real-time coaching overlay",
              LAUNCHER_APP_AC_COPILOT);
    make_tile(col, "POCKET TECHNICIAN",
              "Saved setups manager",
              LAUNCHER_APP_POCKET_TECH);
    make_tile(col, "SETUP EXCHANGE",
              "Community setups browser",
              LAUNCHER_APP_SETUP_EXCHANGE);

    // Initial render of the pill + start the 500 ms poll timer.
    apply_pill_state(ctx, app_state_get());
    ctx->last_state    = app_state_get();
    ctx->first_render  = false;
    ctx->poll_timer    = lv_timer_create(poll_state_cb, 500, ctx);

    return scr;
}
