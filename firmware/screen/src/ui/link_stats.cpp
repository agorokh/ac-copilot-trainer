// Link / backpressure counters — issue #677 Parts B/C.
// Plain state only; main.cpp owns Serial I/O for the `[serial][bp]` line.

#include "ui/link_stats.h"

#include <Arduino.h>

namespace {
link_stats_t g_stats = {};
}  // namespace

extern "C" void link_stats_set_linked(int linked) {
    g_stats.linked = linked ? 1 : 0;
    g_stats.peer_count = g_stats.linked;
}

extern "C" void link_stats_note_rx(void) {
    g_stats.last_frame_ms = millis();
}

extern "C" void link_stats_note_frame(void) {
    if (g_stats.frames_ok < UINT32_MAX) {
        ++g_stats.frames_ok;
    }
}

extern "C" void link_stats_note_overflow(void) {
    if (g_stats.overflow_drops < UINT32_MAX) {
        ++g_stats.overflow_drops;
    }
}

extern "C" void link_stats_note_parse_drop(void) {
    if (g_stats.parse_drops < UINT32_MAX) {
        ++g_stats.parse_drops;
    }
}

extern "C" void link_stats_note_drain(uint32_t available, uint32_t drain_ms) {
    g_stats.last_drain_ms = drain_ms;
    if (available > g_stats.max_rx_available) {
        g_stats.max_rx_available = available;
    }
    if (drain_ms > g_stats.max_drain_ms) {
        g_stats.max_drain_ms = drain_ms;
    }
}

extern "C" const link_stats_t* link_stats_get(void) {
    return &g_stats;
}
