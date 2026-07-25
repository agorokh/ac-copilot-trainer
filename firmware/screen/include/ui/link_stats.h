// Link / backpressure counters for the debug screen + serial probe — #677 Parts B/C.
//
// Updated from the transport path in main.cpp; read by the debug screen.
// The host-facing `[serial][bp]` line is formatted in main.cpp (transport owns
// Serial I/O — counters stay here as plain state).

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t  linked;             // 1 when the sidecar link is up
    uint8_t  peer_count;         // screen-local: 1 linked, else 0
    uint32_t last_frame_ms;      // millis() of last complete inbound frame
    uint32_t frames_ok;          // complete NDJSON lines successfully parsed
    uint32_t overflow_drops;     // lines discarded by the SERIAL_MAX_LINE guard
    uint32_t parse_drops;        // JSON deserialize failures
    uint32_t max_rx_available;   // peak Serial.available() observed at drain start
    uint32_t max_drain_ms;       // peak millis spent draining the CDC ring once
    uint32_t last_drain_ms;      // duration of the most recent non-empty drain
} link_stats_t;

void link_stats_set_linked(int linked);
// Any complete inbound line (keeps last-frame age fresh for the debug screen).
void link_stats_note_rx(void);
// Successfully deserialized JSON (increments frames_ok — host probe hard gate).
void link_stats_note_frame(void);
void link_stats_note_overflow(void);
void link_stats_note_parse_drop(void);
void link_stats_note_drain(uint32_t available, uint32_t drain_ms);

const link_stats_t* link_stats_get(void);

#ifdef __cplusplus
}
#endif
