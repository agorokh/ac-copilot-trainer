#pragma once

#include "../../configuration.h"

#if CONFIGURATION_DEBUG_MODE

// Based on the CH55xDuino CDC reference implementation.

// clang-format off
#include <stdint.h>
#include "include/ch5xx.h"
#include "include/ch5xx_usb.h"
#include "usbCommonDescriptors/StdDescriptors.h"
#include "usbCommonDescriptors/CDCClassCommon.h"
// clang-format on

#define EP0_ADDR 0
#define EP1_ADDR 10
#define EP2_ADDR 20

#define CDC_NOTIFICATION_EPADDR 0x81
#define CDC_NOTIFICATION_EPSIZE 0x08
#define CDC_TX_EPADDR 0x82
#define CDC_RX_EPADDR 0x02
#define CDC_TXRX_EPSIZE 0x40

typedef struct
{
    USB_Descriptor_Configuration_Header_t Config;
    USB_Descriptor_Interface_Association_t CdcIad;
    USB_Descriptor_Interface_t CciInterface;
    USB_CDC_Descriptor_FunctionalHeader_t CciHeader;
    USB_CDC_Descriptor_FunctionalACM_t CciAcm;
    USB_CDC_Descriptor_FunctionalUnion_t CciUnion;
    USB_Descriptor_Endpoint_t CciNotification;
    USB_Descriptor_Interface_t DciInterface;
    USB_Descriptor_Endpoint_t DciOutEndpoint;
    USB_Descriptor_Endpoint_t DciInEndpoint;
} usb_cdc_configuration_t;

enum
{
    INTERFACE_ID_CDC_CCI = 0,
    INTERFACE_ID_CDC_DCI = 1,
};

enum
{
    CDC_REQUEST_SET_LINE_CODING = 0x20,
    CDC_REQUEST_GET_LINE_CODING = 0x21,
    CDC_REQUEST_SET_CONTROL_LINE_STATE = 0x22,
};

extern __code USB_Descriptor_Device_t DeviceDescriptor;
extern __code usb_cdc_configuration_t ConfigurationDescriptor;
extern __code uint8_t LanguageDescriptor[];
extern __code uint16_t SerialDescriptor[];
extern __code uint16_t ProductDescriptor[];
extern __code uint16_t ManufacturerDescriptor[];
extern __code uint16_t InterfaceDescriptor[];

#endif
