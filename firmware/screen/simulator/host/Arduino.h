#pragma once

#include <algorithm>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#ifndef _MSC_VER
#include <strings.h>
#else
#define strncasecmp _strnicmp
#endif

extern uint32_t simulator_time_ms;
inline uint32_t millis() { return simulator_time_ms; }

struct SimulatorSerial {
    void println(const char* text) { fprintf(stderr, "%s\n", text); }
};
inline SimulatorSerial Serial;

// No claim about target heap usage is made from a 64-bit host process.
struct SimulatorESP {
    unsigned getFreeHeap() { return 0; }
    unsigned getMinFreeHeap() { return 0; }
};
inline SimulatorESP ESP;
using std::max;
using std::min;
