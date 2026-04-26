// AC Copilot Rig Screen — Phase-2 firmware (LVGL 8.3 path, default).
//
// Phase-1 raw-Arduino_GFX status screen is preserved behind
// `#define PHASE1_FALLBACK 1` for one release in case the LVGL path needs
// a quick rollback. The default build (PHASE1_FALLBACK 0) brings up
// LVGL on top of the Arduino_Canvas + AXS15231B QSPI flush model
// established in PR #83 and adds touch via the AXS15231B's I²C
// secondary at 0x3B. See:
//   docs/01_Vault/AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
//   docs/01_Vault/AcCopilotTrainer/03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md
//
// WiFi + WebSocket + auto-ping logic is unchanged from PR #83; only the
// UI surface was replaced. On WS connect/disconnect the LVGL UI sees the
// transition through `app_state_set(APP_CONNECTED|APP_DISCONNECTED)`.

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

#include "board/JC3248W535_GFX.h"
#include "wifi_secrets.h"  // WIFI_SSID, WIFI_PASSWORD          (secrets/)
#include "sidecar.h"       // SIDECAR_HOST/PORT/PATH/TOKEN/CLIENT_ID (secrets/)

// ---------------------------------------------------------------------------
// PHASE1_FALLBACK: 1 → keep the original raw-GFX status screen (PR #83).
// 0 → bring up LVGL + touch (Phase 2). Default 0 from issue #86.
// ---------------------------------------------------------------------------
#ifndef PHASE1_FALLBACK
#define PHASE1_FALLBACK 0
#endif

#if PHASE1_FALLBACK == 0
#include <lvgl.h>
#include <esp_heap_caps.h>   // heap_caps_malloc / MALLOC_CAP_SPIRAM
#include "board/JC3248W535_Touch.h"
#include "ui/app_state.h"
#include "ui/nav.h"
#include "ui/screen_ac_copilot.h"
#include "ui/screen_launcher.h"
#include "ui/screen_pocket_technician.h"
#endif

using namespace websockets;

// We keep two pointers to the same display object: `gfx` for Arduino_GFX
// behaviour (begin/setRotation/draw primitives) and `gfx_canvas` for the
// LVGL flush path (which calls Arduino_Canvas::flush()). The factory
// returns Arduino_Canvas* directly — see JC3248W535_GFX.h — so neither
// pointer requires a downcast and a future change to the factory return
// type will surface as a compile error rather than UB. The boot-time
// dimensional sanity check below is kept as defence-in-depth in case the
// factory is ever swapped to a different Arduino_Canvas-derived surface.
// (Copilot + CodeRabbit + sourcery reviews on PR #91.)
static Arduino_GFX*    gfx        = nullptr;
static Arduino_Canvas* gfx_canvas = nullptr;
static WebsocketsClient ws;

// -- Screen layout (rotation=1 -> 480x320 landscape) -------------------------

static constexpr int SCREEN_W = 480;
static constexpr int SCREEN_H = 320;

#if PHASE1_FALLBACK
// A small palette (RGB565). Phase 1 draws directly with Arduino_GFX.
// If LVGL is reintroduced later, re-check byte ordering vs LV_COLOR_16_SWAP.
static constexpr uint16_t COL_BG     = 0x0000;  // black
static constexpr uint16_t COL_FG     = 0xFFFF;  // white
static constexpr uint16_t COL_DIM    = 0x7BEF;  // grey
static constexpr uint16_t COL_OK     = 0x07E0;  // green
static constexpr uint16_t COL_WARN   = 0xFD20;  // orange
static constexpr uint16_t COL_ERR    = 0xF800;  // red
static constexpr uint16_t COL_BTN_BG = 0x001F;  // blue
static constexpr uint16_t COL_BTN_FG = 0xFFFF;

// Row Y positions with 12px pad.
static constexpr int PAD        = 12;
static constexpr int ROW_TITLE  = 8;
static constexpr int ROW_SUB    = 42;
static constexpr int ROW_WIFI   = 80;
static constexpr int ROW_WS     = 112;
static constexpr int ROW_HOST   = 144;
static constexpr int ROW_ERR    = 180;
static constexpr int ROW_H      = 22;    // height of one status row's clear rect

static constexpr int BTN_X = (SCREEN_W - 300) / 2;
static constexpr int BTN_Y = 220;
static constexpr int BTN_W = 300;
static constexpr int BTN_H = 72;
#endif  // PHASE1_FALLBACK

// -- State -------------------------------------------------------------------

enum class WifiState : uint8_t { Idle, Connecting, Connected, Failed };
enum class WsState   : uint8_t { Idle, Connecting, Open, AuthRejected, Closed, Error };

static WifiState wifi_state = WifiState::Idle;
static WsState   ws_state   = WsState::Idle;
static String    last_error;

#if PHASE1_FALLBACK
static WifiState last_painted_wifi = (WifiState)0xFF;
static WsState   last_painted_ws   = (WsState)0xFF;
static String    last_painted_err  = String("\x01");  // sentinel
#endif

static uint32_t wifi_retry_at   = 0;
static uint32_t ws_retry_at     = 0;
static uint32_t ws_backoff_ms   = 1000;    // 1s -> 30s
static constexpr uint32_t WS_BACKOFF_MAX_MS = 30000;
static uint32_t demo_next_at    = 0;
static constexpr uint32_t DEMO_INTERVAL_MS = 10000;
static constexpr bool ENABLE_DEMO_ACTION = false;  // Phase-1 safety: no unsolicited in-game actions.

// (Phase-2 LVGL path now pushes the launcher during `lvgl_bringup()`, so
// there is no longer a one-shot WS-open guard; see the call to
// `ui_nav_push(launcher_create)` below. This addresses chatgpt-codex P1
// and gemini-code-assist medium feedback on PR #91 — the device must show
// the launcher even when the sidecar is unreachable.)

#if PHASE1_FALLBACK == 0
// Issue #86 Part B3: the launcher pill should only flip to DISCONNECTED
// after the link has been down for > 3 s. We capture the close timestamp
// in `ws_on_event` and apply the state transition from `ws_tick()` once
// the threshold has passed. `0` means "no pending close".
//
// Centralised here so all four arm-call-sites (clean WS close, sync
// connect failure, WiFi loss, future reconnect-race) use the same
// timer semantics. (Sourcery review on PR #91 -- WS disconnect grace
// handling was previously spread across ws_on_event/ws_try_connect/
// ws_tick with ordering-sensitive comments.)
static uint32_t ws_disconnected_pending_at = 0;
static constexpr uint32_t WS_DISCONNECT_GRACE_MS = 3000;
// Latched once disconnect_grace_evaluate() has actually surfaced
// APP_DISCONNECTED, so subsequent ws_tick() calls don't re-arm a
// fresh 3-s timer that fires repeated app_state_set(APP_DISCONNECTED)
// calls every 3 seconds while the link stays down. Cleared on reconnect
// via disconnect_grace_clear(). (Cursor Bugbot Low on PR #91.)
static bool disconnect_already_surfaced = false;

// Arm the disconnect grace timer if it isn't already armed. Idempotent
// across multiple call sites in a single tick. Skipped while
// disconnect_already_surfaced is latched -- there is no remaining grace
// to apply until a successful reconnect clears the state.
static inline void disconnect_grace_arm() {
  if (ws_disconnected_pending_at == 0 && !disconnect_already_surfaced) {
    ws_disconnected_pending_at = millis() + WS_DISCONNECT_GRACE_MS;
  }
}

// If the grace timer has elapsed, surface APP_DISCONNECTED to the
// launcher pill, clear the timer, and latch the surfaced flag. Safe to
// call every tick.
static inline void disconnect_grace_evaluate() {
  if (ws_disconnected_pending_at != 0 &&
      (int32_t)(millis() - ws_disconnected_pending_at) >= 0) {
    app_state_set(APP_DISCONNECTED);
    ws_disconnected_pending_at = 0;
    disconnect_already_surfaced = true;
  }
}

// Cancel any pending grace timer (called when the WS reconnects). Also
// clears the latched-surfaced flag so the next link drop will re-arm a
// fresh grace window.
static inline void disconnect_grace_clear() {
  ws_disconnected_pending_at = 0;
  disconnect_already_surfaced = false;
}
#endif

// -- Drawing helpers (Phase 1 only) -----------------------------------------

#if PHASE1_FALLBACK
static const char* wifi_label(WifiState s) {
  switch (s) {
    case WifiState::Idle:       return "WiFi: idle";
    case WifiState::Connecting: return "WiFi: connecting...";
    case WifiState::Connected:  return "WiFi: connected";
    case WifiState::Failed:     return "WiFi: failed";
  }
  return "WiFi: ?";
}

static uint16_t wifi_colour(WifiState s) {
  switch (s) {
    case WifiState::Connected:  return COL_OK;
    case WifiState::Connecting: return COL_WARN;
    case WifiState::Failed:     return COL_ERR;
    default:                    return COL_DIM;
  }
}

static const char* ws_label(WsState s) {
  switch (s) {
    case WsState::Idle:         return "Sidecar: idle";
    case WsState::Connecting:   return "Sidecar: connecting...";
    case WsState::Open:         return "Sidecar: open";
    case WsState::AuthRejected: return "Sidecar: auth rejected";
    case WsState::Closed:       return "Sidecar: closed";
    case WsState::Error:        return "Sidecar: error";
  }
  return "Sidecar: ?";
}

static uint16_t ws_colour(WsState s) {
  switch (s) {
    case WsState::Open:         return COL_OK;
    case WsState::Connecting:   return COL_WARN;
    case WsState::AuthRejected: return COL_ERR;
    case WsState::Closed:       return COL_DIM;
    case WsState::Error:        return COL_ERR;
    default:                    return COL_DIM;
  }
}

static void draw_row(int y, const char* text, uint16_t fg) {
  gfx->fillRect(PAD, y - 2, SCREEN_W - 2 * PAD, ROW_H, COL_BG);
  gfx->setTextColor(fg, COL_BG);
  gfx->setTextSize(2);
  gfx->setCursor(PAD, y);
  gfx->print(text);
}

static void draw_static_chrome() {
  gfx->fillScreen(COL_BG);

  // Title.
  gfx->setTextColor(COL_FG, COL_BG);
  gfx->setTextSize(3);
  gfx->setCursor(PAD, ROW_TITLE);
  gfx->print("AC Copilot Screen");

  gfx->setTextColor(COL_DIM, COL_BG);
  gfx->setTextSize(2);
  gfx->setCursor(PAD, ROW_SUB);
  gfx->print(CLIENT_ID);

  // Target line (static).
  char hostbuf[96];
  snprintf(hostbuf, sizeof(hostbuf), "target  ws://%s:%d%s",
           SIDECAR_HOST, SIDECAR_PORT, SIDECAR_PATH);
  draw_row(ROW_HOST, hostbuf, COL_DIM);

  // Demo button (virtual - no touch yet).
  gfx->fillRoundRect(BTN_X, BTN_Y, BTN_W, BTN_H, 10, COL_BTN_BG);
  gfx->setTextColor(COL_BTN_FG, COL_BTN_BG);
  gfx->setTextSize(2);
  const char* btn_lbl = "auto-ping: toggleFocusPractice";
  int16_t x1, y1;
  uint16_t tw, th;
  gfx->getTextBounds(btn_lbl, 0, 0, &x1, &y1, &tw, &th);
  int tx = BTN_X + (BTN_W - (int)tw) / 2;
  int ty = BTN_Y + (BTN_H - (int)th) / 2;
  gfx->setCursor(tx, ty);
  gfx->print(btn_lbl);
}

static void refresh_ui() {
  bool changed = false;
  if (wifi_state != last_painted_wifi) {
    draw_row(ROW_WIFI, wifi_label(wifi_state), wifi_colour(wifi_state));
    last_painted_wifi = wifi_state;
    changed = true;
  }
  if (ws_state != last_painted_ws) {
    draw_row(ROW_WS, ws_label(ws_state), ws_colour(ws_state));
    last_painted_ws = ws_state;
    changed = true;
  }
  if (last_error != last_painted_err) {
    draw_row(ROW_ERR, last_error.length() ? last_error.c_str() : "", COL_ERR);
    last_painted_err = last_error;
    changed = true;
  }
  // Canvas-backed display: nothing reaches the panel until flush(). Only
  // flush when something actually changed to avoid a per-tick DMA cost.
  if (changed && gfx) {
    gfx->flush();
  }
}
#else  // PHASE1_FALLBACK == 0 — LVGL bring-up

// LVGL partial-buffer parameters. Two 240×40 RGB565 buffers in PSRAM
// (~38 KiB total) per the ADR's Pattern A. Allocated at setup() time.
static constexpr uint32_t LV_BUF_W       = 240;
static constexpr uint32_t LV_BUF_LINES   = 40;
static constexpr uint32_t LV_BUF_PIXELS  = LV_BUF_W * LV_BUF_LINES;
static lv_disp_draw_buf_t lv_draw_buf;
static lv_color_t*        lv_buf_a = nullptr;
static lv_color_t*        lv_buf_b = nullptr;
static lv_disp_drv_t      lv_disp_drv;
static lv_indev_drv_t     lv_indev_drv;
static uint32_t           lv_last_tick_ms = 0;
static uint32_t           lv_next_canvas_flush_ms = 0;
static bool               lv_canvas_dirty = false;

static void lv_flush_cb(lv_disp_drv_t* drv, const lv_area_t* area, lv_color_t* color_p) {
  if (gfx) {
    uint32_t w = (area->x2 - area->x1 + 1);
    uint32_t h = (area->y2 - area->y1 + 1);
    // LV_COLOR_16_SWAP=1 → bytes already in big-endian RGB565. The
    // moononournation API name is "BeRGBBitmap" — feed straight in.
    gfx->draw16bitBeRGBBitmap(area->x1, area->y1,
                              reinterpret_cast<uint16_t*>(color_p),
                              w, h);
    lv_canvas_dirty = true;
  }
  lv_disp_flush_ready(drv);
}

static void lv_indev_read_cb(lv_indev_drv_t* /*drv*/, lv_indev_data_t* data) {
  uint16_t x = 0, y = 0;
  // LVGL 8.3 pre-fills `data->point` from the last raw POINTER point in
  // `_lv_indev_read`, so leaving point untouched on REL "happens to work."
  // Use the canonical static-last_x/last_y pattern from
  // lv_port_indev_template.c so the contract survives a future LVGL upgrade
  // and is self-documenting. (CodeRabbit nit on PR #91.)
  static lv_coord_t last_x = 0, last_y = 0;
  if (jc_touch_read(&x, &y)) {
    last_x = x;
    last_y = y;
    data->state = LV_INDEV_STATE_PR;
  } else {
    data->state = LV_INDEV_STATE_REL;
  }
  data->point.x = last_x;
  data->point.y = last_y;
}

static void lvgl_bringup() {
  lv_init();

  // Allocate the two partial buffers in PSRAM (heap_caps with SPIRAM).
  lv_buf_a = static_cast<lv_color_t*>(
      heap_caps_malloc(LV_BUF_PIXELS * sizeof(lv_color_t), MALLOC_CAP_SPIRAM));
  lv_buf_b = static_cast<lv_color_t*>(
      heap_caps_malloc(LV_BUF_PIXELS * sizeof(lv_color_t), MALLOC_CAP_SPIRAM));
  if (!lv_buf_a || !lv_buf_b) {
    // PSRAM draw-buffer allocation must not silently hang the device.
    // Print loudly and reset so the watchdog crash log is visible to a
    // user with a serial monitor open. (Sourcery review on PR #91.)
    Serial.println("[fatal][lvgl] PSRAM draw-buffer alloc failed -- restarting in 3s");
    Serial.flush();
    delay(3000);
    ESP.restart();
  }
  lv_disp_draw_buf_init(&lv_draw_buf, lv_buf_a, lv_buf_b, LV_BUF_PIXELS);

  lv_disp_drv_init(&lv_disp_drv);
  lv_disp_drv.hor_res  = SCREEN_W;
  lv_disp_drv.ver_res  = SCREEN_H;
  lv_disp_drv.flush_cb = lv_flush_cb;
  lv_disp_drv.draw_buf = &lv_draw_buf;
  lv_disp_drv_register(&lv_disp_drv);

  jc_touch_begin();
  lv_indev_drv_init(&lv_indev_drv);
  lv_indev_drv.type    = LV_INDEV_TYPE_POINTER;
  lv_indev_drv.read_cb = lv_indev_read_cb;
  lv_indev_drv_register(&lv_indev_drv);

  ui_nav_init();
  app_state_set(APP_BOOTING);
  // Push the launcher immediately so the device shows real UI during the
  // boot/connection phase, not a blank LVGL default. The launcher header
  // pill reflects WiFi/WS state via `app_state_get()`. Critical for the
  // sidecar-unreachable failure mode (chatgpt-codex P1 on PR #91).
  ui_nav_push(launcher_create);
  lv_last_tick_ms = millis();
  lv_next_canvas_flush_ms = lv_last_tick_ms + 16;
}

static void lvgl_tick() {
  uint32_t now = millis();
  uint32_t elapsed = now - lv_last_tick_ms;
  if (elapsed > 0) {
    lv_tick_inc(elapsed);
    lv_last_tick_ms = now;
  }
  lv_timer_handler();

  // Canvas push: ~60 Hz cap. Only push when LVGL actually drew something.
  if (lv_canvas_dirty && (int32_t)(now - lv_next_canvas_flush_ms) >= 0) {
    if (gfx_canvas) {
      gfx_canvas->flush();
    }
    lv_canvas_dirty = false;
    lv_next_canvas_flush_ms = now + 16;
  }
}
#endif  // PHASE1_FALLBACK

// -- Network -----------------------------------------------------------------

static void send_demo_action() {
  if (!ENABLE_DEMO_ACTION) {
    return;
  }
  JsonDocument doc;
  doc["v"]    = 1;
  doc["type"] = "action";
  doc["name"] = "toggleFocusPractice";
  String out;
  serializeJson(doc, out);
  ws.send(out);
  Serial.printf("[ws] -> %s\n", out.c_str());
}

static void wifi_try_begin() {
  wifi_state = WifiState::Connecting;
#if PHASE1_FALLBACK
  refresh_ui();
#endif
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  wifi_retry_at = millis() + 15000;
}

static void wifi_tick() {
  if (wifi_state == WifiState::Connecting || wifi_state == WifiState::Failed) {
    if (WiFi.status() == WL_CONNECTED) {
      wifi_state = WifiState::Connected;
      last_error = "";
      Serial.printf("[wifi] up  %s\n", WiFi.localIP().toString().c_str());
#if PHASE1_FALLBACK
      refresh_ui();
#endif
    } else if ((int32_t)(millis() - wifi_retry_at) >= 0) {
      wifi_state = WifiState::Failed;
      last_error = "wifi: retrying";
#if PHASE1_FALLBACK == 0
      // wifi_try_begin() below resets wifi_state to Connecting in the
      // same wifi_tick() call, so ws_tick() (which runs after wifi_tick
      // in loop()) never observes Failed during a cold-boot SSID timeout.
      // Arm the grace timer directly here so the launcher pill still
      // surfaces DISCONNECTED in that case. (chatgpt-codex P2 follow-up
      // on PR #91.)
      disconnect_grace_arm();
#endif
      WiFi.disconnect(true, false);
      delay(200);
      wifi_try_begin();
    }
  } else if (wifi_state == WifiState::Connected && WiFi.status() != WL_CONNECTED) {
    wifi_state = WifiState::Failed;
    last_error = "wifi: lost, retrying";
#if PHASE1_FALLBACK
    refresh_ui();
#endif
    // Force-close the WS so a transient WiFi blip can't leave the
    // socket in a half-open `WsState::Open` while the underlying TCP
    // is dead. Without this, a WiFi-drop-and-recover faster than the
    // WS keepalive timeout keeps `ws_state == Open` indefinitely and
    // blocks `ws_try_connect()` from running. (Cursor Bugbot finding
    // on PR #91.)
#if PHASE1_FALLBACK == 0
    if (ws_state == WsState::Open) {
      Serial.println("[ws] forcing close after WiFi loss");
      ws.close();
      ws_state = WsState::Closed;
      // Arm the grace timer here too, since `ws.close()` may not
      // synchronously fire `ConnectionClosed` if the network is gone.
      disconnect_grace_arm();
    }
#endif
    wifi_try_begin();
  }
}

#if PHASE1_FALLBACK == 0
// Issue #86 Parts C/D: dispatch per-message-type. `state.snapshot` carries
// a `topic` field we route to the appropriate screen module; `setup.*`
// frames go straight to the Pocket Technician screen module.
//
// The dispatch never blocks the WS callback for long: each branch either
// builds a small POD and calls a screen setter, or fans a few labels
// through the same setters. Heavy LVGL work happens later via the
// `lv_async_call` queue inside the screen modules.
static void dispatch_phase2_message(const String& body) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, body);
  if (err) {
    Serial.printf("[ws] parse err: %s\n", err.c_str());
    return;
  }
  if (doc["v"].as<int>() != 1) {
    return;
  }
  const char* type = doc["type"] | "";
  if (type[0] == 0) {
    // Round-10 corner_advice uses the legacy `event` envelope.
    const char* ev = doc["event"] | "";
    if (strcmp(ev, "corner_advice") == 0) {
      const char* corner = doc["corner"] | "";
      const char* text   = doc["text"]   | "";
      if (*corner && *text) {
        screen_ac_copilot_apply_corner_advice(corner, text);
      }
    }
    return;
  }

  if (strcmp(type, "state.snapshot") == 0) {
    const char* topic = doc["topic"] | "";
    JsonVariantConst payload = doc["payload"];
    if (strcmp(topic, "coaching.snapshot") == 0) {
      coaching_snapshot_t snap = {};
      const char* corner_id    = payload["corner_id"]    | "";
      const char* corner_label = payload["corner_label"] | corner_id;
      const char* primary      = payload["primary_line"]   | "";
      const char* secondary    = payload["secondary_line"] | "";
      const char* kind         = payload["kind"]         | "info";
      const char* sub_state    = payload["sub_state"]    | "cruising";
      strncpy(snap.corner_label, corner_label, sizeof(snap.corner_label) - 1);
      strncpy(snap.primary_line, primary,      sizeof(snap.primary_line) - 1);
      strncpy(snap.secondary_line, secondary,  sizeof(snap.secondary_line) - 1);
      strncpy(snap.kind, kind,                 sizeof(snap.kind) - 1);
      strncpy(snap.sub_state, sub_state,       sizeof(snap.sub_state) - 1);
      // Accept both integer and floating-point JSON numbers (chatgpt-codex P1
      // + CodeRabbit "Critical" on PR #91): the Lua publisher emits
      // tonumber(view.targetSpeedKmh) and car.speedKmh, both of which can be
      // fractional. is<int>() returns false for floats, so the screen would
      // silently default valid telemetry to -1. Cast through float and round
      // half-up to int32. Nil/missing fields keep the -1/0 sentinels.
      auto numOr = [](JsonVariantConst v, int32_t fallback) -> int32_t {
        if (v.is<int>())   return (int32_t)v.as<int>();
        if (v.is<float>()) {
          float f = v.as<float>();
          return (int32_t)(f >= 0.0f ? f + 0.5f : f - 0.5f);
        }
        return fallback;
      };
      snap.target_speed_kmh  = numOr(payload["target_speed_kmh"],  -1);
      snap.current_speed_kmh = numOr(payload["current_speed_kmh"], -1);
      snap.dist_to_brake_m   = numOr(payload["dist_to_brake_m"],   -1);
      int32_t pp = numOr(payload["progress_pct"], 0);
      if (pp < 0) pp = 0;
      if (pp > 100) pp = 100;
      snap.progress_pct      = pp;
      snap.has_data          = true;
      screen_ac_copilot_apply_snapshot(&snap);
    } else if (strcmp(topic, "setup.active") == 0) {
      const char* name = payload["name"] | "";
      if (*name) screen_pocket_technician_set_active_setup(name);
    }
  } else if (strcmp(type, "setup.list.result") == 0) {
    const char* car_id   = doc["car_id"]   | "";
    const char* track_id = doc["track_id"] | "";
    if (*car_id || *track_id) {
      screen_pocket_technician_set_identity(*car_id ? car_id : nullptr,
                                            *track_id ? track_id : nullptr);
    }
    screen_pocket_technician_clear_setups();
    JsonArrayConst setups = doc["setups"].as<JsonArrayConst>();
    if (!setups.isNull()) {
      for (JsonVariantConst entry : setups) {
        const char* name      = entry["name"]      | "";
        const char* mtime_iso = entry["mtime_iso"] | "";
        const char* path      = entry["path"]      | "";
        int32_t best_ms = entry["best_ms"].is<int>() ? entry["best_ms"].as<int>() : -1;
        if (*name) {
          screen_pocket_technician_add_setup(name, mtime_iso, best_ms,
                                              *path ? path : nullptr);
        }
      }
    }
  } else if (strcmp(type, "setup.load.ack") == 0) {
    bool ok = doc["ok"] | false;
    const char* name  = doc["name"]  | "";
    const char* error = doc["error"] | "";
    // Treat an empty `error` field the same as missing so the screen's
    // "unknown" fallback fires instead of formatting "Load failed: " with
    // a blank trailer (Cursor Bugbot LOW on PR #91).
    const char* err_arg = (ok || !error || *error == 0) ? nullptr : error;
    screen_pocket_technician_apply_load_ack(ok, name, err_arg);
  }
}
#endif

static void ws_on_message(WebsocketsMessage msg) {
  // Verbose log on Phase-1 fallback only — the LVGL path produces 10 Hz
  // coaching.snapshot frames which would flood the serial monitor.
#if PHASE1_FALLBACK
  Serial.printf("[ws] <- %s\n", msg.data().c_str());
#else
  // Issue #86 Parts C/D: parse + dispatch. Tolerates malformed JSON by
  // logging once and dropping; never blocks the WS poll path.
  dispatch_phase2_message(msg.data());
#endif
}

static void ws_on_event(WebsocketsEvent ev, String data) {
  switch (ev) {
    case WebsocketsEvent::ConnectionOpened: {
      ws_state      = WsState::Open;
      ws_backoff_ms = 1000;
      last_error    = "";
      Serial.println("[ws] open");
#if PHASE1_FALLBACK == 0
      // Launcher is already on the stack from `lvgl_bringup()`. Promote
      // BOOTING → CONNECTED → LAUNCHER_IDLE on first open and on every
      // reconnect; the launcher header listens to this and updates the
      // CONNECTED/DISCONNECTED pill without us pushing a new screen.
      // Cancel any pending disconnect threshold (Part B3 grace window).
      disconnect_grace_clear();
      app_state_set(APP_CONNECTED);
      // Always promote to APP_LAUNCHER_IDLE on a (re)connect, regardless of
      // whether the user is currently on the launcher screen or inside a
      // placeholder (Pocket Tech / Setup Exchange / AC Copilot). Otherwise
      // the LAUNCHER_IDLE transition would never fire if the user popped
      // back to the launcher AFTER reconnect happened, leaving the state
      // stuck at APP_CONNECTED -- functionally harmless today but couples
      // future state-driven UI to a fragile assumption. (Cursor Bugbot
      // Low on PR #91.)
      app_state_set(APP_LAUNCHER_IDLE);
#endif
      JsonDocument doc;
      doc["v"]       = 1;
      doc["type"]    = "hello";
      doc["client"]  = CLIENT_ID;
      String out;
      serializeJson(doc, out);
      ws.send(out);
      demo_next_at = millis() + DEMO_INTERVAL_MS;
      break;
    }
    case WebsocketsEvent::ConnectionClosed:
      ws_state   = WsState::Closed;
      last_error = "ws closed";
      Serial.println("[ws] closed");
#if PHASE1_FALLBACK == 0
      // Part B3: don't flip the pill immediately — give the auto-reconnect
      // logic up to WS_DISCONNECT_GRACE_MS to recover before showing the
      // user a DISCONNECTED state. `ws_tick()` evaluates the deadline.
      disconnect_grace_arm();
#endif
      break;
    case WebsocketsEvent::GotPing:
      break;
    case WebsocketsEvent::GotPong:
      break;
  }
#if PHASE1_FALLBACK
  refresh_ui();
#endif
}

static void ws_try_connect() {
  if (WiFi.status() != WL_CONNECTED) return;
  ws = WebsocketsClient();
  ws_state = WsState::Connecting;
  last_error = "";
#if PHASE1_FALLBACK
  refresh_ui();
#endif

  ws.onMessage(ws_on_message);
  ws.onEvent(ws_on_event);
  ws.addHeader("X-AC-Copilot-Token", SIDECAR_TOKEN);
  ws.addHeader("X-AC-Copilot-Client", CLIENT_ID);

  String url = "ws://" + String(SIDECAR_HOST) + ":" + String(SIDECAR_PORT) +
               String(SIDECAR_PATH);
  Serial.printf("[ws] dial %s\n", url.c_str());
  bool ok = ws.connect(url);
  if (!ok) {
    ws_state   = WsState::Error;
    last_error = "ws connect failed";
    Serial.println("[ws] connect returned false");
#if PHASE1_FALLBACK == 0
    // No socket was ever opened, so `ws_on_event(ConnectionClosed)` won't
    // fire and the disconnect grace timer would never arm. If we don't
    // arm it here, a sidecar-unreachable boot leaves the pill stuck on
    // "CONNECTING" forever. (chatgpt-codex P1 + Cursor Bugbot medium +
    // Sourcery suggestion on PR #91.)
    disconnect_grace_arm();
#endif
#if PHASE1_FALLBACK
    refresh_ui();
#endif
  }
}

static void ws_tick() {
  ws.poll();
#if PHASE1_FALLBACK == 0
  const bool wifi_up = (WiFi.status() == WL_CONNECTED);
  const bool link_up = wifi_up && ws_state == WsState::Open;
  // Arm the disconnect grace timer when we have completed at least one
  // WS connection attempt (ws_state past Connecting -- so any of
  // Open/Closed/Error/AuthRejected after the first dial). The cold-boot
  // SSID-timeout case is handled directly inside wifi_tick() via an
  // explicit disconnect_grace_arm() call, because wifi_tick() resets
  // wifi_state back to Connecting in the same loop iteration before
  // ws_tick() can observe Failed (Cursor Bugbot dead-code follow-up).
  //
  // We deliberately do NOT arm during the very first boot window
  // (ws_state in {Idle, Connecting}), otherwise the pill would flash
  // red "DISCONNECTED" after the 3 s grace even though no real failure
  // has happened yet -- defeating the intent of the CONNECTING amber
  // state. The synchronous ws.connect() failure path arms the timer
  // explicitly, so a real sidecar-unreachable boot still surfaces
  // DISCONNECTED via ws_state = Error.
  //
  // This block must run BEFORE the `ws_state == Open` early return
  // below -- otherwise the arming code is unreachable in exactly the
  // scenario it's meant to handle (WiFi drops while ws_state is still
  // Open). (Sourcery + Cursor Bugbot on PR #91.)
  const bool link_failure = (ws_state != WsState::Idle &&
                             ws_state != WsState::Connecting);
  if (!link_up && link_failure) {
    disconnect_grace_arm();
  } else if (link_up) {
    // Link is fully up again; clear any timer armed by a transient
    // WiFi.status() blip during a still-Open WS session, otherwise the
    // timer would expire and force APP_DISCONNECTED while the link is
    // genuinely live (Cursor Bugbot finding on PR #91).
    disconnect_grace_clear();
  }
  // Surface DISCONNECTED to the launcher pill if the grace window has
  // elapsed. Run before the open-fast-path return below.
  disconnect_grace_evaluate();
#endif
  if (ws_state == WsState::Open) {
    if (ENABLE_DEMO_ACTION && (int32_t)(millis() - demo_next_at) >= 0) {
      send_demo_action();
      demo_next_at = millis() + DEMO_INTERVAL_MS;
    }
    return;
  }
  if (WiFi.status() != WL_CONNECTED) return;
  if ((int32_t)(millis() - ws_retry_at) >= 0) {
    ws_try_connect();
    ws_backoff_ms = min<uint32_t>(WS_BACKOFF_MAX_MS, ws_backoff_ms * 2);
    ws_retry_at   = millis() + ws_backoff_ms;
  }
}

// -- Setup / Loop ------------------------------------------------------------

#if PHASE1_FALLBACK
// Sweep rotations to confirm the canvas+QSPI flush path paints visibly.
// Arduino_Canvas + AXS15231B requires an explicit flush() after each scene
// (the canvas is a PSRAM framebuffer; nothing reaches the panel until flush).
static void sweep_rotations() {
  uint16_t colors[4] = { 0xF800 /*R*/, 0x07E0 /*G*/, 0x001F /*B*/, 0xFFFF /*W*/ };
  for (uint8_t r = 0; r < 4; ++r) {
    gfx->setRotation(r);
    int w = gfx->width();
    int h = gfx->height();
    Serial.printf("[diag] rot=%u size=%dx%d  fill=0x%04X\n", r, w, h, colors[r]);
    gfx->fillScreen(colors[r]);
    gfx->fillRect(0, 0, w, 8, 0x0000);
    gfx->fillRect(0, h - 8, w, 8, 0x0000);
    gfx->fillRect(0, 0, 8, h, 0x0000);
    gfx->fillRect(w - 8, 0, 8, h, 0x0000);
    gfx->drawLine(0, 0, w - 1, h - 1, 0x0000);
    gfx->drawLine(0, h - 1, w - 1, 0, 0x0000);
    gfx->flush();
    delay(2200);
  }
}
#endif

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println();
  Serial.println("[boot] AC Copilot Screen " CLIENT_ID);
#if PHASE1_FALLBACK
  Serial.println("[boot] PHASE1_FALLBACK=1 (raw Arduino_GFX UI)");
#else
  Serial.println("[boot] LVGL 8.3 path (issue #86 Part A)");
#endif

  // Try every plausible BL pin simultaneously — community configs report
  // GPIO 1 (most common), 38, 5, and sometimes 16/18 for JC3248W535 clones.
  // Pulse 6× LOW/HIGH at 400ms so the user can see brightness change. Whichever
  // pin actually drives BL will make the panel visibly blink. After the pulse
  // we leave them all HIGH.
  const int BL_CANDIDATES[] = {JC_TFT_BL, 38, 5, 16, 18, 6, 21};
  const int BL_N = sizeof(BL_CANDIDATES) / sizeof(BL_CANDIDATES[0]);
  for (int i = 0; i < BL_N; ++i) pinMode(BL_CANDIDATES[i], OUTPUT);
  Serial.printf("[diag] BL sweep over pins: ");
  for (int i = 0; i < BL_N; ++i) Serial.printf("%d ", BL_CANDIDATES[i]);
  Serial.println();
  for (int p = 0; p < 6; ++p) {
    int level = (p % 2 == 0) ? LOW : HIGH;
    for (int i = 0; i < BL_N; ++i) digitalWrite(BL_CANDIDATES[i], level);
    delay(220);
  }
  for (int i = 0; i < BL_N; ++i) digitalWrite(BL_CANDIDATES[i], HIGH);
  Serial.println("[diag] BL pins all HIGH after pulse");

  Serial.println("[diag] make_display() ...");
  // jc3248w535_make_display() now returns Arduino_Canvas* directly, so we
  // get both pointers without a downcast. `gfx` keeps the
  // base-class behaviour we use for begin/setRotation/draw; `gfx_canvas`
  // exposes flush() for the LVGL canvas-flush path. (Copilot review on
  // PR #91 — the previous static_cast was UB-adjacent if the factory was
  // ever swapped; this makes the invariant compile-time-checked.)
  gfx_canvas = jc3248w535_make_display();
  gfx        = gfx_canvas;
  Serial.printf("[diag] gfx ptr=%p\n", gfx);
  Serial.println("[diag] gfx->begin() ...");
  bool ok = gfx && gfx->begin();
  Serial.printf("[diag] begin returned %d\n", ok ? 1 : 0);
  if (!gfx || !ok) {
    Serial.println("[fatal] gfx->begin() failed");
    while (true) { delay(1000); }
  }
  Serial.printf("[diag] init size: %dx%d\n", gfx->width(), gfx->height());

  // Sanity-check the canvas narrow: if the factory is ever swapped to a
  // non-canvas surface, the dimensions will mismatch the JC_TFT_NATIVE_*
  // values and we want to know loudly at boot rather than silently DMA
  // garbage. (sourcery feedback on PR #91 about the static_cast UB risk.)
  if (gfx_canvas &&
      (gfx_canvas->width()  != JC_TFT_NATIVE_W ||
       gfx_canvas->height() != JC_TFT_NATIVE_H)) {
    Serial.printf("[warn] canvas dims %dx%d != native %dx%d -- factory mismatch?\n",
                  gfx_canvas->width(), gfx_canvas->height(),
                  JC_TFT_NATIVE_W, JC_TFT_NATIVE_H);
  }

  // Always settle on landscape rotation=1 before any UI bring-up runs.
  gfx->setRotation(1);

#if PHASE1_FALLBACK
  // Sweep every rotation so AT LEAST one fills the visible area visibly.
  sweep_rotations();

  gfx->setRotation(1);
  draw_static_chrome();
  refresh_ui();
  gfx->flush();
  Serial.println("[diag] static chrome drawn + flushed");
#else
  // LVGL bring-up (issue #86 Part A1–A5): allocates draw buffers in PSRAM,
  // registers the Arduino_Canvas flush bridge, registers the AXS15231B
  // I²C touch reader as the LVGL pointer device, prepares the navigator,
  // and pushes the Launcher screen so the user sees real UI during boot.
  lvgl_bringup();
  // Verify the launcher actually got pushed. `launcher_create()` returns
  // nullptr on OOM and `ui_nav_push()` refuses null factories silently, so
  // we want a distinct error log rather than a misleading success line if
  // the device is sitting on the LVGL default empty screen. (CodeRabbit
  // review on PR #91.)
  if (ui_nav_depth() > 0) {
    Serial.println("[diag] LVGL ready; launcher pushed (state=BOOTING)");
  } else {
    Serial.println("[error] LVGL ready but launcher push failed (OOM?) -- blank screen");
  }
#endif

  // WiFi.
  wifi_try_begin();

  // First WS attempt shortly after WiFi is up; the state machine handles it.
  ws_retry_at = millis() + 500;
}

#if PHASE1_FALLBACK == 0
// Drain the Pocket Technician out-queue. Called every loop tick after
// `ws_tick()`; bounded to a few sends per call so a long-stuck WS write
// can't starve the LVGL render path.
static void pt_request_drain() {
  if (ws_state != WsState::Open) return;
  for (int i = 0; i < 4; ++i) {
    pt_request_t req = screen_pocket_technician_pop_request();
    if (req.kind == PT_REQ_NONE) break;

    JsonDocument doc;
    doc["v"] = 1;
    if (req.kind == PT_REQ_LIST) {
      doc["type"] = "setup.list";
    } else if (req.kind == PT_REQ_LOAD) {
      doc["type"] = "setup.load";
      doc["name"] = req.name;
      // Carry the absolute INI path when the trainer reported it on the list,
      // so the Lua handler can disambiguate setups whose basenames collide
      // across track/layout folders (chatgpt-codex P1 on PR #91).
      if (req.path[0]) doc["path"] = req.path;
    } else {
      continue;
    }
    String out;
    serializeJson(doc, out);
    ws.send(out);
    Serial.printf("[ws] -> %s\n", out.c_str());
  }
}
#endif

void loop() {
  wifi_tick();
  ws_tick();
#if PHASE1_FALLBACK == 0
  pt_request_drain();
  lvgl_tick();
#endif
  delay(2);
}
