// Explicit coaching actions; legacy snapshots fail closed without speed inference.
#pragma once

#include <string.h>

inline const char* coaching_command(const char* action, const char* primary,
                                    bool available, bool stale) {
    if (!available) return "WAIT";
    if (stale) return "STALE";
    if (action && *action) {
        if (strcmp(action, "CARRY_MORE_SPEED") == 0) return "CARRY MORE SPEED";
        const char* known[] = {"BRAKE", "LIFT", "UPSHIFT", "HOLD", "CLEAR", "UNAVAILABLE"};
        for (const char* value : known) {
            if (strcmp(action, value) == 0) return value;
        }
        return "UNAVAILABLE";
    }
    // Only known literal legacy commands are meaningful. kind="line" includes
    // upshifts and carry cues, and a NEXT brake speed is not a current verdict.
    if (!primary) return "UNAVAILABLE";
    if (strcmp(primary, "BRAKE NOW") == 0 || strcmp(primary, "BRAKE") == 0 ||
        strcmp(primary, "PREPARE BRAKE") == 0) return "BRAKE";
    if (strcmp(primary, "SHIFT UP") == 0 || strcmp(primary, "UPSHIFT") == 0) return "UPSHIFT";
    if (strcmp(primary, "LIFT") == 0) return "LIFT";
    if (strcmp(primary, "CARRY MORE SPEED") == 0) return "CARRY MORE SPEED";
    if (strcmp(primary, "HOLD") == 0) return "HOLD";
    if (strcmp(primary, "CLEAR") == 0) return "CLEAR";
    return "UNAVAILABLE";
}
