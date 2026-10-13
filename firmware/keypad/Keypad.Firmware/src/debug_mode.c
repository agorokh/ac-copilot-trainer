#include <Arduino.h>
#include <stddef.h>
#include "debug_mode.h"

#if CONFIGURATION_DEBUG_MODE

#include "configuration_data.h"
#include "userUsbCdcDebug/USBCDC.h"

typedef struct
{
    uint8_t pin;
    uint8_t use_pullup;
    uint8_t active_low;
    uint8_t from_configuration;
} debug_pin_entry_t;

#define DEBUG_PIN_CAPACITY 40
#define SUMMARY_INTERVAL_MS 1000UL

#ifndef DEBUG_NOISE_FILTER_ENABLED
#define DEBUG_NOISE_FILTER_ENABLED 1
#endif

#ifndef DEBUG_PULLUPS_ENABLED
#define DEBUG_PULLUPS_ENABLED 1
#endif

#ifndef DEBUG_CONFIRM_SAMPLES
#define DEBUG_CONFIRM_SAMPLES 3
#endif

#ifndef DEBUG_CONFIRM_DELAY_MS
#define DEBUG_CONFIRM_DELAY_MS 1
#endif

static debug_pin_entry_t debug_pins_s[DEBUG_PIN_CAPACITY];
static uint8_t debug_pin_count_s = 0;
static uint8_t debug_pin_state_s[DEBUG_PIN_CAPACITY];
static uint32_t last_summary_ms_s = 0;

static void debug_serial_print_c(char value);
static void debug_serial_print_s(const char *value);
static void debug_serial_println_only(void);
static void debug_serial_print_i(long value);

static void debug_mode_collect_configured_pins(void);
static void debug_mode_collect_unassigned_pins(void);
static void debug_mode_add_pin(uint8_t pin, uint8_t use_pullup, uint8_t active_low, uint8_t from_configuration);
static void debug_mode_wait_for_host(void);
static void debug_mode_print_banner(void);
static void debug_mode_print_pin_snapshot(uint8_t index, uint8_t is_initial);
static void debug_mode_print_summary(void);
static void debug_mode_format_label(uint8_t pin, char *buffer, size_t buffer_length);
static uint8_t debug_mode_is_reserved_pin(uint8_t pin);
static void debug_mode_print_timestamp_prefix(const char *tag);
static uint8_t debug_mode_confirm_change(uint8_t pin, uint8_t previous_state);

void debug_mode_setup(void)
{
    uint8_t i;

    USBInit();
    debug_mode_wait_for_host();
    debug_mode_collect_configured_pins();
    debug_mode_collect_unassigned_pins();
    debug_mode_print_banner();

    for (i = 0; i < debug_pin_count_s; ++i)
    {
        uint8_t mode = debug_pins_s[i].use_pullup ? INPUT_PULLUP : INPUT;
        pinMode(debug_pins_s[i].pin, mode);
        delay(1);
        debug_pin_state_s[i] = digitalRead(debug_pins_s[i].pin);
        debug_mode_print_pin_snapshot(i, 1);
    }

    USBSerial_flush();
    last_summary_ms_s = millis();
}

void debug_mode_loop(void)
{
    uint8_t i;
    uint8_t changed = 0;
    uint32_t now;

    for (i = 0; i < debug_pin_count_s; ++i)
    {
        uint8_t raw = (uint8_t)(digitalRead(debug_pins_s[i].pin) ? 1 : 0);
        if (raw != debug_pin_state_s[i])
        {
            uint8_t confirmed = 1;
#if DEBUG_NOISE_FILTER_ENABLED
            confirmed = debug_mode_confirm_change(debug_pins_s[i].pin, debug_pin_state_s[i]);
#endif

            if (confirmed)
            {
                debug_pin_state_s[i] = (uint8_t)(digitalRead(debug_pins_s[i].pin) ? 1 : 0);
                debug_mode_print_pin_snapshot(i, 0);
                changed = 1;
            }
        }
    }

    now = millis();
    if (!changed && (now - last_summary_ms_s) >= SUMMARY_INTERVAL_MS)
    {
        debug_mode_print_summary();
        last_summary_ms_s = now;
    }
    else if (changed)
    {
        last_summary_ms_s = now;
    }

    USBSerial_flush();
    delay(5);
}

static void debug_mode_collect_configured_pins(void)
{
    size_t i;

    for (i = 0; i < button_binding_count; ++i)
    {
        uint8_t use_pullup = button_bindings[i].active_low ? 1 : 0;
        uint8_t active_low = button_bindings[i].active_low ? 1 : 0;
        debug_mode_add_pin(button_bindings[i].pin, use_pullup, active_low, 1);
    }

    for (i = 0; i < encoder_binding_count; ++i)
    {
        debug_mode_add_pin(encoder_bindings[i].pin_a, 1, 0, 1);
        debug_mode_add_pin(encoder_bindings[i].pin_b, 1, 0, 1);
    }
}

static void debug_mode_collect_unassigned_pins(void)
{
    static const uint8_t candidates[] = {
        0, 1, 2, 3, 4, 5, 6, 7,
        10, 11, 12, 13, 14, 15, 16, 17,
        20, 21, 22, 23, 24, 25, 26, 27,
        30, 31, 32, 33, 34, 35
    };
    size_t i;
    size_t count = sizeof(candidates) / sizeof(candidates[0]);

    for (i = 0; i < count; ++i)
    {
        debug_mode_add_pin(candidates[i], DEBUG_PULLUPS_ENABLED ? 1 : 0, 0, 0);
    }
}

static void debug_mode_add_pin(uint8_t pin, uint8_t use_pullup, uint8_t active_low, uint8_t from_configuration)
{
    uint8_t i;

    if (debug_mode_is_reserved_pin(pin))
    {
        return;
    }

    for (i = 0; i < debug_pin_count_s; ++i)
    {
        if (debug_pins_s[i].pin == pin)
        {
            if (use_pullup)
            {
                debug_pins_s[i].use_pullup = 1;
            }
            if (active_low)
            {
                debug_pins_s[i].active_low = 1;
            }
            if (from_configuration)
            {
                debug_pins_s[i].from_configuration = 1;
            }
            return;
        }
    }

    if (debug_pin_count_s >= DEBUG_PIN_CAPACITY)
    {
        return;
    }

    debug_pins_s[debug_pin_count_s].pin = pin;
    debug_pins_s[debug_pin_count_s].use_pullup = use_pullup ? 1 : 0;
    debug_pins_s[debug_pin_count_s].active_low = active_low ? 1 : 0;
    debug_pins_s[debug_pin_count_s].from_configuration = from_configuration ? 1 : 0;
    debug_pin_state_s[debug_pin_count_s] = 0;
    ++debug_pin_count_s;
}

static void debug_mode_wait_for_host(void)
{
    uint16_t attempts = 0;
    while (attempts < 1000 && !USBSerial())
    {
        delay(5);
        ++attempts;
    }
}

static void debug_mode_print_banner(void)
{
    debug_mode_print_timestamp_prefix("debug");
    debug_serial_print_s("firmware debug mode active");
    debug_serial_println_only();

    debug_mode_print_timestamp_prefix("debug");
    debug_serial_print_s("monitoring ");
    debug_serial_print_i((long)debug_pin_count_s);
    debug_serial_print_s(" pins");
    debug_serial_println_only();
}

static void debug_mode_print_pin_snapshot(uint8_t index, uint8_t is_initial)
{
    char label[6];
    uint8_t raw;
    uint8_t active_low;
    uint8_t active;

    debug_mode_format_label(debug_pins_s[index].pin, label, sizeof(label));
    raw = debug_pin_state_s[index] ? 1 : 0;
    active_low = debug_pins_s[index].active_low ? 1 : 0;
    active = active_low ? (raw == 0) : (raw != 0);

    debug_mode_print_timestamp_prefix(is_initial ? "init" : "change");
    debug_serial_print_s(label);
    debug_serial_print_s(" level=");
    debug_serial_print_s(raw ? "HIGH" : "LOW");
    debug_serial_print_s(" raw=");
    debug_serial_print_c(raw ? '1' : '0');
    debug_serial_print_s(" active=");
    debug_serial_print_s(active ? "true" : "false");
    if (active_low)
    {
        debug_serial_print_s(" active_low");
    }
    if (debug_pins_s[index].from_configuration)
    {
        debug_serial_print_s(" configured");
    }
    debug_serial_println_only();
}

static void debug_mode_print_summary(void)
{
    char label[6];
    uint8_t i;

    debug_mode_print_timestamp_prefix("summary");
    for (i = 0; i < debug_pin_count_s; ++i)
    {
        if (i > 0)
        {
            debug_serial_print_s(" ");
        }
        debug_mode_format_label(debug_pins_s[i].pin, label, sizeof(label));
        debug_serial_print_s(label);
        debug_serial_print_c('=');
        debug_serial_print_c(debug_pin_state_s[i] ? '1' : '0');
    }
    debug_serial_println_only();
}

static void debug_mode_format_label(uint8_t pin, char *buffer, size_t buffer_length)
{
    uint8_t port;
    uint8_t bit;

    if (buffer_length < 5)
    {
        return;
    }

    port = (uint8_t)(pin / 10);
    bit = (uint8_t)(pin % 10);

    buffer[0] = 'P';
    buffer[1] = (char)('0' + port);
    buffer[2] = '.';
    buffer[3] = (char)('0' + bit);
    buffer[4] = '\0';
}

static uint8_t debug_mode_is_reserved_pin(uint8_t pin)
{
    return (uint8_t)((pin == 36U) || (pin == 37U));
}

static void debug_mode_print_timestamp_prefix(const char *tag)
{
    debug_serial_print_s("[");
    debug_serial_print_s((char *)tag);
    debug_serial_print_s(" ");
    debug_serial_print_i((long)millis());
    debug_serial_print_s("ms] ");
}

static uint8_t debug_mode_confirm_change(uint8_t pin, uint8_t previous_state)
{
#if DEBUG_NOISE_FILTER_ENABLED
    const uint8_t samples = (DEBUG_CONFIRM_SAMPLES == 0U) ? 1U : DEBUG_CONFIRM_SAMPLES;
    uint8_t confirmations = 0;
    uint8_t i;

    for (i = 0; i < samples; ++i)
    {
        uint8_t sample = (uint8_t)(digitalRead(pin) ? 1 : 0);
        if (sample != previous_state)
        {
            ++confirmations;
        }
        delay(DEBUG_CONFIRM_DELAY_MS);
    }

    return (uint8_t)(confirmations > (samples / 2U));
#else
    (void)pin;
    (void)previous_state;
    return 1;
#endif
}

static void debug_serial_print_c(char value)
{
    USBSerial_write(value);
}

static void debug_serial_print_s(const char *value)
{
    if (value == NULL)
    {
        return;
    }

    while (1)
    {
        char current = *value++;
        if (current == '\0')
        {
            break;
        }
        USBSerial_write(current);
    }
}

static void debug_serial_println_only(void)
{
    debug_serial_print_c('\r');
    debug_serial_print_c('\n');
}

static void debug_serial_print_i(long value)
{
    char buffer[12];
    uint8_t index = sizeof(buffer);
    long remaining = value;
    uint8_t is_negative = 0;

    buffer[--index] = '\0';

    if (remaining < 0)
    {
        is_negative = 1;
        remaining = -remaining;
    }

    do
    {
        uint8_t digit = (uint8_t)(remaining % 10L);
        buffer[--index] = (char)('0' + digit);
        remaining /= 10L;
    } while (remaining > 0);

    if (is_negative)
    {
        buffer[--index] = '-';
    }

    debug_serial_print_s(&buffer[index]);
}

#endif
