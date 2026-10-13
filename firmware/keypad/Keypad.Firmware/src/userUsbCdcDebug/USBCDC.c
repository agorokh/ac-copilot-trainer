// Based on the CH55xDuino CDC reference implementation.

#include "../../configuration.h"

#if CONFIGURATION_DEBUG_MODE

// clang-format off
#include <stdint.h>
#include <stdbool.h>
#include "include/ch5xx.h"
#include "include/ch5xx_usb.h"
// clang-format on

#include "USBCDC.h"
#include "USBhandler.h"

#define LINE_CODING_SIZE 7

__xdata uint8_t LineCoding[LINE_CODING_SIZE] = {
    0x00, 0x96, 0x00, 0x00, // 38400 baud
    0x00,                   // 1 stop bit
    0x00,                   // no parity
    0x08                    // 8 data bits
};

volatile __xdata uint8_t USBByteCountEP2 = 0;
volatile __xdata uint8_t USBBufOutPointEP2 = 0;
volatile __bit UpPoint2BusyFlag = 0;
volatile __xdata uint8_t ControlLineState = 0;
__xdata uint8_t UsbWritePointer = 0;

void delayMicroseconds(__data uint16_t us);

void resetCDCParameters(void)
{
    USBByteCountEP2 = 0;
    UpPoint2BusyFlag = 0;
    UsbWritePointer = 0;
}

static uint8_t limitToEndpointPacket(uint8_t value)
{
    return value >= MAX_PACKET_SIZE ? (uint8_t)(MAX_PACKET_SIZE - 1) : value;
}

void setLineCodingHandler(void)
{
    for (__data uint8_t i = 0; i < LINE_CODING_SIZE && i < USB_RX_LEN; ++i)
    {
        LineCoding[i] = Ep0Buffer[i];
    }
}

uint16_t getLineCodingHandler(void)
{
    for (__data uint8_t i = 0; i < LINE_CODING_SIZE; ++i)
    {
        Ep0Buffer[i] = LineCoding[i];
    }
    return LINE_CODING_SIZE;
}

void setControlLineStateHandler(void)
{
    ControlLineState = Ep0Buffer[2];
}

static uint8_t waitForEndpoint(void)
{
    __data uint16_t attempts = 0;
    while (UpPoint2BusyFlag)
    {
        if (++attempts >= 50000)
        {
            return 0;
        }
        delayMicroseconds(5);
    }
    return 1;
}

bool USBSerial(void)
{
    return ControlLineState > 0;
}

void USBSerial_flush(void)
{
    if (!UpPoint2BusyFlag && UsbWritePointer > 0)
    {
        UEP2_T_LEN = UsbWritePointer;
        UEP2_CTRL = (UEP2_CTRL & ~MASK_UEP_T_RES) | UEP_T_RES_ACK;
        UpPoint2BusyFlag = 1;

        if (UsbWritePointer == MAX_PACKET_SIZE)
        {
            if (waitForEndpoint())
            {
                UEP2_T_LEN = 0;
                UEP2_CTRL = (UEP2_CTRL & ~MASK_UEP_T_RES) | UEP_T_RES_ACK;
                UpPoint2BusyFlag = 1;
            }
        }
        UsbWritePointer = 0;
    }
}

uint8_t USBSerial_write(char value)
{
    if (ControlLineState == 0)
    {
        return 0;
    }

    while (true)
    {
        if (waitForEndpoint() == 0)
        {
            return 0;
        }

        if (UsbWritePointer < MAX_PACKET_SIZE)
        {
            Ep2Buffer[MAX_PACKET_SIZE + UsbWritePointer] = value;
            ++UsbWritePointer;
            return 1;
        }

        USBSerial_flush();
    }
}

uint8_t USBSerial_print_n(uint8_t *buffer, int length)
{
    if (ControlLineState == 0)
    {
        return 0;
    }

    while (length > 0)
    {
        if (waitForEndpoint() == 0)
        {
            return 0;
        }

        while (length > 0 && UsbWritePointer < MAX_PACKET_SIZE)
        {
            Ep2Buffer[MAX_PACKET_SIZE + UsbWritePointer] = *buffer++;
            ++UsbWritePointer;
            --length;
        }

        if (UsbWritePointer == MAX_PACKET_SIZE)
        {
            USBSerial_flush();
        }
    }

    return 1;
}

uint8_t USBSerial_available(void)
{
    return USBByteCountEP2;
}

char USBSerial_read(void)
{
    if (USBByteCountEP2 == 0)
    {
        return 0;
    }

    __data char value = Ep2Buffer[USBBufOutPointEP2];
    ++USBBufOutPointEP2;
    --USBByteCountEP2;

    if (USBByteCountEP2 == 0)
    {
        UEP2_CTRL = (UEP2_CTRL & ~MASK_UEP_R_RES) | UEP_R_RES_ACK;
    }

    return value;
}

void USB_EP2_IN(void)
{
    UEP2_T_LEN = 0;
    UEP2_CTRL = (UEP2_CTRL & ~MASK_UEP_T_RES) | UEP_T_RES_NAK;
    UpPoint2BusyFlag = 0;
}

void USB_EP2_OUT(void)
{
    if (U_TOG_OK)
    {
        USBByteCountEP2 = USB_RX_LEN;
        USBBufOutPointEP2 = 0;
        if (USBByteCountEP2 != 0)
        {
            UEP2_CTRL = (UEP2_CTRL & ~MASK_UEP_R_RES) | UEP_R_RES_NAK;
        }
    }
}

void USBInit(void)
{
    USBDeviceCfg();
    USBDeviceEndPointCfg();
    USBDeviceIntCfg();
}

#endif
