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
    require(shown.size() == sizeof(rows) / sizeof(rows[0]), "every operator setup is listed");
    // The four scientist setups share a prefix and a suffix; what the driver sees must still
    // tell them apart.
    for (size_t i = 0; i < shown.size(); ++i) {
        for (size_t j = i + 1; j < shown.size(); ++j) {
            require(shown[i] != shown[j], "every saved setup row shows a distinguishable name");
        }
    }
    capture("06c-pocket-technician-operator-setups-scrolled");

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
        setup_exchange();
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
