// AC Copilot Rig Screen - Phase 1 firmware (Arduino_GFX, no LVGL).
//
// Goal of this revision is deliberately narrow:
//   1. Boot, turn the backlight on, render a status screen with Arduino_GFX.
//   2. Join WiFi.
//   3. Dial ws://SIDECAR_HOST:SIDECAR_PORT with X-AC-Copilot-Token.
//   4. Reflect connection state live on the screen (WiFi/WS/last error).
//   5. Demo action auto-sent every 10s once WS is Open, so we can prove the
//      full round-trip as soon as the sidecar + Lua side of the protocol v1
//      extension lands. (No touch yet - see Phase-1b.)
//
// Why Arduino_GFX (not LovyanGFX):
//   LovyanGFX 1.2.20 has no Panel_AXS15231B class, and the JC3248W535 panel
//   is AXS15231B over QSPI. Arduino_GFX (moononournation) ships the community
//   standard Arduino_AXS15231B driver. LVGL intentionally absent in Phase 1.
//
// See:
//   docs/01_Vault/AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
//   docs/01_Vault/AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>

#include "board/JC3248W535_GFX.h"
// wifi_secrets.h (not wifi.h) because Windows case-insensitive FS collides
// with the framework's WiFi.h.
#include "wifi_secrets.h"  // WIFI_SSID, WIFI_PASSWORD          (secrets/)
#include "sidecar.h"       // SIDECAR_HOST/PORT/PATH/TOKEN/CLIENT_ID (secrets/)

using namespace websockets;

static Arduino_GFX* gfx = nullptr;
static WebsocketsClient ws;

// -- Screen layout (rotation=1 -> 480x320 landscape) -------------------------

static constexpr int SCREEN_W = 480;
static constexpr int SCREEN_H = 320;

// A small palette (RGB565).
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

// -- State -------------------------------------------------------------------

enum class WifiState : uint8_t { Idle, Connecting, Connected, Failed };
enum class WsState   : uint8_t { Idle, Connecting, Open, AuthRejected, Closed, Error };

static WifiState wifi_state = WifiState::Idle;
static WsState   ws_state   = WsState::Idle;
static String    last_error;

static WifiState last_painted_wifi = (WifiState)0xFF;
static WsState   last_painted_ws   = (WsState)0xFF;
static String    last_painted_err  = String("\x01");  // sentinel

static uint32_t wifi_retry_at   = 0;
static uint32_t ws_retry_at     = 0;
static uint32_t ws_backoff_ms   = 1000;    // 1s -> 30s
static constexpr uint32_t WS_BACKOFF_MAX_MS = 30000;
static uint32_t demo_next_at    = 0;
static constexpr uint32_t DEMO_INTERVAL_MS = 10000;

// -- Drawing helpers ---------------------------------------------------------

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

// -- Network -----------------------------------------------------------------

static void send_demo_action() {
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
  refresh_ui();
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
      refresh_ui();
    } else if (millis() > wifi_retry_at) {
      wifi_state = WifiState::Failed;
      last_error = "wifi: retrying";
      WiFi.disconnect(true, false);
      delay(200);
      wifi_try_begin();
    }
  } else if (wifi_state == WifiState::Connected && WiFi.status() != WL_CONNECTED) {
    wifi_state = WifiState::Failed;
    last_error = "wifi: lost, retrying";
    refresh_ui();
    wifi_try_begin();
  }
}

static void ws_on_message(WebsocketsMessage msg) {
  Serial.printf("[ws] <- %s\n", msg.data().c_str());
  // TODO Phase 2: parse config.value / state.snapshot / ack.
}

static void ws_on_event(WebsocketsEvent ev, String data) {
  switch (ev) {
    case WebsocketsEvent::ConnectionOpened: {
      ws_state      = WsState::Open;
      ws_backoff_ms = 1000;
      last_error    = "";
      Serial.println("[ws] open");
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
      break;
    case WebsocketsEvent::GotPing:
      ws.pong();
      break;
    case WebsocketsEvent::GotPong:
      break;
  }
  refresh_ui();
}

static void ws_try_connect() {
  if (WiFi.status() != WL_CONNECTED) return;
  ws_state = WsState::Connecting;
  last_error = "";
  refresh_ui();

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
    refresh_ui();
  }
}

static void ws_tick() {
  if (ws_state == WsState::Open) {
    ws.poll();
    if ((int32_t)(millis() - demo_next_at) >= 0) {
      send_demo_action();
      demo_next_at = millis() + DEMO_INTERVAL_MS;
    }
    return;
  }
  if (WiFi.status() != WL_CONNECTED) return;
  if (millis() >= ws_retry_at) {
    ws_try_connect();
    ws_backoff_ms = min<uint32_t>(WS_BACKOFF_MAX_MS, ws_backoff_ms * 2);
    ws_retry_at   = millis() + ws_backoff_ms;
  }
}

// -- Setup / Loop ------------------------------------------------------------

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

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println();
  Serial.println("[boot] AC Copilot Screen " CLIENT_ID);

  // Try every plausible BL pin simultaneously — community configs report
  // GPIO 1 (most common), 38, 5, and sometimes 16/18 for JC3248W535 clones.
  // Pulse 6× LOW/HIGH at 400ms so the user can see brightness change. Whichever
  // pin actually drives BL will make the panel visibly blink. After the pulse
  // we leave them all HIGH.
  const int BL_CANDIDATES[] = {1, 38, 5, 16, 18, 6, 21};
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
  gfx = jc3248w535_make_display();
  Serial.printf("[diag] gfx ptr=%p\n", gfx);
  Serial.println("[diag] gfx->begin() ...");
  bool ok = gfx && gfx->begin();
  Serial.printf("[diag] begin returned %d\n", ok ? 1 : 0);
  if (!gfx || !ok) {
    Serial.println("[fatal] gfx->begin() failed");
    while (true) { delay(1000); }
  }
  Serial.printf("[diag] init size: %dx%d\n", gfx->width(), gfx->height());

  // Sweep every rotation so AT LEAST one fills the visible area visibly.
  sweep_rotations();

  // Settle on landscape rotation=1, draw the chrome.
  gfx->setRotation(1);
  draw_static_chrome();
  refresh_ui();
  gfx->flush();
  Serial.println("[diag] static chrome drawn + flushed");

  // WiFi.
  wifi_try_begin();

  // First WS attempt shortly after WiFi is up; the state machine handles it.
  ws_retry_at = millis() + 500;
}

void loop() {
  wifi_tick();
  ws_tick();
  delay(5);
}
