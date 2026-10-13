// Sample configuration used to keep firmware buildable in the repo.
// At runtime this file is replaced by the backend configuration generator.

#pragma once

#define CONFIGURATION_BUTTON_CAPACITY 4
#define CONFIGURATION_ENCODER_CAPACITY 1
#define CONFIGURATION_DEBUG_MODE 0

#define DEBUG_NOISE_FILTER_ENABLED 1
#define DEBUG_PULLUPS_ENABLED 1
#define DEBUG_CONFIRM_SAMPLES 3
#define DEBUG_CONFIRM_DELAY_MS 1

#define HID_MAX_KEY_STEPS 1

#define PIN_NEO P34
#define NEO_COUNT 3
#define NEO_GRB
#define NEO_REVERSED 0

#include "src/configuration_data.h"