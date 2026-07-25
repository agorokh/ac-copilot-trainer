// NVS persistence — issue #677 Part A.

#include "ui/persist.h"

#include "ui/nav.h"
#include "ui/screen_ac_copilot.h"
#include "ui/screen_debug.h"
#include "ui/screen_pocket_technician.h"
#include "ui/screen_setup_exchange.h"

#include <Arduino.h>
#include <Preferences.h>

namespace {

Preferences prefs;
bool opened = false;

constexpr const char* NS = "acscreen";
constexpr const char* KEY_SCREEN = "screen";
constexpr const char* KEY_SE_SORT = "se_sort";

void ensure_open() {
    if (opened) return;
    // Read-write; false = do not wipe the namespace on first open.
    prefs.begin(NS, /*readOnly=*/false);
    opened = true;
}

bool valid_screen(uint8_t v) {
    return v <= static_cast<uint8_t>(UI_SCREEN_DEBUG);
}

bool valid_sort(uint8_t v) {
    return v <= static_cast<uint8_t>(SE_SORT_NAME_ASC);
}

}  // namespace

extern "C" void ui_persist_begin(void) {
    ensure_open();
}

extern "C" ui_screen_id_t ui_persist_get_screen(void) {
    ensure_open();
    uint8_t v = prefs.getUChar(KEY_SCREEN, static_cast<uint8_t>(UI_SCREEN_LAUNCHER));
    if (!valid_screen(v)) return UI_SCREEN_LAUNCHER;
    return static_cast<ui_screen_id_t>(v);
}

extern "C" void ui_persist_set_screen(ui_screen_id_t id) {
    ensure_open();
    if (!valid_screen(static_cast<uint8_t>(id))) return;
    // Skip a redundant commit so tile re-taps don't thrash NVS wear.
    if (prefs.getUChar(KEY_SCREEN, 0xFF) == static_cast<uint8_t>(id)) return;
    prefs.putUChar(KEY_SCREEN, static_cast<uint8_t>(id));
}

extern "C" se_sort_t ui_persist_get_se_sort(void) {
    ensure_open();
    uint8_t v = prefs.getUChar(KEY_SE_SORT, static_cast<uint8_t>(SE_SORT_DOWNLOADS_DESC));
    if (!valid_sort(v)) return SE_SORT_DOWNLOADS_DESC;
    return static_cast<se_sort_t>(v);
}

extern "C" void ui_persist_set_se_sort(se_sort_t sort) {
    ensure_open();
    if (!valid_sort(static_cast<uint8_t>(sort))) return;
    if (prefs.getUChar(KEY_SE_SORT, 0xFF) == static_cast<uint8_t>(sort)) return;
    prefs.putUChar(KEY_SE_SORT, static_cast<uint8_t>(sort));
}

extern "C" void ui_persist_restore_screen(void) {
    const ui_screen_id_t id = ui_persist_get_screen();
    switch (id) {
        case UI_SCREEN_AC_COPILOT:
            ui_nav_push(screen_ac_copilot_create);
            break;
        case UI_SCREEN_POCKET_TECH:
            ui_nav_push(screen_pocket_technician_create);
            break;
        case UI_SCREEN_SETUP_EXCHANGE:
            ui_nav_push(screen_setup_exchange_create);
            break;
        case UI_SCREEN_DEBUG:
            ui_nav_push(screen_debug_create);
            break;
        case UI_SCREEN_LAUNCHER:
        default:
            break;
    }
}
