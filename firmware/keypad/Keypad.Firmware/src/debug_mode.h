#pragma once

#include "../configuration.h"

#if CONFIGURATION_DEBUG_MODE
void debug_mode_setup(void);
void debug_mode_loop(void);
#else
static inline void debug_mode_setup(void) {}
static inline void debug_mode_loop(void) {}
#endif
