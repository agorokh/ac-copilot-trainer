#include <Arduino.h>
#include "../configuration.h"
#include "hid.h"
#include "util.h"
#include "buttons.h"
#include "configuration_data.h"
#include "led.h"

#if !CONFIGURATION_DEBUG_MODE

static bool *button_state_s = NULL;
static size_t button_state_capacity_s = 0;
static size_t button_state_count_s = 0;
#if KEYPAD_MANAGED
static bool observed_s[CONFIGURATION_BUTTON_CAPACITY];
static uint32_t changed_ms_s[CONFIGURATION_BUTTON_CAPACITY];
#endif

void buttons_setup(void)
{
    button_state_s = configuration_button_state_storage();
    button_state_capacity_s = configuration_button_state_capacity();

    if (button_binding_count == 0)
    {
        button_state_count_s = 0;
        return;
    }

    if (button_state_s == NULL || button_state_capacity_s == 0)
    {
        button_state_count_s = 0;
        return;
    }

    button_state_count_s = button_binding_count;
    if (button_state_count_s > button_state_capacity_s)
    {
        button_state_count_s = button_state_capacity_s;
    }

    for (size_t i = 0; i < button_state_count_s; ++i)
    {
        pinMode(button_bindings[i].pin, button_bindings[i].active_low ? INPUT_PULLUP : INPUT);
        bool active = button_bindings[i].active_low ? !digitalRead(button_bindings[i].pin)
                                                   : digitalRead(button_bindings[i].pin);
        button_state_s[i] = active;
#if KEYPAD_MANAGED
        observed_s[i] = active;
        changed_ms_s[i] = millis();
#endif
        if (active)
        {
            hid_handle_button(i, HID_TRIGGER_PRESS);
        }
    }
}

void buttons_update(void)
{
    if (button_state_count_s == 0 || button_state_s == NULL)
    {
        return;
    }

    bool has_bootloader_chord = false;
    bool bootloader_chord_candidate = true;

    for (size_t i = 0; i < button_state_count_s; ++i)
    {
        bool active = button_bindings[i].active_low ? !digitalRead(button_bindings[i].pin)
                                                   : digitalRead(button_bindings[i].pin);
#if KEYPAD_MANAGED
        const uint32_t now = millis();
        if (active != observed_s[i])
        {
            observed_s[i] = active;
            changed_ms_s[i] = now;
        }
        if ((uint32_t)(now - changed_ms_s[i]) < 5)
        {
            active = button_state_s[i];
        }
#endif
        if (button_bindings[i].bootloader_chord_member)
        {
            has_bootloader_chord = true;
            bootloader_chord_candidate &= active;
        }

        if (button_state_s[i] != active)
        {
            hid_handle_button(i, active ? HID_TRIGGER_PRESS : HID_TRIGGER_RELEASE);
            button_state_s[i] = active;
        }

    }

    if (has_bootloader_chord && bootloader_chord_candidate)
    {
#if NEO_COUNT > 0
        led_show_bootloader_indicator();
#endif
        BOOT_now();
    }
}

#endif
