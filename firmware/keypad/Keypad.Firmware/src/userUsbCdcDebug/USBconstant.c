#include "USBconstant.h"

#if CONFIGURATION_DEBUG_MODE

// Based on the CH55xDuino CDC reference implementation.

__code USB_Descriptor_Device_t DeviceDescriptor = {
    .Header = { .Size = sizeof(USB_Descriptor_Device_t), .Type = DTYPE_Device },
    .USBSpecification = VERSION_BCD(1, 1, 0),
    .Class = 0xEF,
    .SubClass = 0x02,
    .Protocol = 0x01,
    .Endpoint0Size = DEFAULT_ENDP0_SIZE,
    .VendorID = 0x1209,
    .ProductID = 0xC56D,
    .ReleaseNumber = VERSION_BCD(1, 0, 0),
    .ManufacturerStrIndex = 1,
    .ProductStrIndex = 2,
    .SerialNumStrIndex = 3,
    .NumberOfConfigurations = 1
};

__code usb_cdc_configuration_t ConfigurationDescriptor = {
    .Config = {
        .Header = { .Size = sizeof(USB_Descriptor_Configuration_Header_t), .Type = DTYPE_Configuration },
        .TotalConfigurationSize = sizeof(usb_cdc_configuration_t),
        .TotalInterfaces = 2,
        .ConfigurationNumber = 1,
        .ConfigurationStrIndex = NO_DESCRIPTOR,
        .ConfigAttributes = USB_CONFIG_ATTR_RESERVED,
        .MaxPowerConsumption = USB_CONFIG_POWER_MA(200)
    },
    .CdcIad = {
        .Header = { .Size = sizeof(USB_Descriptor_Interface_Association_t), .Type = DTYPE_InterfaceAssociation },
        .FirstInterfaceIndex = INTERFACE_ID_CDC_CCI,
        .TotalInterfaces = 2,
        .Class = CDC_CSCP_CDCClass,
        .SubClass = CDC_CSCP_ACMSubclass,
        .Protocol = CDC_CSCP_ATCommandProtocol,
        .IADStrIndex = 4
    },
    .CciInterface = {
        .Header = { .Size = sizeof(USB_Descriptor_Interface_t), .Type = DTYPE_Interface },
        .InterfaceNumber = INTERFACE_ID_CDC_CCI,
        .AlternateSetting = 0,
        .TotalEndpoints = 1,
        .Class = CDC_CSCP_CDCClass,
        .SubClass = CDC_CSCP_ACMSubclass,
        .Protocol = CDC_CSCP_ATCommandProtocol,
        .InterfaceStrIndex = 4
    },
    .CciHeader = {
        .Header = { .Size = sizeof(USB_CDC_Descriptor_FunctionalHeader_t), .Type = CDC_DTYPE_CSInterface },
        .Subtype = CDC_DSUBTYPE_CSInterface_Header,
        .CDCSpecification = VERSION_BCD(1, 1, 0)
    },
    .CciAcm = {
        .Header = { .Size = sizeof(USB_CDC_Descriptor_FunctionalACM_t), .Type = CDC_DTYPE_CSInterface },
        .Subtype = CDC_DSUBTYPE_CSInterface_ACM,
        .Capabilities = 0x02
    },
    .CciUnion = {
        .Header = { .Size = sizeof(USB_CDC_Descriptor_FunctionalUnion_t), .Type = CDC_DTYPE_CSInterface },
        .Subtype = CDC_DSUBTYPE_CSInterface_Union,
        .MasterInterfaceNumber = INTERFACE_ID_CDC_CCI,
        .SlaveInterfaceNumber = INTERFACE_ID_CDC_DCI
    },
    .CciNotification = {
        .Header = { .Size = sizeof(USB_Descriptor_Endpoint_t), .Type = DTYPE_Endpoint },
        .EndpointAddress = CDC_NOTIFICATION_EPADDR,
        .Attributes = EP_TYPE_INTERRUPT | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA,
        .EndpointSize = CDC_NOTIFICATION_EPSIZE,
        .PollingIntervalMS = 0x40
    },
    .DciInterface = {
        .Header = { .Size = sizeof(USB_Descriptor_Interface_t), .Type = DTYPE_Interface },
        .InterfaceNumber = INTERFACE_ID_CDC_DCI,
        .AlternateSetting = 0,
        .TotalEndpoints = 2,
        .Class = CDC_CSCP_CDCDataClass,
        .SubClass = CDC_CSCP_NoDataSubclass,
        .Protocol = CDC_CSCP_NoDataProtocol,
        .InterfaceStrIndex = 4
    },
    .DciOutEndpoint = {
        .Header = { .Size = sizeof(USB_Descriptor_Endpoint_t), .Type = DTYPE_Endpoint },
        .EndpointAddress = CDC_RX_EPADDR,
        .Attributes = EP_TYPE_BULK | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA,
        .EndpointSize = CDC_TXRX_EPSIZE,
        .PollingIntervalMS = 0x00
    },
    .DciInEndpoint = {
        .Header = { .Size = sizeof(USB_Descriptor_Endpoint_t), .Type = DTYPE_Endpoint },
        .EndpointAddress = CDC_TX_EPADDR,
        .Attributes = EP_TYPE_BULK | ENDPOINT_ATTR_NO_SYNC | ENDPOINT_USAGE_DATA,
        .EndpointSize = CDC_TXRX_EPSIZE,
        .PollingIntervalMS = 0x00
    }
};

__code uint8_t LanguageDescriptor[] = { 0x04, 0x03, 0x09, 0x04 };

__code uint16_t SerialDescriptor[] = {
    ((6 + 1) * 2) | (DTYPE_String << 8),
    'D','E','B','U','G','1'
};

__code uint16_t ProductDescriptor[] = {
    ((19 + 1) * 2) | (DTYPE_String << 8),
    'K','e','y','p','a','d',' ','D','e','b','u','g',' ','S','e','r','i','a','l'
};

__code uint16_t ManufacturerDescriptor[] = {
    ((6 + 1) * 2) | (DTYPE_String << 8),
    'O','p','e','n','A','I'
};

__code uint16_t InterfaceDescriptor[] = {
    ((13 + 1) * 2) | (DTYPE_String << 8),
    'D','e','b','u','g',' ','C','D','C',' ','I','F','0'
};

#endif
