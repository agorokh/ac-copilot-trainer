# Keypad adapter: wiring and arrival checklist

Prepared 2026-10-13. Instructions for future physical qualification; no flash or controller activation has occurred. Firmware and controller are merged and staged. Workstation-ops [#3863](https://github.com/Atelier-AppliedAI/workstation-ops/issues/3863) owns the physical acceptance; this folder is its agent resume procedure. The actual board/GPIO and LED colours remain unverified.

## 1. Build the passive adapter

Use the USB-C **male-to-female breakout with pins**, two **10 kΩ** resistors, four female-to-male jumpers, and the kit breadboard. The **Arduino Uno stays disconnected**; no sketch is needed.

```text
PC ── existing USB data cable ── [FEMALE | breakout | MALE] ── keypad
                                        │
                           pin taps on BOTH sides:

              Side A:  VCC/5V ─── [10 kΩ R1] ─── D+
              Side B:  VCC/5V ─── [10 kΩ R2] ─── D+

              D− and GND: no added jumper connections
              Arduino Uno: no connections
```

This shows **signal names, not physical pin positions**. Confirm the delivered board's labels match. If labels are unclear, stop assembly until its pinout is identified.

With USB unplugged:

1. Connect side-A VCC and D+ through R1 on the breadboard.
2. Repeat side-B VCC and D+ through R2.
3. Each resistor must bridge **different breadboard nodes**. For a standard centre-gap board: R1 from a10 to f10, jumpers b10 and g10; R2 from a14 to f14, jumpers b14 and g14. Verify those groups are separate on your breadboard.
4. Check for accidental bare-wire shorts. Never join VCC directly to D+ without its resistor.

Resistors work either way round. All four USB lines still pass through the breakout itself. Remove the entire adapter for ordinary use.

Circuit source: [the pinned KeypadFlasher DIY procedure](https://github.com/AmyJeanes/KeypadFlasher/blob/6de74402068c1e57febd65ce13cc6a111ed171ac/docs/bootloader.md#diy-adapter).

## 2. First visit: recovery and unchanged stock controls only

1. Connect the keypad **normally**, with no adapter. Number its buttons using your established 1/2/3 labels. Record the six current functions in the table below.
2. Unplug it. Insert the wired adapter between cable and keypad. Have the agent's USB identity check ready; connect USB power/data.
3. Look for recovery ID **4348:55E0** and read the chip/bootloader identity only. The ROM window is approximately ten seconds. Replug if necessary. Do not select any upload, erase, or flash operation.
4. On Windows, if the ROM needs a driver, use WinUSB for **4348:55E0 only**, following the upstream driver instructions. Do not replace the stock keypad's keyboard/HID driver. Driver installation does not establish GPIO compatibility.
5. Unplug, remove the adapter, and reconnect normally. The original device should return as **1189:8890**. Repeat every stock control.
6. Repeat the recovery → adapter removal → normal reconnect sequence **twice**, recording the identity and stock results each time.
7. Stop before flashing. The agent must match the measured identity to the source board profiles and reconcile the outer-button P11/P16 order, encoder direction and remaining GPIO evidence. Seeing the ROM proves recovery access; it does not prove the LED/key wiring.

| Physical action | Stock / red baseline expectation |
|---|---|
| Button 1, tap and release | Ctrl+Alt+A, currently Content Manager shortcut |
| Button 2, tap and release | Ctrl+Alt+M, currently Minecraft shortcut |
| Button 3, tap and release | Ctrl+Alt+S, currently Steam shortcut |
| Knob one detent clockwise | Computer volume up |
| Knob one detent counterclockwise | Computer volume down |
| Knob press and release | Computer mute toggle |

Pause two seconds between actions. A HID capture should check the actual shortcut/media reports; launching an application alone is weaker evidence. For volume/mute tests, note the starting value, use one step each way, and unmute afterwards.

**Flashing replaces the factory program.** The prepared red baseline is a replacement preservation build, not a verified factory backup. Unplugging after a flash will not restore the original program.

## 3. After compatibility is resolved: qualify the two firmware variants

Both files are still staged under `DO-NOT-FLASH/` in the PC recovery ZIP. Only one image can run on the keypad at a time. The agent selects the matching reviewed image after the checks above; this guide is not an instruction to upload the current candidates blindly.

**Red baseline, `baseline.hex`:** controller remains off. Repeat the six stock functions twice. Observe all three LEDs: startup, idle, held buttons, knob turns, reconnect and power cycle should remain red. Prove both documented recovery paths—knob held while plugging in and all three buttons plus knob pressed together—then disconnect/reconnect. These software entry paths still depend on correct physical pins. Keep the passive adapter as the independent recovery route.

**Managed, `managed.hex`:** before any host controller starts, expect red with inert controls. With a temporary test controller active, use the safe letter mappings below. No shaker power or level action is enabled by these test files.

| Physical action | Managed logical input | Notepad test letter |
|---|---|---|
| Button 1 | `button_1` | A |
| Button 2 | `button_2` | B |
| Button 3 | `button_3` | C |
| Clockwise detent | `knob_cw` | D |
| Counterclockwise detent | `knob_ccw` | E |
| Knob press | `knob_press` | F |

Windows may type lowercase depending on Caps Lock. Use a blank Notepad document, single taps and single detents, two seconds apart. Expect `abcdef` in that order; repeat twice under red and twice under green. Test button/knob releases and verify no key remains held after switching profiles or unplugging.

## 4. Red/green tests in the logged-in PC desktop

Included files (validate or simulate freely; `--run` is only for the later managed-hardware qualification):

- [test-red.json](test-red.json): forces red; all six controls type A–F.
- [test-green.json](test-green.json): forces green; same six letter mappings.
- [test-auto.json](test-auto.json): automatic red/default, green when Java Minecraft has both foreground process and Minecraft title, or when Bedrock has focus. All bindings are deliberately no-ops for this colour-only focus test.

These are **temporary diagnostic mappings**, separate from your future racing mappings. With managed firmware qualified, use the already prepared PC virtual environment. The prepared PC copy is under that root as `adapter-guide`. To refresh it later, copy this repository's `firmware/keypad/qualification/` folder there as `adapter-guide`; copying files does not activate the controller. Run from a normal **logged-in desktop PowerShell**, not SSH: foreground conditions and injected keys belong to that desktop. Keep Game Point's `keypad_profiles` empty during standalone tests, and run only one controller at a time.

```powershell
$Root = Join-Path $env:LOCALAPPDATA 'WorkstationOps\Recovery\keypad-profiles-prepared-20261012'
Set-Location $Root
$Python = Join-Path $Root '.venv\Scripts\python.exe'

# Read-only inspection; should find one managed vendor collection.
& $Python -m tools.rig_controls --inspect

# Validation only: no hardware output.
& $Python -m tools.rig_controls --config .\adapter-guide\test-red.json --validate

# Start only after hardware qualification, using managed firmware.
& $Python -m tools.rig_controls --config .\adapter-guide\test-red.json --run
```

Wait for `active` in the console. Focus blank Notepad and test A–F. Return to the PowerShell window and press **Ctrl+C** to stop. Repeat the `--run` command with `test-green.json`, then stop. Run with `test-auto.json` for the focus test:

1. Desktop / Assetto Corsa / SimHub foreground: red default.
2. Bring actual Minecraft gameplay to the foreground: all three LEDs green.
3. Switch away to Notepad or AC: red again, even with Minecraft running in the background.
4. Repeat the switch several times. Java needs the actual Minecraft window title; a launcher or unrelated Java window is insufficient.
5. Stop the controller. Managed firmware should return to red and inert inputs after its lease expires (up to about three seconds).

Stopping the controller does not preserve the baseline computer-volume actions on managed firmware. To use those actions without a controller, the separately qualified baseline must be the installed image.

## 5. Final acceptance and park it safely

Check red after unplug/replug and a power cycle. Check sleep/wake and USB reconnect; record any flash of another colour, stuck key, skipped/duplicate detent or missing LED. Sleep may remove USB power, and unpowered LEDs cannot light; ROM recovery is outside application LED control and needs observation.

Repeat recovery after each flashed variant and verify reconnect returns to that installed variant. Verify three buttons, both rotation directions and knob press again afterwards. Log measured ROM identity, button order, direction, firmware variant, six results and colour observations under workstation-ops #3863.

At the end, stop standalone workers and leave Game Point `keypad_profiles` empty. Keep both reviewed HEX variants staged. Socket power and shaker-only gain remain unavailable until their exact targets/integration are verified. Later agents can edit validated JSON functions and conditions without rebuilding the firmware.

Project sources: [firmware README](../README.md), [controller README](../../../tools/rig_controls/README.md), and [external racing controls](../../../docs/01_Vault/AcCopilotTrainer/10_Rig/external-racing-controls.md).
