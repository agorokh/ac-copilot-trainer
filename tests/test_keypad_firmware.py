"""Native execution of the firmware protocol, without USB device access."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/keypad/Keypad.Firmware"


def test_vendor_protocol_native(tmp_path):
    source = FIRMWARE / "src/profile_protocol.c"
    assert source.is_file(), "firmware profile protocol is not implemented"
    compiler = shutil.which("cc")
    assert compiler, "native C compiler is required for firmware verification"
    harness = tmp_path / "harness.c"
    harness.write_text(r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "profile_protocol.h"
int main(void) {
  uint8_t p[9]={5,1,9,0,255,0,10,0,0}, r[9], control;
  profile_init(); profile_capability(r);
  assert(r[0]==7 && r[1]=='A' && r[2]=='C' && r[3]==1);
  assert(r[5]==255 && r[6]==0 && r[7]==0 && r[8]==0);
  assert(!profile_receive(p,8,0)); p[1]=2;
  assert(!profile_receive(p,9,0)); p[1]=1; p[7]=1;
  assert(!profile_receive(p,9,0)); p[7]=0; p[6]=0;
  assert(!profile_receive(p,9,0)); p[6]=51;
  assert(!profile_receive(p,9,0)); p[6]=10; p[0]=0xa2;
  assert(!profile_receive(p,9,0)); p[0]=5;
  assert(profile_receive(p,9,100));
  profile_event(1,1);
  assert(profile_peek(r) && r[0]==6 && r[2]==9 && r[4]==255 && r[6]==1);
  /* Busy USB retry cannot consume the pending ACK or event. */
  assert(profile_peek(r) && r[0]==6); profile_sent();
  assert(profile_peek(r) && r[0]==4 && r[3]==0 && r[4]==1 && r[5]==1);
  profile_sent(); profile_event(1,0);
  assert(profile_peek(r) && r[3]==1 && r[5]==0); profile_sent();
  for(control=1;control<=6;control++) {
    profile_event(control,1);
    assert(profile_peek(r) && r[4]==control && r[5]==1); profile_sent();
  }
  profile_event(0,1); profile_event(7,1); profile_event(4,0);
  assert(!profile_peek(r));
  /* Epoch changes clear old input and reset sequence; ACK always goes first. */
  profile_event(2,1); p[2]=10; assert(profile_receive(p,9,300));
  profile_event(6,0); assert(profile_peek(r) && r[0]==6); profile_sent();
  assert(profile_peek(r) && r[0]==4 && r[2]==10 && r[3]==0 && r[4]==6); profile_sent();
  /* More than queue capacity must expose a sequence gap, never hide lost ups. */
  for(control=0;control<10;control++) profile_event(1,control%2);
  assert(profile_peek(r) && r[3]>1);
  profile_tick(1300); profile_capability(r);
  assert(r[8]==0 && r[5]==255 && r[6]==0);
  assert(!profile_peek(r)); profile_event(1,1); assert(!profile_peek(r));
  /* Unsigned elapsed subtraction remains correct across millis wrap. */
  p[2]=11; p[6]=2; assert(profile_receive(p,9,UINT32_MAX-50));
  profile_tick(100); profile_capability(r); assert(r[8]==1);
  profile_tick(149); profile_capability(r); assert(r[8]==0 && r[5]==255);
  /* Reclaim after timeout needs a new epoch to suppress stale events. */
  assert(!profile_receive(p,9,150)); p[2]=12;
  assert(profile_receive(p,9,150));
  return 0;
}
""")
    result = subprocess.run(
        [
            compiler,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(source.parent),
            str(harness),
            str(source),
            "-o",
            str(tmp_path / "test"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    subprocess.run([str(tmp_path / "test")], check=True)


@pytest.mark.parametrize("managed", [0, 1])
def test_actual_hid_bindings_and_managed_suppression(tmp_path, managed):
    includes = tmp_path / "include"
    includes.mkdir()
    (includes / "ch5xx.h").write_text("#define __data\n#define __xdata\n")
    (includes / "ch5xx_usb.h").write_text("")
    (tmp_path / "Arduino.h").write_text(
        "#include <stdint.h>\n#include <stdbool.h>\nvoid delay(uint16_t n);\n"
    )
    harness = tmp_path / "hid_harness.c"
    harness.write_text(r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "configuration.h"
#include "src/hid.h"
#include "src/profile_protocol.h"
static uint8_t keys[32], key_count, releases, consumer_count, busy;
static uint16_t consumers[32];
void delay(uint16_t n) {(void)n;}
uint8_t Keyboard_press(uint8_t k) {keys[key_count++]=k;return 1;}
void Keyboard_releaseAll(void) {releases++;}
uint8_t Keyboard_consumer_send(uint16_t k) {consumers[consumer_count++]=k;return 1;}
uint8_t Keyboard_consumer_try_send(uint16_t k) {
  if(busy)return 0; consumers[consumer_count++]=k; return 1;
}
uint8_t Mouse_click(uint8_t k) {(void)k;return 1;}
uint8_t Mouse_move(int8_t x,int8_t y) {(void)x;(void)y;return 1;}
uint8_t Mouse_scroll(int8_t k) {(void)k;return 1;}
void led_set_key_state(int k,bool p) {(void)k;(void)p;}
int main(void) {
 uint8_t r[9], i, p[9]={5,1,42,0,255,0,50,0,0};
 profile_init();
#if KEYPAD_MANAGED
 assert(profile_receive(p,9,0)); assert(profile_peek(r)&&r[0]==6);profile_sent();
 for(i=0;i<4;i++) {
   hid_handle_button(i,HID_TRIGGER_PRESS);
   assert(profile_peek(r)&&r[4]==(i==3?6:i+1)&&r[5]==1);profile_sent();
   hid_handle_button(i,HID_TRIGGER_RELEASE);
   assert(profile_peek(r)&&r[5]==0);profile_sent();
 }
 hid_handle_encoder(0,true); assert(profile_peek(r)&&r[4]==4);profile_sent();
 hid_handle_encoder(0,false);assert(profile_peek(r)&&r[4]==5);profile_sent();
 profile_tick(5000);
 hid_handle_button(0,HID_TRIGGER_PRESS);hid_handle_encoder(0,true);hid_service();
 assert(!profile_peek(r));assert(key_count==0&&consumer_count==0);
#else
 (void)r;(void)p;
 for(i=0;i<3;i++) {hid_handle_button(i,HID_TRIGGER_PRESS);hid_handle_button(i,HID_TRIGGER_RELEASE);}
 assert(key_count==9 && releases==3);
 for(i=0;i<3;i++) {assert(keys[i*3]==0x80&&keys[i*3+1]==0x82);}
 assert(keys[2]=='a'&&keys[5]=='m'&&keys[8]=='s');
 hid_handle_button(3,HID_TRIGGER_PRESS);assert(consumers[0]==0xe2);
 hid_handle_encoder(0,true);busy=1;hid_service();assert(consumer_count==1);
 busy=0;hid_service();assert(consumers[1]==0xe9);hid_service();assert(consumers[2]==0);
 hid_handle_encoder(0,false);hid_service();assert(consumers[3]==0xea);
 busy=1;hid_service();assert(consumer_count==4);
 busy=0;hid_service();assert(consumers[4]==0);
#endif
 return 0;
}
""")
    result = subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            f"-DKEYPAD_MANAGED={managed}",
            "-I",
            str(tmp_path),
            "-I",
            str(FIRMWARE),
            str(harness),
            str(FIRMWARE / "src/hid.c"),
            str(FIRMWARE / "src/profile_protocol.c"),
            str(FIRMWARE / "configuration.c"),
            "-o",
            str(tmp_path / "hid"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    subprocess.run([str(tmp_path / "hid")], check=True)


def test_usb_vendor_descriptor_and_feature_are_implemented():
    descriptor = (FIRMWARE / "src/userUsbHidKeyboardMouse/USBconstant.c").read_text()
    handler = (FIRMWARE / "src/userUsbHidKeyboardMouse/USBhandler.c").read_text()
    assert "0x06, 0x31, 0xff" in descriptor
    assert "0x75, 0x08, 0x95, 0x08" in descriptor
    for report in (4, 5, 6, 7):
        assert f"0x85, 0x0{report}" in descriptor
    assert "profile_capability(capability)" in handler
    assert "UsbSetupBuf->wValueH != 3" in handler
    assert "capability[capability_offset + i]" in handler
    assert "USB_profile_reset();" in handler, "bus reset must clear a busy IN endpoint"
    sketch = (FIRMWARE / "Keypad.Firmware.ino").read_text()
    assert sketch.index("led_update();") < sketch.index("USBInit();")


def test_lease_keepalive_preserves_queue_and_sequence_wrap(tmp_path):
    harness = tmp_path / "keepalive.c"
    harness.write_text(r"""
#include <assert.h>
#include <stdint.h>
#include "profile_protocol.h"
int main(void) {
 uint8_t p[9]={5,1,1,255,0,0,10,0,0}, r[9]; unsigned i;
 profile_init();assert(profile_receive(p,9,0));profile_peek(r);profile_sent();
 profile_event(1,1);assert(profile_receive(p,9,900));
 assert(profile_peek(r)&&r[0]==6);profile_sent();
 assert(profile_peek(r)&&r[0]==4&&r[3]==0&&r[5]==1);profile_sent();
 profile_tick(1100);profile_capability(r);assert(r[8]==1);
 for(i=1;i<258;i++) {
   profile_event(4,1);assert(profile_peek(r)&&r[3]==(uint8_t)i);profile_sent();
 }
 profile_tick(1900);profile_capability(r);assert(r[8]==0);
 return 0;
}
""")
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE / "src"),
            str(harness),
            str(FIRMWARE / "src/profile_protocol.c"),
            "-o",
            str(tmp_path / "keepalive"),
        ],
        check=True,
    )
    subprocess.run([str(tmp_path / "keepalive")], check=True)


def test_hex_verifier_rejects_bad_checksum_and_bootloader_address(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("keypad_build", FIRMWARE.parent / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "firmware.hex"
    path.write_text(":0100000001FE\n:00000001FF\n")
    assert module.verify_hex(path)["bytes"] == 1
    path.write_text(":0100000001FD\n:00000001FF\n")
    with pytest.raises(ValueError, match="checksum"):
        module.verify_hex(path)
    path.write_text(":0138000001C6\n:00000001FF\n")
    with pytest.raises(ValueError, match="boundary"):
        module.verify_hex(path)
    path.write_text(":0100000001FE\n")
    with pytest.raises(ValueError, match="incomplete"):
        module.verify_hex(path)


def test_managed_buttons_debounce_before_emitting_edges(tmp_path):
    (tmp_path / "Arduino.h").write_text(
        "#include <stdint.h>\n#include <stdbool.h>\n#define INPUT_PULLUP 2\n"
        "#define INPUT 0\nvoid pinMode(uint8_t p,uint8_t m);\n"
        "uint8_t digitalRead(uint8_t p);\nuint32_t millis(void);\n"
    )
    harness = tmp_path / "buttons.c"
    harness.write_text(r"""
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include "configuration.h"
#include "src/hid.h"
#include "src/buttons.h"
const button_binding_t button_bindings[4]={{.pin=11,.active_low=true},
 {.pin=17,.active_low=true},{.pin=16,.active_low=true},{.pin=33,.active_low=true}};
const size_t button_binding_count=4;
static uint8_t pressed, edges; static uint32_t now;
void pinMode(uint8_t p,uint8_t m){(void)p;(void)m;}
uint8_t digitalRead(uint8_t p){return p==11?!pressed:1;}
uint32_t millis(void){return now;}
void hid_handle_button(size_t i,hid_trigger_mode_t m){assert(i==0);
 assert(m==(edges?HID_TRIGGER_RELEASE:HID_TRIGGER_PRESS));edges++;}
void led_show_bootloader_indicator(void){}
void BOOT_now(void){assert(0);}
int main(void){
 buttons_setup();pressed=1;now=1;buttons_update();assert(edges==0);
 pressed=0;now=3;buttons_update();assert(edges==0);
 pressed=1;now=4;buttons_update();now=8;buttons_update();assert(edges==0);
 now=9;buttons_update();assert(edges==1);
 pressed=0;now=10;buttons_update();now=14;buttons_update();assert(edges==1);
 now=15;buttons_update();assert(edges==2);return 0;
}
""")
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-I",
            str(tmp_path),
            "-I",
            str(FIRMWARE),
            str(harness),
            str(FIRMWARE / "src/buttons.c"),
            str(FIRMWARE / "src/configuration_data.c"),
            "-o",
            str(tmp_path / "buttons"),
        ],
        check=True,
    )
    subprocess.run([str(tmp_path / "buttons")], check=True)


def test_actual_usb_endpoint_functions_under_native_register_harness(tmp_path):
    """Execute actual EP0/EP1 functions; emulate registers, not protocol logic."""
    usb = FIRMWARE / "src/userUsbHidKeyboardMouse"
    handler = (usb / "USBhandler.c").read_text()
    hid = (usb / "USBHIDKeyboardMouse.c").read_text()
    ep0 = handler[handler.index("void USB_EP0_SETUP()") : handler.index("void USB_EP0_OUT()")]
    ep1 = hid[hid.index("void USB_EP1_OUT()") : hid.index("static uint8_t USB_EP1_send_consumer")]
    # Native compilers do not give SDCC's implicit address conversion to __code objects.
    ep0 = ep0.replace("DeviceDescriptor;", "&DeviceDescriptor;")
    ep0 = ep0.replace("*)ConfigurationDescriptor;", "*)&ConfigurationDescriptor;")
    constants = {
        "USB_REQ_TYP_MASK": 0x60,
        "USB_REQ_TYP_STANDARD": 0,
        "USB_REQ_TYP_VENDOR": 0x40,
        "USB_REQ_TYP_CLASS": 0x20,
        "USB_GET_DESCRIPTOR": 6,
        "USB_SET_ADDRESS": 5,
        "USB_GET_CONFIGURATION": 8,
        "USB_SET_CONFIGURATION": 9,
        "USB_GET_INTERFACE": 10,
        "USB_SET_INTERFACE": 11,
        "USB_CLEAR_FEATURE": 1,
        "USB_SET_FEATURE": 3,
        "USB_GET_STATUS": 0,
        "USB_REQ_RECIP_DEVICE": 0,
        "USB_REQ_RECIP_MASK": 31,
        "USB_REQ_RECIP_ENDP": 2,
        "DEFAULT_ENDP0_SIZE": 8,
        "bUEP_R_TOG": 0x80,
        "bUEP_T_TOG": 0x40,
        "MASK_UEP_T_RES": 3,
        "MASK_UEP_R_RES": 12,
        "UEP_R_RES_STALL": 12,
        "UEP_T_RES_STALL": 3,
        "UEP_T_RES_ACK": 0,
        "UEP_R_RES_ACK": 0,
        "UEP_T_RES_NAK": 2,
        "UEP_R_RES_NAK": 8,
        "bUDA_GP_BIT": 0x80,
        "KEYPAD_MANAGED": 1,
    }
    stubs = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "profile_protocol.h"
#define __data
#define __code
typedef struct {uint8_t bRequestType,bRequest,wValueL,wValueH,wIndexL,wIndexH,
 wLengthL,wLengthH;} USB_SETUP_REQ;
typedef struct {uint8_t unused[18];} USB_Descriptor_Device_t;
typedef struct {struct {uint8_t ConfigAttributes;} Config;
 struct {uint16_t HIDReportLength;} HID_KeyboardHID;} USB_Descriptor_Configuration_t;
static USB_Descriptor_Device_t DeviceDescriptor;
static USB_Descriptor_Configuration_t ConfigurationDescriptor;
static uint8_t LanguageDescriptor[4],ManufacturerDescriptor[4],ProductDescriptor[4],
 SerialDescriptor[4],ReportDescriptor[4];
static uint8_t Ep0Buffer[8],Ep1Buffer[128],capability[9],capability_offset;
#define UsbSetupBuf ((USB_SETUP_REQ*)Ep0Buffer)
static uint16_t SetupLen;static uint8_t SetupReq,usbMsgFlags,UsbConfig;
static uint8_t *pDescr;
static uint8_t USB_RX_LEN,UEP0_CTRL,UEP1_CTRL,UEP2_CTRL,UEP3_CTRL,UEP4_CTRL,
 UEP0_T_LEN,UEP1_T_LEN,USB_DEV_AD,IE_USB,U_TOG_OK,UpPoint1_Busy;
static uint8_t ProfileOutPending,ProfileOut[9],ProfileResetPending;
static uint32_t now;
uint32_t millis(void){return now;}
"""
    harness = tmp_path / "endpoints.c"
    harness.write_text(
        "\n".join(f"#define {key} {value}" for key, value in constants.items())
        + stubs
        + ep0
        + ep1
        + r"""
static void setup(uint8_t type,uint8_t report,uint8_t length) {
 USB_SETUP_REQ request={type,1,report,3,0,0,length,0};
 memcpy(Ep0Buffer,&request,8);USB_RX_LEN=8;USB_EP0_SETUP();
}
int main(void){
 uint8_t p[9]={5,1,77,0,255,0,10,0,0};
 profile_init();setup(0xa1,7,9);
 assert(UEP0_T_LEN==8&&Ep0Buffer[0]==7&&Ep0Buffer[1]=='A');
 USB_EP0_IN();assert(UEP0_T_LEN==1&&Ep0Buffer[0]==0);
 USB_EP0_IN();assert(UEP0_T_LEN==0);
 setup(0xa1,5,9);assert((UEP0_CTRL&15)==15);
 setup(0xa2,7,9);assert((UEP0_CTRL&15)==15);
 /* Unsynchronized and wrong-length output never reaches protocol state. */
 USB_RX_LEN=9;U_TOG_OK=0;memcpy(Ep1Buffer,p,9);USB_EP1_OUT();
 assert(!ProfileOutPending);U_TOG_OK=1;USB_RX_LEN=8;USB_EP1_OUT();
 assert(!ProfileOutPending);USB_RX_LEN=9;USB_EP1_OUT();
 assert(ProfileOutPending&&(UEP1_CTRL&12)==8);
 UsbConfig=1;IE_USB=1;USB_profile_service();
 assert(IE_USB&&UpPoint1_Busy&&UEP1_T_LEN==9&&Ep1Buffer[64]==6);
 profile_event(1,1);USB_profile_service();assert(Ep1Buffer[64]==6);
 UpPoint1_Busy=0;USB_profile_service();assert(Ep1Buffer[64]==4&&Ep1Buffer[68]==1);
 setup(0xa1,7,9);USB_EP0_IN();assert(Ep0Buffer[0]==1);
 USB_profile_reset();assert(!UpPoint1_Busy);USB_profile_service();
 setup(0xa1,7,9);USB_EP0_IN();assert(Ep0Buffer[0]==0);
 UpPoint1_Busy=0;now=1000;USB_profile_service();setup(0xa1,7,9);
 assert(Ep0Buffer[5]==255&&Ep0Buffer[6]==0);
 USB_EP0_IN();assert(Ep0Buffer[0]==0);return 0;
}
"""
    )
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-I",
            str(FIRMWARE / "src"),
            str(harness),
            str(FIRMWARE / "src/profile_protocol.c"),
            "-o",
            str(tmp_path / "endpoints"),
        ],
        check=True,
    )
    subprocess.run([str(tmp_path / "endpoints")], check=True)


def test_actual_managed_led_renderer_red_boot_green_lease_red_expiry(tmp_path):
    source = (FIRMWARE / "src/led.c").read_text()
    count = source[
        source.index("static uint8_t led_count(") : source.index("static uint8_t clamp_percent(")
    ]
    physical = source[
        source.index("static uint8_t led_physical_index(") : source.index(
            "void led_show_bootloader_indicator("
        )
    ]
    indicator = source[
        source.index("void led_show_bootloader_indicator(") : source.index("void led_init(")
    ]
    key_state = source[source.index("void led_set_key_state(") : source.index("void led_update()")]
    renderer = source[source.index("void led_update()") :].rsplit("\n#endif", 1)[0]
    harness = tmp_path / "led.c"
    harness.write_text(
        r"""
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include "configuration.h"
#include "src/profile_protocol.h"
#define NEO_REVERSED 0
const led_configuration_t led_configuration={.count=3,.brightness_percent=100};
static const led_configuration_t *led_cfg_s=&led_configuration;
static bool pressed_s[3];static uint8_t colors[3][3],frames;
void NEO_writeColor(uint8_t i,uint8_t r,uint8_t g,uint8_t b){
 assert(i<3);colors[i][0]=r;colors[i][1]=g;colors[i][2]=b;}
void NEO_update(void){frames++;}
"""
        + count
        + physical
        + indicator
        + key_state
        + renderer
        + r"""
static void color_is(uint8_t red,uint8_t green){
 uint8_t i;for(i=0;i<3;i++)assert(colors[i][0]==red&&colors[i][1]==green&&colors[i][2]==0);}
int main(void){
 uint8_t p[9]={5,1,2,0,255,0,10,0,0};
 profile_init();led_update();color_is(255,0);
 assert(profile_receive(p,9,0));led_update();color_is(0,255);
 led_set_key_state(0,true);profile_event(4,1);led_update();color_is(0,255);
 profile_tick(1000);led_update();color_is(255,0);
 led_show_bootloader_indicator();color_is(255,0);assert(frames==5);return 0;
}
"""
    )
    subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-I",
            str(FIRMWARE),
            str(harness),
            str(FIRMWARE / "src/profile_protocol.c"),
            "-o",
            str(tmp_path / "led"),
        ],
        check=True,
    )
    subprocess.run([str(tmp_path / "led")], check=True)
