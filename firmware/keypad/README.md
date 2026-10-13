# Racing keypad firmware

Prepared source and offline builds; **DO NOT FLASH** until the actual board,
outer-button pin order and ROM recovery have been verified. The acrylic case has
not been opened, and CH552 identity remains provisional. GPIO configuration:
buttons P11/P17/P16 (outer P11/P16 order unresolved), knob press P33, encoder
P31/P30, three WS2812 LEDs P34.

## Source and licence

Derived from AmyJeanes [KeypadFlasher](https://github.com/AmyJeanes/KeypadFlasher/tree/6de74402068c1e57febd65ce13cc6a111ed171ac)
commit `6de74402068c1e57febd65ce13cc6a111ed171ac`. Retained author notices include
Deqing Sun's USB implementation and Stefan Wagner's NeoPixel/GPIO code. Firmware
and modifications here remain **CC-BY-SA 3.0 Unported**; see [LICENCE](LICENCE).
This firmware subtree's licence is separate from the host application's licence.

The recovered previous always-red candidate added red before USB startup and red
recovery indication. This derivative adds the AC profile HID protocol, queued six
logical inputs, an RGB lease, red timeout fallback and capability discovery.

## Build without programming hardware

Use Arduino CLI and the official [CH55xDuino package](https://github.com/DeqingSun/ch55xduino)
pinned to **0.0.26**, with SDCC **build.13407_4**, MCS51Tools **2026.07.10**.
From the repository root:

```sh
arduino-cli --config-file firmware/keypad/Keypad.Firmware/arduino-cli.yaml core update-index
arduino-cli --config-file firmware/keypad/Keypad.Firmware/arduino-cli.yaml core install CH55xDuino:mcs51@0.0.26
python3 firmware/keypad/build.py
python3 -m pytest tests/test_keypad_firmware.py -q
```

If CLI is outside PATH, use `--arduino-cli /absolute/path/to/arduino-cli`. Generated
files stay in ignored `.scratch/keypad-build/`; there is no upload command. The
build script validates every Intel HEX checksum and verifies all application
addresses stay below CH552's `0x3800` ROM boundary. Build receipt hashes identify
the staged artifacts, and do not establish physical compatibility.

## Two separate variants

**Managed:** vendor HID collection `FF31:1`, VID/PID `1209:C55D`. Inputs emit
logical event reports only. Keyboard and consumer report descriptors retained
for compatibility are never used to execute physical controls in this build.
No active host lease means steady red and inert controls. After a timed-out
lease the host must claim a different epoch. This never falls back to computer
master volume.

**Baseline:** retains Ctrl+Alt+A/M/S, clockwise volume-up, counterclockwise
volume-down and knob-click mute, plus red styling. It has no vendor collection
or capability report; the profile controller must not open it for output. This
is an offline preservation candidate, not a dump of the original stock firmware.

Each vendor report is exactly nine bytes including its ID. IDs 4/6 are input
events/ACK, ID5 is the validated RGB lease output and GET_FEATURE7 advertises
`AC`, version1, current epoch/color and lease state. See the implementation plan
and runtime guide for the complete host contract. USB class requests other than
the supported capability query stall. No HID report invokes bootloader commands.

Each new epoch clears queued input and resets the sequence to zero. ACK precedes
that epoch's events. Busy USB preserves pending events. Queue overflow immediately
ends the lease, clears queued input and returns to red. Renewal of that invalidated
epoch is rejected; the host's renewal ACK timeout releases held actions and renegotiates.
No events are evicted silently: otherwise exactly 256 lost reports could wrap an
8-bit sequence and hide a lost key-up. Ordinary transport gaps likewise require
the host to clear held actions and obtain a new epoch.
Renewing the same active epoch acknowledges the color without clearing input.
Unsigned elapsed time handles the 32-bit `millis()` wrap.
Managed button transitions must remain stable for 5ms before being emitted. A USB
bus reset clears endpoint-busy state and invalidates the lease in the main loop,
so the host can reconnect with a new epoch and the LEDs return to red.

## Recovery and acceptance when the adapter arrives

The existing physical recovery mechanisms are retained: hold the knob while
powering on, or hold every configured button including the knob simultaneously
at runtime. These paths and pin assignments still require physical proof.

Before any programming, use the documented two-10kΩ USB boot adapter to identify
the ROM device `4348:55E0`, read identity only, then unplug and reconnect normally
and verify all six stock controls twice. Do not target stock `1189:8890` with this
controller. Reconcile silicon and outer-key GPIO, establish compatible recovery,
then program and test red startup, held/rotating controls, lease expiry, profile
colors, disconnect/reconnect, power cycle, sleep/resume and repeated recovery.
The boot adapter is removed for normal use. Unpowered LEDs cannot stay lit.

## Adapter arrival checklist

The [qualification guide](qualification/README.md) contains the passive USB-C wiring
diagram, recovery-first steps, six-control checks and red/green focus tests. Its
three temporary JSON profiles are for later managed-hardware qualification; they
do not enable shaker actions. Controller activation and both HEX uploads remain
deferred until ROM identity, GPIO mapping and repeatable recovery are established.
