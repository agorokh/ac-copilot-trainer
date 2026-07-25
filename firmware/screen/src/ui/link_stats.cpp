// Link / backpressure counters — issue #677 Parts B/C.

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
    // Parse-success counter only — do not bump last_frame here; callers that
    // already saw a complete line call link_stats_note_rx() first (#677 / qodo).
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

extern "C" void link_stats_emit_bp_line(void) {
    // Machine-parseable for tools.ai_sidecar.serial_backpressure_probe (#677 B).
    Serial.printf(
        "[serial][bp] ok=%lu drop=%lu parse=%lu max_avail=%lu max_drain_ms=%lu "
        "linked=%u peers=%u last_ms=%lu heap=%u\n",
        static_cast<unsigned long>(g_stats.frames_ok),
        static_cast<unsigned long>(g_stats.overflow_drops),
        static_cast<unsigned long>(g_stats.parse_drops),
        static_cast<unsigned long>(g_stats.max_rx_available),
        static_cast<unsigned long>(g_stats.max_drain_ms),
        static_cast<unsigned>(g_stats.linked),
        static_cast<unsigned>(g_stats.peer_count),
        static_cast<unsigned long>(g_stats.last_frame_ms),
        static_cast<unsigned>(ESP.getFreeHeap()));
}
