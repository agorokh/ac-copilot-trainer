#pragma once

#include <stdint.h>
#include <stddef.h>

typedef enum
{
  HID_TRIGGER_PRESS,
  HID_TRIGGER_RELEASE,
  HID_TRIGGER_CLICK,
} hid_trigger_mode_t;


typedef enum
{
  HID_POINTER_MOVE_UP,
  HID_POINTER_MOVE_DOWN,
  HID_POINTER_MOVE_LEFT,
  HID_POINTER_MOVE_RIGHT,
  HID_POINTER_LEFT_CLICK,
  HID_POINTER_RIGHT_CLICK,
  HID_POINTER_SCROLL_UP,
  HID_POINTER_SCROLL_DOWN
} hid_pointer_event_type_t;

typedef struct
{
  hid_pointer_event_type_t type;
  uint8_t value;
} hid_pointer_event_t;

typedef enum
{
  HID_STEP_KEY,
  HID_STEP_PAUSE,
  HID_STEP_FUNCTION,
  HID_STEP_MOUSE,
} hid_step_kind_t;

#ifndef HID_MAX_KEY_STEPS
#define HID_MAX_KEY_STEPS 16
#endif

typedef struct
{
  hid_step_kind_t kind;
  uint8_t keycode;
  uint8_t modifiers; // bitmask: 1=Ctrl, 2=Shift, 4=Alt, 8=GUI
  uint8_t hold_ms;   // how long to hold key+mods
  uint8_t gap_ms;    // delay after releasing before next step or gap after function/mouse
  void (*functionPointer)(hid_trigger_mode_t mode);
  uint8_t function_value;
  hid_pointer_event_type_t pointer_type;
  uint8_t pointer_value;
} hid_key_step_t;

typedef struct
{
  hid_key_step_t steps[HID_MAX_KEY_STEPS];
  uint8_t length;
} hid_key_sequence_t;

typedef enum
{
  HID_BINDING_SEQUENCE,
  HID_BINDING_NULL,
} hid_binding_type_t;

typedef struct
{
  hid_binding_type_t type;
  union
  {
    hid_key_sequence_t sequence;
  } function;
} hid_binding_t;


void hid_handle_button(size_t button_index, hid_trigger_mode_t mode);
void hid_handle_encoder(size_t encoder_index, bool clockwise);

void hid_consumer_volume_up(hid_trigger_mode_t mode);
void hid_consumer_volume_down(hid_trigger_mode_t mode);
void hid_consumer_mute(hid_trigger_mode_t mode);
void hid_consumer_media_play_pause(hid_trigger_mode_t mode);
void hid_consumer_media_next(hid_trigger_mode_t mode);
void hid_consumer_media_previous(hid_trigger_mode_t mode);
void hid_consumer_media_stop(hid_trigger_mode_t mode);

void hid_service(void);
