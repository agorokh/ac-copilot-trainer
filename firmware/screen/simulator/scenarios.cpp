// Compile the firmware screens unchanged; drive LVGL's real pointer/renderer.
#include <lvgl.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <string.h>

#include "ui/app_state.h"
#include "ui/nav.h"
#include "ui/screen_launcher.h"
#include "ui/screen_ac_copilot.h"
#include "ui/screen_pocket_technician.h"
#include "ui/screen_setup_exchange.h"

uint32_t simulator_time_ms = 1;

namespace {
constexpr int WIDTH = 320;
constexpr int HEIGHT = 480;
lv_color_t framebuffer[WIDTH * HEIGHT];
lv_color_t draw_buffer[WIDTH * 40];
lv_disp_draw_buf_t display_buffer;
bool pointer_pressed = false;
lv_point_t pointer_position{};
int assertions = 0;
std::filesystem::path output;
std::vector<std::string> captures;

void require(bool value, const char* description) {
    if (!value) throw std::runtime_error(description);
    std::cout << "PASS: " << description << '\n';
    ++assertions;
}

void flush(lv_disp_drv_t* display, const lv_area_t* area, lv_color_t* color) {
    for (int y = area->y1; y <= area->y2; ++y) {
        for (int x = area->x1; x <= area->x2; ++x, ++color) {
            if (x >= 0 && x < WIDTH && y >= 0 && y < HEIGHT) framebuffer[y * WIDTH + x] = *color;
        }
    }
    lv_disp_flush_ready(display);
}

void read_pointer(lv_indev_drv_t*, lv_indev_data_t* data) {
    data->point = pointer_position;
    data->state = pointer_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

void tick(int ms = 150) {
    for (int elapsed = 0; elapsed < ms; elapsed += 5) {
        simulator_time_ms += 5;
        lv_tick_inc(5);
        lv_timer_handler();
    }
    lv_refr_now(nullptr);
}

lv_obj_t* find_label(lv_obj_t* root, const char* text, bool prefix = false) {
    if (lv_obj_check_type(root, &lv_label_class)) {
        const char* rendered = lv_label_get_text(root);
        if (prefix ? strncmp(rendered, text, strlen(text)) == 0 : strcmp(rendered, text) == 0) return root;
    }
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(root); ++i) {
        if (auto* found = find_label(lv_obj_get_child(root, i), text, prefix)) return found;
    }
    return nullptr;
}

bool has_label(const char* text) { return find_label(lv_scr_act(), text) != nullptr; }

void assert_no_missing_glyphs(lv_obj_t* root) {
    if (!root) return;
    if (lv_obj_check_type(root, &lv_label_class)) {
        const char* rendered = lv_label_get_text(root);
        const lv_font_t* font = lv_obj_get_style_text_font(root, LV_PART_MAIN);
        require(font != nullptr, "every label has a bound LVGL font");
        uint32_t idx = 0;
        while (rendered && rendered[idx] != '\0') {
            uint32_t cp = _lv_txt_encoded_next(rendered, &idx);
            if (cp == 0 || cp == '\n' || cp == '\r' || cp == '\t') continue;
            uint32_t next_idx = idx;
            uint32_t cp_next = _lv_txt_encoded_next(rendered, &next_idx);
            lv_font_glyph_dsc_t dsc{};
            if (!lv_font_get_glyph_dsc(font, &dsc, cp, cp_next)) {
                throw std::runtime_error(
                    std::string("missing glyph U+") + std::to_string(cp) +
                    " in label: " + rendered);
            }
        }
    }
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(root); ++i) {
        assert_no_missing_glyphs(lv_obj_get_child(root, i));
    }
}

void tap(const char* text) {
    tick();
    auto* label = find_label(lv_scr_act(), text);
    require(label != nullptr, text);
    lv_area_t bounds;
    lv_obj_get_coords(label, &bounds);
    pointer_position.x = (bounds.x1 + bounds.x2) / 2;
    pointer_position.y = (bounds.y1 + bounds.y2) / 2;
    require(pointer_position.x >= 0 && pointer_position.x < WIDTH &&
            pointer_position.y >= 0 && pointer_position.y < HEIGHT, "tap target is on screen");
    pointer_pressed = true;
    tick(60);
    pointer_pressed = false;
    tick(140);
}

void capture(const char* name) {
    tick();
    assert_no_missing_glyphs(lv_scr_act());
    assert_no_missing_glyphs(lv_layer_top());
    std::string filename = std::string(name) + ".ppm";
    std::ofstream image(output / filename, std::ios::binary);
    image.exceptions(std::ios::failbit | std::ios::badbit);
    image << "P6\n" << WIDTH << ' ' << HEIGHT << "\n255\n";
    for (auto pixel : framebuffer) {
        lv_color32_t rgb;
        rgb.full = lv_color_to32(pixel);
        image.put(static_cast<char>(rgb.ch.red));
        image.put(static_cast<char>(rgb.ch.green));
        image.put(static_cast<char>(rgb.ch.blue));
    }
    image.close();
    captures.push_back(filename);
}

// Tap a label by the start of its text (a truncated label renders the start plus "...").
void tap_prefix(const char* prefix) {
    tick();
    auto* label = find_label(lv_scr_act(), prefix, true);
    require(label != nullptr, prefix);
    // Recursive: the label's own parent (a row) does not scroll; the list above it does.
    lv_obj_scroll_to_view_recursive(label, LV_ANIM_OFF);
    tick();
    lv_area_t bounds;
    lv_obj_get_coords(label, &bounds);
    pointer_position.x = (bounds.x1 + bounds.x2) / 2;
    pointer_position.y = (bounds.y1 + bounds.y2) / 2;
    require(pointer_position.x >= 0 && pointer_position.x < WIDTH &&
            pointer_position.y >= 0 && pointer_position.y < HEIGHT, "tap target is on screen");
    lv_obj_t* hit = lv_indev_search_obj(lv_scr_act(), &pointer_position);
    require(hit == label || hit == lv_obj_get_parent(label), "the tap lands on the intended row");
    pointer_pressed = true;
    tick(60);
    pointer_pressed = false;
    tick(140);
}

void back() {
    tap("< BACK");
    require(ui_nav_at_root(), "Back returns to launcher through pointer hit testing");
}

void initialize() {
    lv_init();
    lv_disp_draw_buf_init(&display_buffer, draw_buffer, nullptr, WIDTH * 40);
    static lv_disp_drv_t display;
    lv_disp_drv_init(&display);
    display.hor_res = WIDTH;
    display.ver_res = HEIGHT;
    display.draw_buf = &display_buffer;
    display.flush_cb = flush;
    lv_disp_drv_register(&display);
    static lv_indev_drv_t pointer;
    lv_indev_drv_init(&pointer);
    pointer.type = LV_INDEV_TYPE_POINTER;
    pointer.read_cb = read_pointer;
    lv_indev_drv_register(&pointer);
    ui_nav_init();
    app_state_set(APP_CONNECTED);
    ui_nav_push(launcher_create);
    tick();
}

void copilot() {
    tap("AC COPILOT");
    require(ui_nav_depth() == 2, "Copilot opens through pointer hit testing");
    require(has_label("WAIT"), "no coaching data shows WAIT");
    require(!has_label("0"), "no coaching data does not invent a zero speed");
    capture("02-copilot-wait");
    coaching_snapshot_t snapshot{};
    strcpy(snapshot.primary_line, "BRAKE");
    strcpy(snapshot.secondary_line, "Brake in a straight line");
    strcpy(snapshot.corner_label, "T3");
    strcpy(snapshot.current_corner_label, "T2");
    strcpy(snapshot.approach_corner_label, "T3");
    strcpy(snapshot.action, "BRAKE");
    strcpy(snapshot.kind, "brake");
    strcpy(snapshot.sub_state, "approaching");
    strcpy(snapshot.target_phase, "brake_onset");
    strcpy(snapshot.target_provenance, "reference");
    snapshot.target_speed_kmh = 85;
    snapshot.current_speed_kmh = 146;
    snapshot.dist_to_brake_m = 125;
    snapshot.target_available = true;
    snapshot.current_speed_available = true;
    snapshot.has_data = true;
    snapshot.progress_pct = 48;
    screen_ac_copilot_apply_snapshot(&snapshot);
    tick();
    require(has_label("BRAKE") && has_label("LIVE"), "explicit BRAKE and fresh LIVE state render");
    capture("03-copilot-brake");
    tick(6000);
    require(has_label("STALE") && !has_label("146"), "stale coaching hides old speed");
    capture("04-copilot-stale");
    strcpy(snapshot.action, "UPSHIFT");
    strcpy(snapshot.kind, "line");
    snapshot.dist_to_brake_m = 1250;
    screen_ac_copilot_apply_snapshot(&snapshot);
    tick();
    require(has_label("UPSHIFT") && !has_label("LIFT"), "line-kind UPSHIFT is not misclassified as LIFT");
    auto* distance = find_label(lv_scr_act(), "1250");
    require(distance != nullptr, "four-digit brake distance renders");
    const lv_font_t* font = lv_obj_get_style_text_font(distance, LV_PART_MAIN);
    require(lv_txt_get_width("1250", 4, font, lv_obj_get_style_text_letter_space(distance, LV_PART_MAIN),
                            LV_TEXT_FLAG_NONE) <= lv_obj_get_width(distance),
            "four-digit distance fits its actual rendered font and label width");
    capture("05-copilot-upshift");
    back();
}

void pocket_technician() {
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity("ks_porsche_911_gt3_r_2016", "Porsche 911 GT3 R 2016",
                                         "Porsche", "magione", "Magione");
    tap("POCKET TECHNICIAN");
    require(ui_nav_depth() == 2, "Pocket Technician opens through pointer");
    screen_pocket_technician_clear_setups();
    pt_setup_summary_t summary{64, 2, 3, -1, 8};
    screen_pocket_technician_add_setup("Simulator baseline", "2026-10-16", 102183,
                                      "C:/simulator/baseline.ini", &summary);
    screen_pocket_technician_finish_setup_list();
    screen_pocket_technician_apply_live_electronics(63.5f, 3, 12, 2, 12, true, "");
    capture("06-pocket-technician");
    tap("Simulator baseline");
    bool load = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD && strcmp(request.name, "Simulator baseline") == 0 &&
            strcmp(request.path, "C:/simulator/baseline.ini") == 0) load = true;
    }
    require(load, "Pocket Technician emits setup.load with exact name and path");
    screen_pocket_technician_apply_load_ack(true, "Simulator baseline", "C:/simulator/baseline.ini", nullptr);
    screen_pocket_technician_set_sidecar_link_up(0);
    tick();
    tap("Simulator baseline");
    bool offline_mutation = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD || request.kind == PT_REQ_SPINNER_SET) offline_mutation = true;
    }
    require(!offline_mutation, "offline Pocket Technician refuses setup mutation");
    capture("07-pocket-technician-offline");
    back();
}

void setup_exchange() {
    screen_setup_exchange_set_sidecar_link_up(1);
    screen_setup_exchange_set_context("ks_porsche_911_gt3_r_2016", "Porsche 911 GT3 R 2016",
                                      "magione", "Magione");
    tap("SETUP EXCHANGE");
    require(ui_nav_depth() == 2, "Setup Exchange opens through pointer");
    screen_setup_exchange_clear_results();
    screen_setup_exchange_add_result(86, "Simulator community setup", "Fixture driver", 125,
                                      "ks_porsche_911_gt3_r_2016", "magione");
    screen_setup_exchange_finish_results();
    tick();
    require(has_label("BY Fixture driver"), "Setup Exchange shows the community author");
    capture("08-setup-exchange");
    tap("Simulator community setup");
    bool download = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_setup_exchange_pop_request();
        if (request.kind == SE_REQ_NONE) break;
        if (request.kind == SE_REQ_DOWNLOAD && request.setup_id == 86) download = true;
    }
    require(download, "Setup Exchange pointer emits download request for selected setup");
    screen_setup_exchange_apply_download_ack(false, 86, "Simulator community setup", nullptr, "Offline fixture");
    tick();
    require(has_label("Download failed"), "download failure is visibly reported");
    capture("09-setup-exchange-error");
    screen_setup_exchange_set_sidecar_link_up(0);
    tap("Simulator community setup");
    require(screen_setup_exchange_pop_request().kind == SE_REQ_NONE, "offline Setup Exchange refuses download");
    screen_setup_exchange_set_sidecar_link_up(1);
    screen_setup_exchange_apply_search_error("Start an Assetto Corsa practice session");
    tick();
    require(has_label("Search failed"), "missing CSP service is a visible search error");
    capture("10-setup-exchange-unavailable");
    tap("REFRESH");
    bool retry_search = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_setup_exchange_pop_request();
        if (request.kind == SE_REQ_NONE) break;
        if (request.kind == SE_REQ_SEARCH &&
            strcmp(request.car_id, "ks_porsche_911_gt3_r_2016") == 0 &&
            strcmp(request.track_id, "magione") == 0) retry_search = true;
    }
    require(retry_search, "refresh retries the active car/track through CSP");
    screen_setup_exchange_clear_results();
    screen_setup_exchange_add_result(86, "Simulator community setup", "Fixture driver", 125,
                                      "ks_porsche_911_gt3_r_2016", "magione");
    screen_setup_exchange_finish_results();
    tap("Simulator community setup");
    bool retry_download = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_setup_exchange_pop_request();
        if (request.kind == SE_REQ_NONE) break;
        if (request.kind == SE_REQ_DOWNLOAD && request.setup_id == 86) retry_download = true;
    }
    require(retry_download, "download can be retried after a failure");
    constexpr const char* installed_path = "C:/simulator/Simulator community setup.ini";
    screen_setup_exchange_apply_download_ack(true, 86, "Simulator community setup.ini", installed_path, nullptr);
    tick(3500);  // Let the earlier search-error toast expire before image review.
    require(find_label(lv_scr_act(), "Installed: ", true) != nullptr,
            "successful install is visible even when the filename ellipsizes");
    capture("11-setup-exchange-installed");
    back();
    screen_pocket_technician_set_sidecar_link_up(1);
    tap("POCKET TECHNICIAN");
    screen_pocket_technician_clear_setups();
    pt_setup_summary_t summary{64, 2, 3, -1, 8};
    screen_pocket_technician_add_setup("Simulator community setup", "2026-10-16", -1,
                                      installed_path, &summary);
    screen_pocket_technician_finish_setup_list();
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    tap("Simulator community setup");
    require(screen_pocket_technician_pop_request().kind == PT_REQ_NONE,
            "installed setup cannot load without fresh pits/reset permission");
    screen_pocket_technician_apply_live_electronics(64, 3, 12, 2, 12, true, "");
    tap("Simulator community setup");
    bool installed_load = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD && strcmp(request.path, installed_path) == 0) installed_load = true;
    }
    require(installed_load, "Pocket Technician loads the exact installed community path");
    screen_pocket_technician_apply_load_ack(true, "Simulator community setup", installed_path, nullptr);
    tick();
    require(has_label("ACTIVE: Simulator community setup"), "installed setup is visibly active in Pocket Technician");
    capture("12-community-setup-active");
    back();
}

lv_obj_t* child_label_with_prefix(lv_obj_t* parent, const char* prefix) {
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(parent); ++i) {
        lv_obj_t* child = lv_obj_get_child(parent, i);
        if (lv_obj_check_type(child, &lv_label_class) &&
            strncmp(lv_label_get_text(child), prefix, strlen(prefix)) == 0) {
            return child;
        }
    }
    return nullptr;
}

// #86 operator report 2026-10-18: on the rig the saved-setup names wrapped over the
// BB/ABS/TC line. The earlier scenario only ever used "Simulator baseline". These are the
// operator's actual Magione rows exactly as the trainer's setup.list returned them.
void pocket_technician_operator_setups() {
    struct row_t {
        const char* name;
        const char* path;
        pt_setup_summary_t summary;
    };
    const row_t rows[] = {
        {"Copilot_Balanced_Fast", "C:/setups/magione/Copilot_Balanced_Fast.ini", {63, 7, 3, 1, 16}},
        {"Copilot_Scientist_42b69c28227df065_802860d58233d33f",
         "C:/setups/magione/Copilot_Scientist_42b69c28227df065_802860d58233d33f.ini", {63, 7, 3, 1, 15}},
        {"Copilot_Scientist_5c9552785d5327fd_802860d58233d33f",
         "C:/setups/magione/Copilot_Scientist_5c9552785d5327fd_802860d58233d33f.ini", {63, 7, 3, 1, 15}},
        {"Copilot_Scientist_9eedecc46de76540_802860d58233d33f",
         "C:/setups/magione/Copilot_Scientist_9eedecc46de76540_802860d58233d33f.ini", {63, 7, 3, 1, 15}},
        {"Copilot_Scientist_bb0141b4f314cb7b_802860d58233d33f",
         "C:/setups/magione/Copilot_Scientist_bb0141b4f314cb7b_802860d58233d33f.ini", {63, 7, 3, 1, 15}},
        {"last", "C:/setups/generic/last.ini", {63, 7, 3, 1, 16}},
        {"pocket-20260629-133817", "C:/setups/generic/pocket-20260629-133817.ini", {59, 8, -1, 1, 20}},
    };
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity("ks_porsche_911_gt3_r_2016", "Porsche 911 GT3 R 2016",
                                         "Porsche", "magione", "Magione");
    tap("POCKET TECHNICIAN");
    require(ui_nav_depth() == 2, "Pocket Technician opens for the operator's saved setups");
    screen_pocket_technician_clear_setups();
    for (const auto& row : rows) {
        screen_pocket_technician_add_setup(row.name, "", -1, row.path, &row.summary);
    }
    screen_pocket_technician_finish_setup_list();
    screen_pocket_technician_apply_live_electronics(63.5f, 3, 12, 2, 12, true, "");
    tick();
    capture("06b-pocket-technician-operator-setups");
    lv_obj_t* first = find_label(lv_scr_act(), "Copilot_Balanced_F", true);
    require(first != nullptr, "the saved setup list is on screen");
    lv_obj_t* list = lv_obj_get_parent(lv_obj_get_parent(first));
    std::vector<std::string> shown;
    for (int page = 0; page < 2; ++page) {
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(list); ++i) {
        lv_obj_t* setup_row = lv_obj_get_child(list, i);
        lv_obj_t* chips = child_label_with_prefix(setup_row, "BB:");
        if (!chips) continue;  // headings and spinner rows
        lv_obj_t* name = lv_obj_get_child(setup_row, 0);
        // A truncated label shows the start of the name followed by "...".
        std::string visible = lv_label_get_text(name);
        if (visible.size() >= 3 && visible.compare(visible.size() - 3, 3, "...") == 0) {
            visible.resize(visible.size() - 3);
        }
        bool real_name = false;
        for (const auto& row : rows) {
            if (!visible.empty() && strncmp(row.name, visible.c_str(), visible.size()) == 0) real_name = true;
        }
        require(real_name, "each row shows the start of one of the operator's setup names");
        // The list scrolls: bring the row into view before measuring it on screen.
        lv_obj_scroll_to_view(setup_row, LV_ANIM_OFF);
        tick();
        lv_area_t name_area, chips_area;
        lv_obj_get_coords(name, &name_area);
        lv_obj_get_coords(chips, &chips_area);
        const lv_font_t* font = lv_obj_get_style_text_font(name, LV_PART_MAIN);
        require(lv_area_get_height(&name_area) <= 2 * lv_font_get_line_height(font),
                "a long setup name stays within two lines");
        require(name_area.y2 < chips_area.y1, "a setup name never overlaps its BB/ABS/TC line");
        shown.emplace_back(lv_label_get_text(name));
    }
        if (page == 0) tap_prefix("SETUPS >");
    }
    require(shown.size() == sizeof(rows) / sizeof(rows[0]), "every operator setup is listed");
    // The four scientist setups share a prefix and a suffix; what the driver sees must still
    // tell them apart.
    for (size_t i = 0; i < shown.size(); ++i) {
        for (size_t j = i + 1; j < shown.size(); ++j) {
            require(shown[i] != shown[j], "every saved setup row shows a distinguishable name");
        }
    }
    capture("06c-pocket-technician-operator-setups-scrolled");
    tap_prefix("< SETUPS");

    // Loading a long-named setup: the request must carry the FULL name (the row cache used to
    // cut it at 47 characters), and the ACTIVE line must stay on one line above LIVE CAR.
    const row_t& scientist = rows[1];
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {
    }
    tap_prefix("Copilot_Scientist_42b6");
    bool full_name_load = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD && strcmp(request.name, scientist.name) == 0 &&
            strcmp(request.path, scientist.path) == 0) full_name_load = true;
    }
    require(full_name_load, "a long setup name is requested in full, not cut at 47 characters");
    screen_pocket_technician_apply_load_ack(true, scientist.name, scientist.path, nullptr);
    tick();
    lv_obj_t* active = find_label(lv_scr_act(), "ACTIVE: Copilot_Scientist_42b6", true);
    require(active != nullptr, "the loaded long-named setup is shown as ACTIVE");
    lv_obj_t* live = find_label(lv_scr_act(), "LIVE CAR", true);
    require(live != nullptr, "the live car line is still shown");
    lv_area_t active_area, live_area;
    lv_obj_get_coords(active, &active_area);
    lv_obj_get_coords(live, &live_area);
    require(lv_area_get_height(&active_area) <=
                lv_font_get_line_height(lv_obj_get_style_text_font(active, LV_PART_MAIN)),
            "a long ACTIVE setup name stays on one line");
    require(active_area.y2 < live_area.y1, "the ACTIVE line never overlaps LIVE CAR");
    capture("06d-pocket-technician-long-name-active");
    back();
}

// #86: Live Spa pit verification exposed two real-rig regressions:
// 1. `se.acstuff.club` community setup `PORSCHE GT3 ’16 Hotlap V1` (U+2019) rendered a missing-glyph
//    tofu box against the ASCII-subsetted LVGL fonts, while Pocket Technician must still preserve
//    the unfolded wire/filesystem name for `setup.load` <-> `setup.load.ack` correlation.
// 2. Live CSP spinners (`SETUP VALUES`, per-corner `Bump LF`, degree units) must render cleanly and
//    update immediately on confirmed `setup.spinner.set.ack`.
void pocket_technician_spinners_and_utf8() {
    constexpr const char* utf8_name = "PORSCHE GT3 \xe2\x80\x99" "16 Hotlap V1";
    constexpr const char* utf8_path = "C:/setups/spa/PORSCHE GT3 \xe2\x80\x99" "16 Hotlap V1.ini";
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity(
        "ks_porsche_911_gt3_r_2016",
        "Porsche 911 GT3 R \xe2\x80\x99" "16",
        "Porsche",
        "spa",
        "Circuit de Spa-Francorchamps \xe2\x80\x93 GP");
    screen_pocket_technician_set_setup_capability(true, "", "csp");
    tap("POCKET TECHNICIAN");
    require(ui_nav_depth() == 2, "Pocket Technician opens for live spinners and UTF-8 titles");
    screen_pocket_technician_clear_spinners();
    screen_pocket_technician_add_spinner("FRONT_BIAS", "Brake Bias", 68.0f, 50.0f, 80.0f, 1.0f, "%", true, 1.0f);
    screen_pocket_technician_add_spinner("DAMP_BUMP_LF", "Bump LF", 8.0f, 0.0f, 20.0f, 1.0f, "", true, 1.0f);
    screen_pocket_technician_add_spinner("CAMBER_LF", "Camber LF", -3.2f, -5.0f, 0.0f, 0.1f, "\xc2\xb0", true, 1.0f);
    screen_pocket_technician_finish_spinner_list();
    screen_pocket_technician_clear_setups();
    pt_setup_summary_t summary{68, 8, 3, 1, 20};
    screen_pocket_technician_add_setup(utf8_name, "2026-11-10", -1, utf8_path, &summary);
    screen_pocket_technician_finish_setup_list();
    screen_pocket_technician_apply_live_electronics(68.0f, 3, 12, 8, 12, true, "");
    tick();
    require(has_label("SETUP VALUES"), "Pocket Technician renders live SETUP VALUES heading");
    require(has_label("Brake Bias") && has_label("68%"), "Brake Bias spinner renders value and unit");
    require(has_label("Bump LF"), "disambiguated per-corner spinner label renders");
    lv_obj_t* camber_val = find_label(lv_scr_act(), "-3.2deg");
    require(camber_val != nullptr, "UTF-8 degree symbol folds cleanly to ASCII deg");
    const lv_font_t* camber_font = lv_obj_get_style_text_font(camber_val, LV_PART_MAIN);
    lv_area_t camber_area;
    lv_obj_get_coords(camber_val, &camber_area);
    require(lv_area_get_height(&camber_area) <= lv_font_get_line_height(camber_font),
            "multi-char spinner value+unit stays on one line without vertical wrap");
    require(lv_txt_get_width("-3.2deg", 7, camber_font, 0, LV_TEXT_FLAG_NONE) <= lv_obj_get_width(camber_val),
            "multi-char spinner value+unit fits inside its value slot width");
    require(find_label(lv_scr_act(), "TRACK: Circuit de Spa-Francorchamps - GP", true) != nullptr,
            "UTF-8 en-dash in track name folds cleanly to ASCII hyphen");
    require(has_label("911 GT3 R '16"), "UTF-8 apostrophe in car model folds cleanly to ASCII");
    capture("06e-pocket-technician-spinners-utf8");

    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    lv_obj_t* bias_lbl = find_label(lv_scr_act(), "Brake Bias");
    require(bias_lbl != nullptr, "Brake Bias row is present");
    lv_obj_t* bias_row = lv_obj_get_parent(bias_lbl);
    lv_obj_t* plus_lbl = find_label(bias_row, "+");
    require(plus_lbl != nullptr, "Brake Bias row has + button");
    lv_area_t plus_bounds;
    lv_obj_get_coords(plus_lbl, &plus_bounds);
    pointer_position.x = (plus_bounds.x1 + plus_bounds.x2) / 2;
    pointer_position.y = (plus_bounds.y1 + plus_bounds.y2) / 2;
    pointer_pressed = true;
    tick(60);
    pointer_pressed = false;
    tick(140);
    bool spinner_set = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_SPINNER_SET &&
            strcmp(request.section, "FRONT_BIAS") == 0 &&
            request.value == 69.0f) {
            spinner_set = true;
        }
    }
    require(spinner_set, "tapping + on Brake Bias queues setup.spinner.set for 69");
    screen_pocket_technician_apply_spinner_ack(true, true, "FRONT_BIAS", 69.0f, nullptr);
    tick();
    require(has_label("69%"), "confirmed spinner ack updates displayed value immediately");

    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    tap_prefix("PORSCHE GT3 '16 Hotlap V1");
    bool exact_utf8_load = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD &&
            strcmp(request.name, utf8_name) == 0 &&
            strcmp(request.path, utf8_path) == 0) {
            exact_utf8_load = true;
        }
    }
    require(exact_utf8_load, "UTF-8 setup displays folded ASCII while preserving exact wire name/path");
    screen_pocket_technician_apply_load_ack(true, utf8_name, utf8_path, nullptr);
    tick();
    require(has_label("ACTIVE: PORSCHE GT3 '16 Hotlap V1"),
            "loaded UTF-8 setup displays folded ASCII in ACTIVE banner");
    screen_pocket_technician_clear_spinners();
    screen_pocket_technician_finish_spinner_list();
    back();
}

void pocket_technician_prescriptions() {
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity("ks_porsche_911_gt3_r_2016", "Porsche 911 GT3 R 2016",
        "Porsche", "spa", "Spa-Francorchamps");
    tap("POCKET TECHNICIAN");
    screen_pocket_technician_clear_spinners();
    screen_pocket_technician_clear_setups();
    screen_pocket_technician_finish_setup_list();
    std::string request_id;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_GET) request_id = request.request_id;
    }
    require(!request_id.empty(), "Pocket Technician requests a prescription on open");
    pt_prescription_change_t changes[4] = {
        {"PRESSURE_LF", 24, 23, -1}, {"PRESSURE_RF", 24, 23, -1},
        {"PRESSURE_LR", 24, 25, 1}, {"PRESSURE_RR", 24, 25, 1}};
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-a", "proposed",
        "LF hot pressure high", "Laps 3-4: LF 29.8 psi; target 27-29", "", changes, 1);
    capture("06f-pocket-prescription-proposed");
    require(has_label("COLD PRESSURE"), "pit prescription card renders");
    require(has_label("LF 24.0 -> 23.0 psi (-1.0)"), "card shows affected corner and cold psi delta");
    tap("ACCEPT");
    tap("ACCEPT");
    require(has_label("Awaiting decision receipt"), "Accept is pending consent, never applied state");
    int accepts = 0;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_ACCEPT) {
            ++accepts;
            require(strcmp(request.prescription_id, "rx-956-a") == 0 && request.request_id == request_id,
                "Accept carries prescription and response epoch identifiers");
        }
    }
    require(accepts == 1, "duplicate touch bounce queues exactly one Accept");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-a", "accepted_unverified",
        "LF hot pressure high", "Laps 3-4: LF 29.8 psi; target 27-29", "", changes, 1);
    tick();
    require(has_label("Accepted - awaiting setup readback"), "accepted_unverified remains explicit without readback");
    require(!has_label("Applied - setup readback verified"), "Accept receipt cannot imply applied setup");
    capture("06g-pocket-prescription-unverified");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-a", "verified_applied",
        "LF cold trim applied", "Setup readback: LF 23.0 psi", "", changes, 1);
    tick();
    require(has_label("Applied - setup readback verified"), "only verified sidecar response renders applied state");

    auto refresh = [&]() {
        tap("REFRESH");
        std::string next_id;
        for (;;) {
            auto request = screen_pocket_technician_pop_request();
            if (request.kind == PT_REQ_NONE) break;
            if (request.kind == PT_REQ_PRESCRIPTION_GET) next_id = request.request_id;
        }
        require(!next_id.empty() && next_id != request_id, "refresh advances response epoch");
        request_id = next_id;
    };
    refresh();
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-b", "proposed",
        "Stabilized pressure deviations", "Laps 3-4: measured hot psi; known compound", "", changes, 4);
    capture("06h-pocket-prescription-four-corners");
    auto* accept_label = find_label(lv_scr_act(), "ACCEPT");
    lv_area_t accept_bounds;
    lv_obj_get_coords(accept_label, &accept_bounds);
    require(accept_bounds.y2 < HEIGHT, "four-corner card keeps Accept visible without scrolling");
    tap("ACCEPT");
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, false, "Outside pit box");
    tap("ACCEPT");
    bool outside_accept = false;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_ACCEPT) outside_accept = true;
    }
    require(!outside_accept, "pit exit removes queued Accept and prevents retried Accept");
    capture("06i-pocket-prescription-pit-exit");
    tap("REJECT");
    tap("REJECT");
    int rejects = 0;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_REJECT) ++rejects;
        require(request.kind != PT_REQ_SPINNER_SET && request.kind != PT_REQ_PRESCRIPTION_ACCEPT,
            "Reject never stages a setup mutation");
    }
    require(rejects == 1, "Reject remains safe outside pit and deduplicates bounce");

    const std::string old_request = request_id;
    screen_pocket_technician_invalidate_live_state();
    screen_pocket_technician_apply_prescription(old_request.c_str(), "rx-956-b", "proposed",
        "Old session", "Must never restore after session reset", "", changes, 4);
    tick();
    require(!has_label("COLD PRESSURE"), "late reply cannot restore prior-session card");
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_GET) request_id = request.request_id;
    }
    require(request_id != old_request, "session invalidation requests a new prescription epoch");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-trap", "abstained",
        "Cold out-lap - insufficient stabilized flying-lap observations for a meaningful cold pressure trim",
        "Laps 1-1: warming tyres; measured pressure is not stabilized. Extra long text must remain bounded inside this card.",
        "No change: need two stabilized flying laps and a known compound target window. Long reason stays inside the card.",
        nullptr, 0);
    tick();
    require(has_label("Abstained - no setup change"), "trap card makes abstention explicit");
    tap("ACCEPT");
    require(screen_pocket_technician_pop_request().kind == PT_REQ_NONE,
        "abstention Accept cannot stage any decision or setup write");
    capture("06j-pocket-prescription-abstention-truncation");
    auto* title = find_label(lv_scr_act(), "COLD PRESSURE");
    auto* card = lv_obj_get_parent(title);
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(card); ++i) {
        auto* child = lv_obj_get_child(card, i);
        if (!lv_obj_check_type(child, &lv_label_class)) continue;
        require(lv_obj_get_width(child) <= lv_obj_get_content_width(card),
            "prescription text width stays inside card bounds");
        require(lv_label_get_long_mode(child) == LV_LABEL_LONG_DOT,
            "prescription labels use bounded ellipsis rather than overflow");
    }
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-malformed", "proposed",
        "Malformed reply", "Missing pressure changes", "", nullptr, 0);
    tick();
    require(has_label("Invalid pressure changes - refresh required"),
        "malformed proposed card fails closed instead of leaving prior actionable state");
    tap("ACCEPT");
    bool malformed_accept = false;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_ACCEPT) malformed_accept = true;
    }
    require(!malformed_accept, "malformed card cannot queue Accept");

    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-stale", "proposed",
        "LF hot pressure high", "Laps 3-4 measured pressure", "", changes, 1);
    tick(1600);
    screen_pocket_technician_set_sidecar_link_up(1);
    tap("ACCEPT");
    require(screen_pocket_technician_pop_request().kind == PT_REQ_NONE,
        "stale telemetry cannot authorize a prescription Accept");
    screen_pocket_technician_set_sidecar_link_up(0);
    screen_pocket_technician_set_sidecar_link_up(1);
    std::string reconnect_id;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_GET) reconnect_id = request.request_id;
    }
    require(!reconnect_id.empty() && reconnect_id != request_id,
        "reconnect starts a fresh response epoch");
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-stale", "verified_applied",
        "Old reply after reconnect", "Stale reply must be ignored", "", changes, 1);
    tick();
    require(!has_label("Old reply after reconnect"), "reconnect ignores a delayed prior-link reply");
    back();
}

void pocket_technician_prescription_capacity() {
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity("ks_porsche_911_gt3_r_2016", "Porsche 911 GT3 R 2016",
        "Porsche", "spa", "Spa-Francorchamps");
    tap("POCKET TECHNICIAN");
    screen_pocket_technician_clear_setups();
    screen_pocket_technician_clear_spinners();
    std::string request_id;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_GET) request_id = request.request_id;
    }
    require(!request_id.empty(), "capacity scenario has a fresh prescription response epoch");
    auto memory = [](const char* stage) {
        lv_mem_monitor_t monitor{};
        lv_mem_monitor(&monitor);
        std::cout << "MEMORY " << stage << ": total=" << monitor.total_size
            << " free=" << monitor.free_size << " largest=" << monitor.free_biggest_size
            << " used_pct=" << static_cast<int>(monitor.used_pct)
            << " frag_pct=" << static_cast<int>(monitor.frag_pct) << std::endl;
        return monitor;
    };
    memory("Pocket Technician empty");
    for (int i = 0; i < PT_MAX_SPINNERS; ++i) {
        char section[32], label[32];
        snprintf(section, sizeof(section), "CAPACITY_%02d", i + 1);
        snprintf(label, sizeof(label), "Spinner %02d", i + 1);
        screen_pocket_technician_add_spinner(section, label, 24, 16, 40, 1, "psi", true, 1);
    }
    screen_pocket_technician_finish_spinner_list();
    memory("12 spinner rows");
    pt_setup_summary_t summary{63, 2, 3, 1, 20};
    for (int i = 0; i < 64; ++i) {
        char name[PT_SETUP_NAME_MAX], path[PT_SETUP_PATH_MAX];
        snprintf(name, sizeof(name), "Capacity setup %02d", i + 1);
        if (i == 0 || i == 63) snprintf(name, sizeof(name), "Capacity shared");
        snprintf(path, sizeof(path), "C:/simulator/capacity/setup_%02d.ini", i + 1);
        screen_pocket_technician_add_setup(name, "2026-11-12", 102183, path, &summary);
        if ((i + 1) % 16 == 0) memory(name);
    }
    screen_pocket_technician_finish_setup_list();
    tick();
    require(find_label(lv_scr_act(), "Capacity shared") != nullptr,
        "maximum cached state renders first saved setup page");
    require(find_label(lv_scr_act(), "Spinner 01") != nullptr,
        "maximum cached state renders first spinner page");
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    pt_prescription_change_t changes[4] = {
        {"PRESSURE_LF", 24, 23, -1}, {"PRESSURE_RF", 24, 23, -1},
        {"PRESSURE_LR", 24, 25, 1}, {"PRESSURE_RR", 24, 25, 1}};
    screen_pocket_technician_apply_prescription(request_id.c_str(), "rx-956-capacity", "proposed",
        "Stabilized pressure deviations", "Laps 3-4: measured hot psi; known compound", "", changes, 4);
    tick();
    auto monitor = memory("64 setups + 12 spinners + four-corner prescription");
    require(monitor.free_size > 0 && monitor.free_biggest_size > 0,
        "maximum cached state and card retain usable space in the real 64 KiB LVGL pool");
    require(find_label(lv_scr_act(), "Capacity shared") != nullptr &&
            find_label(lv_scr_act(), "Spinner 01") != nullptr && has_label("COLD PRESSURE"),
        "four-corner card coexists with both maximum-capacity caches");
    capture("06k-pocket-prescription-maximum-capacity");
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    tap_prefix("Capacity shared");
    bool first_setup_request = false;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD && strcmp(request.path, "C:/simulator/capacity/setup_01.ini") == 0)
            first_setup_request = true;
    }
    require(first_setup_request, "first same-name setup stages its exact path before paging");
    uint32_t minimum_free = monitor.free_size;
    int setups_seen = 0, spinners_seen = 0;
    for (int page = 0; page < 16; ++page) {
        for (int i = 0; i < 4; ++i) {
            char name[PT_SETUP_NAME_MAX];
            snprintf(name, sizeof(name), "Capacity setup %02d", page * 4 + i + 1);
            if ((page == 0 && i == 0) || (page == 15 && i == 3))
                snprintf(name, sizeof(name), "Capacity shared");
            require(find_label(lv_scr_act(), name) != nullptr,
                "every cached saved setup is reachable through bounded pages");
            ++setups_seen;
        }
        auto page_memory = memory("saved-setup page");
        minimum_free = std::min(minimum_free, page_memory.free_size);
        if (page < 15) tap_prefix("SETUPS >");
    }
    for (int page = 0; page < 3; ++page) {
        for (int i = 0; i < 4; ++i) {
            char name[32];
            snprintf(name, sizeof(name), "Spinner %02d", page * 4 + i + 1);
            require(find_label(lv_scr_act(), name) != nullptr,
                "every cached spinner is reachable through bounded pages");
            ++spinners_seen;
        }
        auto page_memory = memory("spinner page");
        minimum_free = std::min(minimum_free, page_memory.free_size);
        if (page < 2) tap_prefix("CONTROLS >");
    }
    require(setups_seen == 64 && spinners_seen == 12,
        "pagination preserves access to all64 setups and all12 controls");
    std::cout << "MEMORY minimum_free_across_maximum_pages=" << minimum_free << std::endl;
    // LVGL 8.3's max_used omits realloc accounting; report measured TLSF free
    // space at each page boundary rather than mislabel it a transient peak.
    memory("after all maximum pages");
    require(lv_mem_test() == LV_RES_OK, "maximum-capacity page traversal preserves allocator integrity");
    require(minimum_free >= 8192, "maximum rendered pages retain at least8 KiB for transient LVGL work");
    auto* last_setup = find_label(lv_scr_act(), "Capacity shared");
    lv_obj_scroll_to_view_recursive(lv_obj_get_parent(last_setup), LV_ANIM_OFF);
    tick();
    capture("06l-pocket-prescription-maximum-last-page");
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    tap_prefix("Capacity shared");
    bool last_setup_request = false;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_LOAD && strcmp(request.path, "C:/simulator/capacity/setup_64.ini") == 0)
            last_setup_request = true;
    }
    require(last_setup_request, "last-page setup retains its exact load path");
    tap_prefix("< SETUPS");
    screen_pocket_technician_apply_load_ack(true, "Capacity shared",
        "C:/simulator/capacity/not_requested.ini", nullptr);
    require(screen_pocket_technician_pop_request().kind == PT_REQ_NONE,
        "unmatched same-name path cannot consume a pending load or trigger refresh");
    screen_pocket_technician_apply_load_ack(true, "Capacity shared",
        "C:/simulator/capacity/setup_01.ini", nullptr);
    bool first_ack_path = false;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_SPINNER_LIST && strcmp(request.path, "C:/simulator/capacity/setup_01.ini") == 0)
            first_ack_path = true;
    }
    require(first_ack_path, "first same-name ack correlates its own path after all paging");
    screen_pocket_technician_apply_load_ack(true, "Capacity shared",
        "C:/simulator/capacity/setup_64.ini", nullptr);
    tick();
    require(find_label(lv_scr_act(), "ACTIVE: Capacity shared") != nullptr,
        "matching setup ack remains correlated after its row is paged out");
    bool last_ack_path = false;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_SPINNER_LIST && strcmp(request.path, "C:/simulator/capacity/setup_64.ini") == 0)
            last_ack_path = true;
    }
    require(last_ack_path, "last same-name ack preserves independent path correlation after paging");
    back();
    screen_pocket_technician_clear_setups();
    screen_pocket_technician_clear_spinners();
}

void prescription_reject_epoch_review_regression() {
    pt_prescription_change_t change{"PRESSURE_LF", 24, 23, -1};
    auto open_card = [&](const char* prescription_id) {
        screen_pocket_technician_set_sidecar_link_up(1);
        screen_pocket_technician_set_identity("review-car", "Review car", "", "review-track", "Review track");
        tap("POCKET TECHNICIAN");
        screen_pocket_technician_clear_spinners();
        screen_pocket_technician_clear_setups();
        screen_pocket_technician_finish_setup_list();
        std::string epoch;
        for (;;) {
            auto request = screen_pocket_technician_pop_request();
            if (request.kind == PT_REQ_NONE) break;
            if (request.kind == PT_REQ_PRESCRIPTION_GET) epoch = request.request_id;
        }
        require(!epoch.empty(), "review regression starts from a real GET response epoch");
        screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
        screen_pocket_technician_apply_prescription(epoch.c_str(), prescription_id, "proposed",
            "LF hot pressure high", "Laps 3-4: LF 29.8 psi; target 27-29", "", &change, 1);
        tick();
        return epoch;
    };
    int refresh_rejects = 0, refresh_gets = 0, refresh_mutations = 0;
    bool refresh_original_epoch = true;
    std::string refresh_epoch = open_card("rx-review-refresh"), new_refresh_epoch;
    tap("REJECT");
    tap("REFRESH");
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_REJECT) {
            ++refresh_rejects;
            refresh_original_epoch = refresh_original_epoch && request.request_id == refresh_epoch;
        }
        if (request.kind == PT_REQ_PRESCRIPTION_GET) {
            ++refresh_gets;
            new_refresh_epoch = request.request_id;
        }
        if (request.kind == PT_REQ_PRESCRIPTION_ACCEPT || request.kind == PT_REQ_SPINNER_SET) ++refresh_mutations;
    }
    const bool refresh_pending_preserved = has_label("Refreshing pressure evidence");
    std::cout << "REVIEW5878205548 reject_then_refresh: rejects=" << refresh_rejects
        << " gets=" << refresh_gets << " mutations=" << refresh_mutations
        << " original_epoch=" << refresh_original_epoch
        << " refresh_pending=" << refresh_pending_preserved << std::endl;
    capture("06m-review-reject-refresh");
    back();

    int disconnect_rejects = 0, reconnect_gets = 0, disconnect_mutations = 0;
    bool disconnect_original_epoch = true;
    const std::string disconnect_epoch = open_card("rx-review-disconnect");
    tap("REJECT");
    screen_pocket_technician_set_sidecar_link_up(0);
    tick();
    const bool offline_pending = has_label("Awaiting decision receipt");
    capture("06n-review-reject-disconnect");
    screen_pocket_technician_set_sidecar_link_up(1);
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_REJECT) {
            ++disconnect_rejects;
            disconnect_original_epoch = disconnect_original_epoch && request.request_id == disconnect_epoch;
        }
        if (request.kind == PT_REQ_PRESCRIPTION_GET) ++reconnect_gets;
        if (request.kind == PT_REQ_PRESCRIPTION_ACCEPT || request.kind == PT_REQ_SPINNER_SET) ++disconnect_mutations;
    }
    const bool reconnect_pending_preserved = has_label("Refreshing pressure evidence");
    std::cout << "REVIEW5878205548 reject_then_disconnect: rejects=" << disconnect_rejects
        << " gets=" << reconnect_gets << " mutations=" << disconnect_mutations
        << " original_epoch=" << disconnect_original_epoch
        << " offline_pending=" << offline_pending
        << " reconnect_refresh_pending=" << reconnect_pending_preserved << std::endl;
    std::ofstream result(output / "review-5878205548-results.json");
    result << "{\"reject_then_refresh\":{\"rejects\":" << refresh_rejects
        << ",\"gets\":" << refresh_gets << ",\"mutations\":" << refresh_mutations
        << ",\"refresh_pending\":" << refresh_pending_preserved
        << "},\"reject_then_disconnect\":{\"rejects\":" << disconnect_rejects
        << ",\"gets\":" << reconnect_gets << ",\"mutations\":" << disconnect_mutations
        << ",\"offline_pending\":" << offline_pending
        << ",\"reconnect_refresh_pending\":" << reconnect_pending_preserved << "}}\n";
    result.close();
    back();
    require(refresh_rejects == 1 && refresh_gets == 1 && refresh_mutations == 0 &&
            refresh_original_epoch && new_refresh_epoch != refresh_epoch && refresh_pending_preserved,
        "original Reject+Refresh sequence logs one safe Reject and preserves the new GET epoch");
    require(disconnect_rejects == 1 && reconnect_gets == 1 && disconnect_mutations == 0 &&
            disconnect_original_epoch && !offline_pending && reconnect_pending_preserved,
        "original Reject+disconnect sequence retains safe Reject without a stale pending receipt");
}

void prescription_pending_epoch_ownership() {
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity("epoch-car", "Epoch car", "", "epoch-track", "Epoch track");
    tap("POCKET TECHNICIAN");
    std::string epoch;
    for (;;) {
        auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.kind == PT_REQ_PRESCRIPTION_GET) epoch = request.request_id;
    }
    pt_prescription_change_t change{"PRESSURE_LF", 24, 23, -1};
    auto proposal = [&](const std::string& response_epoch, const char* id) {
        screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
        screen_pocket_technician_apply_prescription(response_epoch.c_str(), id, "proposed",
            "LF hot pressure high", "Laps 3-4 measured hot pressure", "", &change, 1);
        tick();
    };
    proposal(epoch, "rx-epoch-old-accept");
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    tap("ACCEPT");
    tap("REFRESH");
    const auto old_accept = screen_pocket_technician_pop_request();
    require(old_accept.kind == PT_REQ_PRESCRIPTION_GET,
        "stale queued Accept is dropped before returning the new GET");
    epoch = old_accept.request_id;
    require(has_label("Refreshing pressure evidence"),
        "dropping old Accept leaves new GET refresh ownership intact");
    proposal(epoch, "rx-epoch-old-reject");
    tap("REJECT");
    tap("REFRESH");
    const auto safe_reject = screen_pocket_technician_pop_request();
    require(safe_reject.kind == PT_REQ_PRESCRIPTION_REJECT && safe_reject.request_id == epoch,
        "safe old Reject keeps its original display epoch");
    const auto next_get = screen_pocket_technician_pop_request();
    require(next_get.kind == PT_REQ_PRESCRIPTION_GET && next_get.request_id != epoch,
        "old Reject does not replace the newer refresh request");
    epoch = next_get.request_id;
    proposal(epoch, "rx-epoch-current-decision");
    tap("REJECT");
    screen_pocket_technician_set_setup_capability(false, "Outside pit box", "csp");
    const auto current_reject = screen_pocket_technician_pop_request();
    require(current_reject.kind == PT_REQ_PRESCRIPTION_REJECT && current_reject.request_id == epoch,
        "pit transition retains the current safe Reject");
    require(has_label("Awaiting decision receipt"),
        "queue drain does not clear a current in-flight decision's receipt state");
    screen_pocket_technician_apply_prescription(safe_reject.request_id, "rx-epoch-old-reject", "rejected",
        "Old rejected prescription", "Late old-epoch receipt", "", &change, 1);
    tick();
    require(has_label("Awaiting decision receipt") && !has_label("Old rejected prescription"),
        "late old Reject response cannot clear or replace the newer decision");
    capture("06o-review-current-decision-epoch");
    screen_pocket_technician_apply_prescription(epoch.c_str(), "rx-epoch-current-decision", "rejected",
        "Pressure change rejected", "No setup write", "", &change, 1);
    tick();
    require(!has_label("Awaiting decision receipt") && has_label("rejected"),
        "matching current receipt alone settles the current decision");
    back();
}

void pocket_technician_ai_bench_routing() {
    screen_pocket_technician_set_sidecar_link_up(1);
    screen_pocket_technician_set_identity("bench-car", "Bench car", "", "bench-track", "Bench track");
    tap("POCKET TECHNICIAN");
    screen_pocket_technician_clear_setups();
    screen_pocket_technician_clear_spinners();
    screen_pocket_technician_finish_setup_list();
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    require(!screen_pocket_technician_bench_active(), "956 AI bench starts disabled");
    screen_pocket_technician_add_spinner("PRESSURE_LF", "Pressure LF", 24, 20, 35, 1, "psi", true, 1);
    screen_pocket_technician_finish_spinner_list();
    pt_setup_summary_t setup_summary{63, 2, 3, 1, 20};
    screen_pocket_technician_add_setup("Bench baseline", "", -1, "C:/bench/baseline.ini", &setup_summary);
    screen_pocket_technician_finish_setup_list();
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    tap_prefix("+");
    tap_prefix("Bench baseline");
    require(screen_pocket_technician_set_bench_status(true, "bench-run-956"), "explicit bench status is accepted");
    tick();
    require(find_label(lv_scr_act(), "956 AI BENCH |", true) != nullptr,
        "956 AI BENCH is visible before any card response");
    const auto get = screen_pocket_technician_pop_request();
    require(get.kind == PT_REQ_PRESCRIPTION_GET && get.ai_bench &&
            strcmp(get.bench_run_id, "bench-run-956") == 0,
        "active bench GET carries distinct routing and exact run id");
    require(screen_pocket_technician_pop_request().kind == PT_REQ_NONE,
        "arming bench discards previously queued manual spinner and setup mutations");
    tap("+");
    tap("Bench baseline");
    require(screen_pocket_technician_pop_request().kind == PT_REQ_NONE,
        "bench keeps manual values visible but locks spinner and saved-setup actions");
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    pt_prescription_change_t change{"PRESSURE_LF", 24, 23, -1};
    screen_pocket_technician_apply_prescription(get.request_id, "ordinary", "proposed",
        "Ordinary response must not appear", "No bench authority", "", &change, 1);
    tick();
    require(!has_label("Ordinary response must not appear"), "ordinary card cannot enter bench mode");
    screen_pocket_technician_apply_prescription_mode(get.request_id, "wrong-run", "proposed",
        "Wrong bench run", "Mismatched run authority", "", &change, 1, "ai_bench", "another-run");
    tick();
    require(!has_label("Wrong bench run"), "bench card must match the explicitly armed run");
    screen_pocket_technician_apply_prescription_mode(get.request_id, "bench-card", "proposed",
        "AI BENCH: LF pressure high", "Laps 3-4 measured hot pressure", "", &change, 1,
        "ai_bench", "bench-run-956");
    tick();
    require(has_label("956 AI BENCH") && has_label("AI BENCH: LF pressure high"),
        "bench card visibly distinguishes AI bench from ordinary pressure advice");
    capture("06p-ai-bench-proposed");
    tap("ACCEPT");
    const auto accept = screen_pocket_technician_pop_request();
    require(accept.kind == PT_REQ_PRESCRIPTION_ACCEPT && accept.ai_bench &&
            strcmp(accept.bench_run_id, "bench-run-956") == 0 &&
            strcmp(accept.prescription_id, "bench-card") == 0,
        "bench Accept can only leave through the bench namespace with its run");
    require(screen_pocket_technician_set_bench_status(true, "bench-run-956"), "same status is idempotent");
    require(has_label("Awaiting decision receipt"), "repeated status does not clear an in-flight decision");
    screen_pocket_technician_apply_prescription_mode(get.request_id, "bench-card", "verified_applied",
        "AI BENCH: verified trim", "All cold pressures read back", "", &change, 1,
        "ai_bench", "bench-run-956");
    tick();
    require(has_label("Applied - setup readback verified"), "bench applied state still requires matching readback response");
    capture("06q-ai-bench-verified");
    tap("REFRESH");
    const auto next_get = screen_pocket_technician_pop_request();
    screen_pocket_technician_apply_live_electronics(63, 3, 12, 2, 12, true, "");
    screen_pocket_technician_apply_prescription_mode(next_get.request_id, "bench-pending", "proposed",
        "AI BENCH: pending trim", "Measured evidence", "", &change, 1, "ai_bench", "bench-run-956");
    tick();
    tap("ACCEPT");
    screen_pocket_technician_set_sidecar_link_up(0);
    tick();
    require(!screen_pocket_technician_bench_active() &&
            strcmp(screen_pocket_technician_bench_run_id(), "") == 0,
        "disconnect immediately forgets bench authority");
    bool leaked_bench = false;
    for (;;) {
        const auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        if (request.ai_bench) leaked_bench = true;
    }
    require(!leaked_bench && !has_label("956 AI BENCH"), "disconnect revokes queued trial requests and visible active card");
    screen_pocket_technician_set_sidecar_link_up(1);
    const auto ordinary_get = screen_pocket_technician_pop_request();
    require(ordinary_get.kind == PT_REQ_PRESCRIPTION_GET && !ordinary_get.ai_bench,
        "reconnect returns to ordinary GET without automatic bench rearm");
    screen_pocket_technician_apply_prescription_mode(ordinary_get.request_id, "bench-forged", "proposed",
        "Bench must never become ordinary", "Wrong namespace", "", &change, 1, "ai_bench", "bench-run-956");
    tick();
    require(!has_label("Bench must never become ordinary"), "ordinary mode cannot redeem a bench card");
    screen_pocket_technician_apply_prescription(ordinary_get.request_id, "inactive", "abstained",
        "No pressure change", "", "Pressure experiment inactive", nullptr, 0);
    tick();
    require(has_label("Pressure experiment inactive") && has_label("COLD PRESSURE"),
        "normal disabled experiment behavior is restored after disconnect");
    capture("06r-ai-bench-disarmed");
    require(screen_pocket_technician_set_bench_status(true, "bench-run-session"),
        "a new trial requires explicit rearm");
    screen_pocket_technician_invalidate_live_state();
    require(!screen_pocket_technician_bench_active(), "session reset immediately disarms bench routing");
    while (screen_pocket_technician_pop_request().kind != PT_REQ_NONE) {}
    require(screen_pocket_technician_set_bench_status(true, "bench-run-scope"),
        "scope trial is explicitly armed");
    screen_pocket_technician_set_identity("changed-car", "Changed car", "", nullptr, nullptr);
    require(!screen_pocket_technician_bench_active(), "actual car identity change revokes bench mode");
    for (;;) {
        const auto request = screen_pocket_technician_pop_request();
        if (request.kind == PT_REQ_NONE) break;
        require(!request.ai_bench, "scope change cannot retain a queued trial request");
    }
    require(!screen_pocket_technician_set_bench_status(true, ""), "empty run id fails closed");
    require(!screen_pocket_technician_bench_active(), "malformed status never arms a trial");
    back();
    screen_pocket_technician_clear_setups();
    screen_pocket_technician_clear_spinners();
}

void setup_exchange_utf8_community_titles() {
    screen_setup_exchange_set_sidecar_link_up(1);
    screen_setup_exchange_set_context(
        "ks_porsche_911_gt3_r_2016",
        "Porsche 911 GT3 R \xe2\x80\x99" "16",
        "nurburgring",
        "N\xc3\xbcrburgring \xe2\x80\x93 GP");
    tap("SETUP EXCHANGE");
    require(ui_nav_depth() == 2, "Setup Exchange opens for UTF-8 community titles");
    screen_setup_exchange_clear_results();
    screen_setup_exchange_add_result(
        991,
        "PORSCHE GT3 \xe2\x80\x99" "16 Hotlap V1",
        "Caf\xc3\xa9 \xe2\x80\x9cPro\xe2\x80\x9d",
        108,
        "ks_porsche_911_gt3_r_2016",
        "nurburgring");
    screen_setup_exchange_finish_results();
    tick();
    require(has_label("TRACK: Nurburgring - GP"), "Setup Exchange folds UTF-8 track name");
    require(has_label("PORSCHE GT3 '16 Hotlap V1"),
            "Setup Exchange folds U+2019 apostrophe cleanly without tofu");
    require(has_label("BY Cafe \"Pro\""), "Setup Exchange folds accented and curly-quoted author");
    capture("08c-setup-exchange-utf8");
    while (screen_setup_exchange_pop_request().kind != SE_REQ_NONE) {}
    tap("PORSCHE GT3 '16 Hotlap V1");
    bool utf8_download = false;
    for (int i = 0; i < 12; ++i) {
        auto request = screen_setup_exchange_pop_request();
        if (request.kind == SE_REQ_NONE) break;
        if (request.kind == SE_REQ_DOWNLOAD && request.setup_id == 991) utf8_download = true;
    }
    require(utf8_download, "tapping folded UTF-8 Setup Exchange row downloads setup_id 991");
    screen_setup_exchange_apply_download_ack(
        true,
        991,
        "PORSCHE GT3 \xe2\x80\x99" "16 Hotlap V1.ini",
        "C:/simulator/PORSCHE GT3 16 Hotlap V1.ini",
        nullptr);
    tick();
    require(find_label(lv_scr_act(), "Installed: PORSCHE GT3 '16", true) != nullptr,
            "Setup Exchange install status folds UTF-8 filename cleanly");
    capture("08d-setup-exchange-utf8-installed");
    back();
}

// #86: Magione + 911 GT3 R has zero community setups (measured: service total=0). Say what
// was searched instead of a bare "No setups found".
void setup_exchange_empty_for_track() {
    screen_setup_exchange_set_sidecar_link_up(1);
    screen_setup_exchange_set_context("ks_porsche_911_gt3_r_2016", "Porsche 911 GT3 R 2016",
                                      "magione", "Magione");
    tap("SETUP EXCHANGE");
    require(ui_nav_depth() == 2, "Setup Exchange opens for an empty track search");
    screen_setup_exchange_clear_results();
    screen_setup_exchange_finish_results();
    tick();
    require(!has_label("Loading..."), "an empty result never leaves the list saying Loading");
    require(find_label(lv_scr_act(), "No community setups for this car at Magione", true) != nullptr,
            "an empty search names the car and track it searched");
    capture("08b-setup-exchange-empty-track");
    back();
}

void report() {
    std::ofstream result(output / "results.json");
    result.exceptions(std::ios::failbit | std::ios::badbit);
    result << "{\"passed\":true,\"assertions\":" << assertions
           << ",\"lvgl\":\"" << LVGL_VERSION_MAJOR << '.' << LVGL_VERSION_MINOR << '.' << LVGL_VERSION_PATCH
           << "\",\"captures\":[";
    for (size_t i = 0; i < captures.size(); ++i) {
        if (i) result << ',';
        result << '"' << captures[i] << '"';
    }
    result << "]}\n";
    result.close();
}
}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::runtime_error("Supply an output directory");
        output = argv[1];
        std::filesystem::create_directories(output);
        initialize();
        require(has_label("CONNECTED"), "launcher reports connected");
        capture("01-launcher");
        copilot();
        pocket_technician();
        pocket_technician_operator_setups();
        pocket_technician_spinners_and_utf8();
        pocket_technician_prescriptions();
        pocket_technician_prescription_capacity();
        prescription_reject_epoch_review_regression();
        prescription_pending_epoch_ownership();
        pocket_technician_ai_bench_routing();
        setup_exchange();
        setup_exchange_utf8_community_titles();
        setup_exchange_empty_for_track();
        app_state_set(APP_DISCONNECTED);
        tick(600);
        require(has_label("DISCONNECTED"), "launcher shows disconnected");
        capture("13-disconnected");
        report();
        std::cout << "Verified " << assertions << " assertions using production UI and fonts\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
