// Shared connection / lifecycle state — issue #86 Part F1.

#include "ui/app_state.h"

namespace {
volatile app_state_t s_state = APP_BOOTING;
}  // namespace

extern "C" app_state_t app_state_get(void) {
    return s_state;
}

extern "C" void app_state_set(app_state_t new_state) {
    s_state = new_state;
}
