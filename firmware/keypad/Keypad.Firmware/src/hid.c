#include <Arduino.h>
#include "../configuration.h"
#include "userUsbHidKeyboardMouse/USBHIDKeyboardMouse.h"
#include "led.h"
#include "hid.h"
#include "configuration_data.h"

#if !CONFIGURATION_DEBUG_MODE

#define HID_CONSUMER_VOLUME_INCREMENT 0x00E9
#define HID_CONSUMER_VOLUME_DECREMENT 0x00EA
#define HID_CONSUMER_MUTE 0x00E2
#define HID_CONSUMER_PLAY_PAUSE 0x00CD
#define HID_CONSUMER_SCAN_NEXT 0x00B5
#define HID_CONSUMER_SCAN_PREV 0x00B6
#define HID_CONSUMER_STOP 0x00B7

static int consumer_volume_pending_s = 0;
static uint8_t consumer_phase_s = 0; // 0 idle, 1 waiting to release

static void hid_run_key_sequence(hid_key_sequence_t sequence, hid_trigger_mode_t mode)
{
  uint8_t i;

  if (mode == HID_TRIGGER_RELEASE)
  {
    return;
  }

  for (i = 0; i < sequence.length; i++)
  {
    hid_key_step_t *step = &sequence.steps[i];
    switch (step->kind)
    {
    case HID_STEP_PAUSE:
      if (step->gap_ms > 0)
      {
        delay(step->gap_ms);
      }
      break;
    case HID_STEP_MOUSE:
      switch (step->pointer_type)
      {
      case HID_POINTER_MOVE_UP:
        Mouse_move(0, -(int8_t)step->pointer_value);
        break;
      case HID_POINTER_MOVE_DOWN:
        Mouse_move(0, (int8_t)step->pointer_value);
        break;
      case HID_POINTER_MOVE_LEFT:
        Mouse_move(-(int8_t)step->pointer_value, 0);
        break;
      case HID_POINTER_MOVE_RIGHT:
        Mouse_move((int8_t)step->pointer_value, 0);
        break;
      case HID_POINTER_LEFT_CLICK:
        Mouse_click(MOUSE_LEFT);
        break;
      case HID_POINTER_RIGHT_CLICK:
        Mouse_click(MOUSE_RIGHT);
        break;
      case HID_POINTER_SCROLL_UP:
        Mouse_scroll(step->pointer_value);
        break;
      case HID_POINTER_SCROLL_DOWN:
        Mouse_scroll(-(int8_t)step->pointer_value);
        break;
      default:
        break;
      }
      if (step->gap_ms > 0)
      {
        delay(step->gap_ms);
      }
      break;
    case HID_STEP_FUNCTION:
      if (step->functionPointer)
      {
        uint8_t times = step->function_value == 0 ? 1 : step->function_value;
        while (times--)
        {
          step->functionPointer(mode);
        }
      }
      if (step->gap_ms > 0)
      {
        delay(step->gap_ms);
      }
      break;
    case HID_STEP_KEY:
    default:
    {
      uint8_t mods = step->modifiers;
      uint8_t hold_ms = step->hold_ms;
      uint8_t gap_ms = step->gap_ms;
      uint8_t key = step->keycode;

      if (mods & 0x01) Keyboard_press(KEY_LEFT_CTRL);
      if (mods & 0x02) Keyboard_press(KEY_LEFT_SHIFT);
      if (mods & 0x04) Keyboard_press(KEY_LEFT_ALT);
      if (mods & 0x08) Keyboard_press(KEY_LEFT_GUI);

      if (key != 0)
      {
        Keyboard_press(key);
      }
      if (hold_ms == 0)
      {
        hold_ms = 10; // default hold for reliability
      }
      delay(hold_ms);
      Keyboard_releaseAll();

      if (gap_ms > 0)
      {
        delay(gap_ms);
      }
      break;
    }
    }
  }
}

static void hid_run_binding(const hid_binding_t *binding, hid_trigger_mode_t mode)
{
  switch (binding->type)
  {
  case HID_BINDING_SEQUENCE:
    hid_run_key_sequence(binding->function.sequence, mode);
    break;
  case HID_BINDING_NULL:
  default:
    break;
  }
}

void hid_consumer_volume_up(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  consumer_volume_pending_s++;
}

void hid_consumer_volume_down(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  consumer_volume_pending_s--;
}

void hid_consumer_mute(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  Keyboard_consumer_send(HID_CONSUMER_MUTE);
}

void hid_consumer_media_play_pause(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  Keyboard_consumer_send(HID_CONSUMER_PLAY_PAUSE);
}

void hid_consumer_media_next(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  Keyboard_consumer_send(HID_CONSUMER_SCAN_NEXT);
}

void hid_consumer_media_previous(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  Keyboard_consumer_send(HID_CONSUMER_SCAN_PREV);
}

void hid_consumer_media_stop(hid_trigger_mode_t mode)
{
  if (mode != HID_TRIGGER_PRESS && mode != HID_TRIGGER_CLICK)
  {
    return;
  }
  Keyboard_consumer_send(HID_CONSUMER_STOP);
}

void hid_handle_button(size_t button_index, hid_trigger_mode_t mode)
{
  if (button_index >= button_binding_count)
  {
    return;
  }

  const button_binding_t *binding = &button_bindings[button_index];

#if NEO_COUNT > 0
  if (binding->led_index >= 0)
  {
    if (mode == HID_TRIGGER_PRESS)
    {
      led_set_key_state(binding->led_index, true);
    }
    else if (mode == HID_TRIGGER_RELEASE)
    {
      led_set_key_state(binding->led_index, false);
    }
  }
#endif

  hid_run_binding(&binding->function, mode);
}

void hid_handle_encoder(size_t encoder_index, bool clockwise)
{
  if (encoder_index >= encoder_binding_count)
  {
    return;
  }

  const encoder_binding_t *binding = &encoder_bindings[encoder_index];
  const hid_binding_t *fn = clockwise ? &binding->clockwise : &binding->counter_clockwise;
  hid_run_binding(fn, HID_TRIGGER_CLICK);
}

void hid_service(void)
{
  if (consumer_phase_s == 1)
  {
    if (Keyboard_consumer_try_send(0))
    {
      consumer_phase_s = 0;
    }
    return;
  }

  if (consumer_volume_pending_s > 0)
  {
    if (Keyboard_consumer_try_send(HID_CONSUMER_VOLUME_INCREMENT))
    {
      consumer_volume_pending_s--;
      consumer_phase_s = 1;
    }
  }
  else if (consumer_volume_pending_s < 0)
  {
    if (Keyboard_consumer_try_send(HID_CONSUMER_VOLUME_DECREMENT))
    {
      consumer_volume_pending_s++;
      consumer_phase_s = 1;
    }
  }
}

#endif
