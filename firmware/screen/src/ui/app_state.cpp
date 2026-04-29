// Shared connection / lifecycle state — issue #86 Part F1.
//
// Memory model: this state is only read/written from the main Arduino loop
// (no ISR, no second core), so plain assignment is sufficient. If a future
// change moves any reader to another task or ISR, switch to
// `std::atomic<app_state_t>` rather than re-introducing `volatile`
// (volatile alone does not provide cross-thread ordering on ESP32). See
// the sourcery review on PR #91 for context.

#include "ui/app_state.h"

namespace {
app_state_t s_state = APP_BOOTING;
}  // namespace

extern "C" app_state_t app_state_get(void) {
    return s_state;
}

extern "C" void app_state_set(app_state_t new_state) {
    s_state = new_state;
}
