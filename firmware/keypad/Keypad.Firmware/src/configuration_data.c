#include <Arduino.h>

#include "../configuration.h"

static bool button_state_storage_s[CONFIGURATION_BUTTON_CAPACITY > 0 ? CONFIGURATION_BUTTON_CAPACITY : 1];

size_t configuration_button_state_capacity(void)
{
    return CONFIGURATION_BUTTON_CAPACITY;
}

bool *configuration_button_state_storage(void)
{
    return button_state_storage_s;
}

#if CONFIGURATION_ENCODER_CAPACITY > 0
static uint8_t encoder_prev_storage_s[CONFIGURATION_ENCODER_CAPACITY];
static int8_t encoder_delta_storage_s[CONFIGURATION_ENCODER_CAPACITY];
#else
static uint8_t encoder_prev_storage_s[1];
static int8_t encoder_delta_storage_s[1];
#endif

size_t configuration_encoder_state_capacity(void)
{
    return CONFIGURATION_ENCODER_CAPACITY;
}

uint8_t *configuration_encoder_prev_storage(void)
{
    return encoder_prev_storage_s;
}

int8_t *configuration_encoder_delta_storage(void)
{
    return encoder_delta_storage_s;
}

bool configuration_bootloader_requested(void)
{
    bool requested = false;
    for (size_t i = 0; i < button_binding_count; ++i)
    {
        if (!button_bindings[i].bootloader_on_boot)
        {
            continue;
        }

        pinMode(button_bindings[i].pin, button_bindings[i].active_low ? INPUT_PULLUP : INPUT);
        bool active = button_bindings[i].active_low ? !digitalRead(button_bindings[i].pin)
                                                    : digitalRead(button_bindings[i].pin);
        if (active)
        {
            requested = true;
            break;
        }
    }
    return requested;
}
