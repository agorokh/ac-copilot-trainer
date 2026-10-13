// Based on the CH55xDuino CDC reference implementation.

#include "../../configuration.h"

#if CONFIGURATION_DEBUG_MODE

#include "USBhandler.h"
#include "USBconstant.h"

void resetCDCParameters(void);
void setLineCodingHandler(void);
uint16_t getLineCodingHandler(void);
void setControlLineStateHandler(void);

__xdata __at(EP0_ADDR) uint8_t Ep0Buffer[8];
__xdata __at(EP1_ADDR) uint8_t Ep1Buffer[8];
__xdata __at(EP2_ADDR) uint8_t Ep2Buffer[128];

#if defined(USER_USB_RAM)
#if (EP2_ADDR + 128) > USER_USB_RAM
#error "Not enough USB RAM for CDC mode"
#endif
#endif

__data uint16_t SetupLen;
__data uint8_t SetupReq;
volatile __xdata uint8_t UsbConfig;
const __code uint8_t *__data ActiveDescriptor;

static inline void NOP_Process(void) {}

void USB_EP0_SETUP(void)
{
    __data uint8_t len = USB_RX_LEN;
    if (len == sizeof(USB_SETUP_REQ))
    {
        SetupLen = ((uint16_t)UsbSetupBuf->wLengthH << 8) | UsbSetupBuf->wLengthL;
        len = 0;
        SetupReq = UsbSetupBuf->bRequest;

        if ((UsbSetupBuf->bRequestType & USB_REQ_TYP_MASK) != USB_REQ_TYP_STANDARD)
        {
            switch (UsbSetupBuf->bRequestType & USB_REQ_TYP_MASK)
            {
            case USB_REQ_TYP_CLASS:
                switch (SetupReq)
                {
                case CDC_REQUEST_GET_LINE_CODING:
                    len = getLineCodingHandler();
                    break;
                case CDC_REQUEST_SET_CONTROL_LINE_STATE:
                    setControlLineStateHandler();
                    break;
                case CDC_REQUEST_SET_LINE_CODING:
                    break;
                default:
                    len = 0xFF;
                    break;
                }
                break;
            default:
                len = 0xFF;
                break;
            }
        }
        else
        {
            switch (SetupReq)
            {
            case USB_GET_DESCRIPTOR:
                switch (UsbSetupBuf->wValueH)
                {
                case DTYPE_Device:
                    ActiveDescriptor = (__code uint8_t *)DeviceDescriptor;
                    len = sizeof(USB_Descriptor_Device_t);
                    break;
                case DTYPE_Configuration:
                    ActiveDescriptor = (__code uint8_t *)ConfigurationDescriptor;
                    len = sizeof(usb_cdc_configuration_t);
                    break;
                case DTYPE_String:
                    if (UsbSetupBuf->wValueL == 0)
                    {
                        ActiveDescriptor = (__code uint8_t *)LanguageDescriptor;
                    }
                    else if (UsbSetupBuf->wValueL == 1)
                    {
                        ActiveDescriptor = (__code uint8_t *)ManufacturerDescriptor;
                    }
                    else if (UsbSetupBuf->wValueL == 2)
                    {
                        ActiveDescriptor = (__code uint8_t *)ProductDescriptor;
                    }
                    else if (UsbSetupBuf->wValueL == 3)
                    {
                        ActiveDescriptor = (__code uint8_t *)SerialDescriptor;
                    }
                    else if (UsbSetupBuf->wValueL == 4)
                    {
                        ActiveDescriptor = (__code uint8_t *)InterfaceDescriptor;
                    }
                    else
                    {
                        len = 0xFF;
                        break;
                    }
                    len = ActiveDescriptor[0];
                    break;
                default:
                    len = 0xFF;
                    break;
                }

                if (len != 0xFF)
                {
                    if (SetupLen > len)
                    {
                        SetupLen = len;
                    }

                    len = (SetupLen >= DEFAULT_ENDP0_SIZE) ? DEFAULT_ENDP0_SIZE : SetupLen;

                    for (__data uint8_t i = 0; i < len; ++i)
                    {
                        Ep0Buffer[i] = ActiveDescriptor[i];
                    }
                    SetupLen -= len;
                    ActiveDescriptor += len;
                }
                break;

            case USB_SET_ADDRESS:
                SetupLen = UsbSetupBuf->wValueL;
                break;

            case USB_GET_CONFIGURATION:
                Ep0Buffer[0] = UsbConfig;
                if (SetupLen >= 1)
                {
                    len = 1;
                }
                break;

            case USB_SET_CONFIGURATION:
                UsbConfig = UsbSetupBuf->wValueL;
                break;

            case USB_CLEAR_FEATURE:
            case USB_SET_FEATURE:
            case USB_GET_STATUS:
                /* Rely on default handling below */
                break;

            default:
                len = 0xFF;
                break;
            }
        }
    }
    else
    {
        len = 0xFF;
    }

    if (len == 0xFF)
    {
        SetupReq = 0xFF;
        UEP0_CTRL = bUEP_R_TOG | bUEP_T_TOG | UEP_R_RES_STALL | UEP_T_RES_STALL;
    }
    else
    {
        UEP0_T_LEN = len;
        UEP0_CTRL = bUEP_R_TOG | bUEP_T_TOG | UEP_R_RES_ACK | UEP_T_RES_ACK;
    }
}

void USB_EP0_IN(void)
{
    switch (SetupReq)
    {
    case USB_GET_DESCRIPTOR:
    {
        __data uint8_t len = (SetupLen >= DEFAULT_ENDP0_SIZE) ? DEFAULT_ENDP0_SIZE : SetupLen;
        for (__data uint8_t i = 0; i < len; ++i)
        {
            Ep0Buffer[i] = ActiveDescriptor[i];
        }
        SetupLen -= len;
        ActiveDescriptor += len;
        UEP0_T_LEN = len;
        UEP0_CTRL ^= bUEP_T_TOG;
        break;
    }
    case USB_SET_ADDRESS:
        USB_DEV_AD = (USB_DEV_AD & bUDA_GP_BIT) | SetupLen;
        UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        break;
    default:
        UEP0_T_LEN = 0;
        UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        break;
    }
}

void USB_EP0_OUT(void)
{
    if (SetupReq == CDC_REQUEST_SET_LINE_CODING && U_TOG_OK)
    {
        setLineCodingHandler();
        UEP0_T_LEN = 0;
        UEP0_CTRL |= UEP_R_RES_ACK | UEP_T_RES_ACK;
    }
    else
    {
        UEP0_T_LEN = 0;
        UEP0_CTRL |= UEP_R_RES_ACK | UEP_T_RES_NAK;
    }
}

void USB_EP1_IN(void)
{
    UEP1_T_LEN = 0;
    UEP1_CTRL = (UEP1_CTRL & ~MASK_UEP_T_RES) | UEP_T_RES_NAK;
}

#pragma save
#pragma nooverlay
void USBInterrupt(void)
{
    if (UIF_TRANSFER)
    {
        __data uint8_t endpoint = USB_INT_ST & MASK_UIS_ENDP;
        switch (USB_INT_ST & MASK_UIS_TOKEN)
        {
        case UIS_TOKEN_OUT:
            switch (endpoint)
            {
            case 0: USB_EP0_OUT(); break;
            case 2: USB_EP2_OUT(); break;
            default: break;
            }
            break;
        case UIS_TOKEN_IN:
            switch (endpoint)
            {
            case 0: USB_EP0_IN(); break;
            case 1: USB_EP1_IN(); break;
            case 2: USB_EP2_IN(); break;
            default: break;
            }
            break;
        case UIS_TOKEN_SETUP:
            if (endpoint == 0)
            {
                USB_EP0_SETUP();
            }
            break;
        default:
            break;
        }
        UIF_TRANSFER = 0;
    }

    if (UIF_BUS_RST)
    {
        UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
        UEP1_CTRL = bUEP_AUTO_TOG | UEP_T_RES_NAK;
        UEP2_CTRL = bUEP_AUTO_TOG | UEP_T_RES_NAK | UEP_R_RES_ACK;
        USB_DEV_AD = 0x00;
        UIF_SUSPEND = 0;
        UIF_TRANSFER = 0;
        UIF_BUS_RST = 0;
        UsbConfig = 0;
        resetCDCParameters();
    }

    if (UIF_SUSPEND)
    {
        UIF_SUSPEND = 0;
        if ((USB_MIS_ST & bUMS_SUSPEND) == 0)
        {
            USB_INT_FG = 0xFF;
        }
    }
}
#pragma restore

void USBDeviceCfg(void)
{
    USB_CTRL = 0x00;
    USB_CTRL &= ~bUC_HOST_MODE;
    USB_CTRL |= bUC_DEV_PU_EN | bUC_INT_BUSY | bUC_DMA_EN;
    USB_DEV_AD = 0x00;
    USB_CTRL &= ~bUC_LOW_SPEED;
    UDEV_CTRL &= ~bUD_LOW_SPEED;
#if defined(CH551) || defined(CH552) || defined(CH549)
    UDEV_CTRL = bUD_PD_DIS;
#endif
#if defined(CH559)
    UDEV_CTRL = bUD_DP_PD_DIS;
#endif
    UDEV_CTRL |= bUD_PORT_EN;
}

void USBDeviceIntCfg(void)
{
    USB_INT_EN |= bUIE_SUSPEND;
    USB_INT_EN |= bUIE_TRANSFER;
    USB_INT_EN |= bUIE_BUS_RST;
    USB_INT_FG |= 0x1F;
    IE_USB = 1;
    EA = 1;
}

void USBDeviceEndPointCfg(void)
{
#if defined(CH559)
    UEP0_DMA_H = ((uint16_t)Ep0Buffer >> 8);
    UEP0_DMA_L = ((uint16_t)Ep0Buffer >> 0);
    UEP1_DMA_H = ((uint16_t)Ep1Buffer >> 8);
    UEP1_DMA_L = ((uint16_t)Ep1Buffer >> 0);
    UEP2_DMA_H = ((uint16_t)Ep2Buffer >> 8);
    UEP2_DMA_L = ((uint16_t)Ep2Buffer >> 0);
#else
    UEP0_DMA = (uint16_t)Ep0Buffer;
    UEP1_DMA = (uint16_t)Ep1Buffer;
    UEP2_DMA = (uint16_t)Ep2Buffer;
#endif

    UEP2_3_MOD = 0x0C;
    UEP1_CTRL = bUEP_AUTO_TOG | UEP_T_RES_NAK;
    UEP2_CTRL = bUEP_AUTO_TOG | UEP_T_RES_NAK | UEP_R_RES_ACK;
    UEP4_1_MOD = 0x40;
    UEP0_CTRL = UEP_R_RES_ACK | UEP_T_RES_NAK;
}

#endif
