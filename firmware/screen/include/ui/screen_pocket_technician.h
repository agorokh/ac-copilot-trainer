// Pocket Technician — issue #86 Part D.
//
// Real bidirectional setup picker. On screen-create the screen sends a
// `setup.list` request to the trainer; on tap-row it sends `setup.load`
// and renders a gold-pulse on success or a 3 s red toast on error.
//
// Public surface mirrors the AC Copilot screen: a `_create` factory plus
// per-message apply functions called from `main.cpp`'s WS dispatch.

#pragma once

#include <lvgl.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Build the screen. Triggers an async `setup.list` request via the WS
// out-queue (`pt_request_setup_list`) and renders a "Loading…" placeholder
// row until the result arrives.
lv_obj_t* screen_pocket_technician_create(void);

// Drop the cached setup list (rendered after `setup.list.result` arrives).
// Capacity is bounded; entries beyond capacity are silently dropped.
//
// `path` (optional) is the absolute setup INI path on disk. When the
// trainer reports it, the screen carries it in `PT_REQ_LOAD` so the
// Lua side can disambiguate same-basename files across track/layout
// folders (chatgpt-codex P1 on PR #91). Pass nullptr to keep the
// load request `name`-only (legacy behavior).
void screen_pocket_technician_clear_setups(void);
typedef struct {
    int32_t brake_bias;  // -1 if missing
    int32_t abs;
    int32_t tc;
    int32_t wing_f;
    int32_t wing_r;
} pt_setup_summary_t;

void screen_pocket_technician_add_setup(const char* name,
                                         const char* mtime_iso,
                                         int32_t best_ms,
                                         const char* path,
                                         const pt_setup_summary_t* summary);

// Update the meta bar from `state.snapshot topic="setup.active"` or from
// the `setup.list.result` envelope's car_*/track_* fields.
//
// Display names (`car_name`, `track_name`) are optional — when nullptr or
// empty, the meta bar falls back to the directory ID. Sending both lets
// the screen show "Porsche 911 GT3 R 2016" in place of "ks_porsche_911_gt3r_2016".
void screen_pocket_technician_set_identity(const char* car_id, const char* car_name,
                                            const char* car_brand,
                                            const char* track_id, const char* track_name);
void screen_pocket_technician_set_active_setup(const char* name);

// Result of the most recent `setup.load` (called from main.cpp's WS dispatch).
// `ok=true` triggers a gold border pulse on the active row; `ok=false`
// shows the 3 s red toast with `error` (or "load failed" when null).
void screen_pocket_technician_apply_load_ack(bool ok, const char* name, const char* error);

// ---- Out-queue (screen → trainer) ----------------------------------------
// The screen module never writes to the WS directly; it stages a request
// in a small bounded out-queue that `main.cpp` drains every loop tick.
// This keeps the LVGL event callbacks free of any networking dependencies.

typedef enum {
    PT_REQ_NONE = 0,
    PT_REQ_LIST,        // {"v":1,"type":"setup.list"}
    PT_REQ_LOAD,        // {"v":1,"type":"setup.load","name":"<name>"}
} pt_request_kind_t;

typedef struct {
    pt_request_kind_t kind;
    char              name[64];   // valid for PT_REQ_LOAD only
    char              path[160];  // optional unique disambiguator; "" if unknown
} pt_request_t;

// Pop the next pending request, or PT_REQ_NONE. Drained from main.cpp.
pt_request_t screen_pocket_technician_pop_request(void);

#ifdef __cplusplus
}
#endif
