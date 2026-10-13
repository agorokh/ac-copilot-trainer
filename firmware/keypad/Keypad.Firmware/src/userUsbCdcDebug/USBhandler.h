#pragma once

#include "../../configuration.h"

#if CONFIGURATION_DEBUG_MODE

// Based on the CH55xDuino CDC reference implementation.

// clang-format off
#include <stdint.h>
#include "include/ch5xx.h"
#include "include/ch5xx_usb.h"
#include "USBconstant.h"
// clang-format on

extern __xdata __at(EP0_ADDR) uint8_t Ep0Buffer[];
extern __xdata __at(EP1_ADDR) uint8_t Ep1Buffer[];
extern __xdata __at(EP2_ADDR) uint8_t Ep2Buffer[];

extern volatile __xdata uint8_t UsbConfig;
extern __data uint16_t SetupLen;
extern __data uint8_t SetupReq;
extern const __code uint8_t *__data ActiveDescriptor;

#define UsbSetupBuf ((PUSB_SETUP_REQ)Ep0Buffer)

void USBInterrupt(void);
void USB_EP0_SETUP(void);
void USB_EP0_IN(void);
void USB_EP0_OUT(void);
void USB_EP1_IN(void);
void USB_EP2_IN(void);
void USB_EP2_OUT(void);

#endif
