#ifndef PROFILE_PROTOCOL_H
#define PROFILE_PROTOCOL_H
#include <stdint.h>
/* ACK and events share one nine-byte interrupt IN endpoint. State lives only in
 * the main loop; USB OUT is first copied into its interrupt-safe mailbox. */
void profile_init(void);
uint8_t profile_receive(const uint8_t *packet, uint8_t length, uint32_t now);
void profile_tick(uint32_t now);
void profile_disconnect(void);
void profile_event(uint8_t control, uint8_t pressed);
uint8_t profile_peek(uint8_t *packet);
void profile_sent(void);
void profile_capability(uint8_t *packet);
void profile_color(uint8_t *rgb);
#endif
