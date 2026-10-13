/* AC Copilot Trainer derivative of KeypadFlasher, CC-BY-SA-3.0. */
#include "profile_protocol.h"
#ifndef KEYPAD_MANAGED
#define KEYPAD_MANAGED 1
#endif
#if KEYPAD_MANAGED
#define QUEUE_SIZE 4
typedef struct { uint8_t sequence, control, pressed; } event_t;
static event_t events[QUEUE_SIZE];
static uint8_t head, count, sequence, epoch, managed, acknowledged, claimed;
static uint8_t color[3];
static uint32_t lease_started;
static uint16_t lease_ms;

void profile_init(void) {
  head = count = sequence = epoch = managed = acknowledged = claimed = 0;
  color[0] = 255; color[1] = color[2] = 0;
  lease_ms = 0; lease_started = 0;
}

uint8_t profile_receive(const uint8_t *p, uint8_t length, uint32_t now) {
  if (length != 9 || p[0] != 5 || p[1] != 1 || !p[6] || p[6] > 50 || p[7] || p[8])
    return 0;
  /* A timed-out epoch cannot revive stale held-key state. */
  if (!managed && claimed && p[2] == epoch) return 0;
  if (!managed || p[2] != epoch) { head = count = sequence = 0; }
  epoch = p[2]; claimed = managed = 1;
  acknowledged = 0;
  color[0] = p[3]; color[1] = p[4]; color[2] = p[5];
  lease_ms = (uint16_t)p[6] * 100;
  lease_started = now;
  return 1;
}

void profile_tick(uint32_t now) {
  if (managed && (uint32_t)(now - lease_started) >= lease_ms) {
    profile_disconnect();
  }
}

void profile_disconnect(void) {
  managed = 0; head = count = 0;
  color[0] = 255; color[1] = color[2] = 0;
}

void profile_event(uint8_t control, uint8_t pressed) {
  uint8_t slot;
  if (!managed || control < 1 || control > 6 || pressed > 1 ||
      ((control == 4 || control == 5) && !pressed)) return;
  /* Dropping a key-up is unsafe, and 8-bit sequence gaps can alias after 256
   * losses. End the lease on any overflow; old-epoch renewals are rejected and
   * the host's ACK timeout releases held actions before claiming a new epoch. */
  if (count == QUEUE_SIZE) { profile_disconnect(); return; }
  slot = (head + count) % QUEUE_SIZE;
  events[slot].sequence = sequence++;
  events[slot].control = control; events[slot].pressed = pressed;
  count++;
}

uint8_t profile_peek(uint8_t *p) {
  uint8_t i;
  if (!managed) return 0;
  for (i = 0; i < 9; i++) p[i] = 0;
  p[1] = 1; p[2] = epoch;
  if (!acknowledged) {
    p[0] = 6; p[3] = color[0]; p[4] = color[1]; p[5] = color[2]; p[6] = 1;
  } else if (count) {
    p[0] = 4; p[3] = events[head].sequence;
    p[4] = events[head].control; p[5] = events[head].pressed;
  } else return 0;
  return 1;
}

void profile_sent(void) {
  if (!acknowledged) acknowledged = 1;
  else if (count) { head = (head + 1) % QUEUE_SIZE; count--; }
}

void profile_color(uint8_t *rgb) {
  rgb[0] = color[0]; rgb[1] = color[1]; rgb[2] = color[2];
}

void profile_capability(uint8_t *p) {
  p[0] = 7; p[1] = 'A'; p[2] = 'C'; p[3] = 1; p[4] = epoch;
  p[5] = color[0]; p[6] = color[1]; p[7] = color[2]; p[8] = managed;
}
#else
void profile_init(void) {}
#endif
