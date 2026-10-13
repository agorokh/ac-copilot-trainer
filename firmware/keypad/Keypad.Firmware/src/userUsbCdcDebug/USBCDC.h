#pragma once

#include "../../configuration.h"

#if CONFIGURATION_DEBUG_MODE

#include <stdint.h>
#include <stdbool.h>

bool USBSerial(void);
void USBInit(void);
void USBInterrupt(void);
void USBDeviceCfg(void);
void USBDeviceIntCfg(void);
void USBDeviceEndPointCfg(void);
void USBSerial_flush(void);
uint8_t USBSerial_available(void);
uint8_t USBSerial_write(char value);
uint8_t USBSerial_print_n(uint8_t *buffer, int length);
char USBSerial_read(void);

#endif
