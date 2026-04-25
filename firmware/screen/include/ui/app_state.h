// Shared connection / lifecycle state — issue #86 Part F1 (foundation).
//
// Updated by main.cpp on WiFi/WS transitions; consumed by the launcher
// header (CONNECTED/DISCONNECTED pill) and any screen that wants to gate
// behavior on the link being live.

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    APP_BOOTING = 0,
    APP_CONNECTED,
    APP_LAUNCHER_IDLE,
    APP_DISCONNECTED,
} app_state_t;

app_state_t app_state_get(void);
void        app_state_set(app_state_t new_state);

#ifdef __cplusplus
}
#endif
