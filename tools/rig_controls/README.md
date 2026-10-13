# External controls: profiles owned by Game Point

Prepared for workstation-ops #3863. Hardware has not been flashed. The controller
only opens the new managed firmware's unique vendor HID collection, validates its
capability, then writes a profile lease. Stock `1189:8890`, ROM `4348:55E0` and the
separate baseline firmware cannot receive profile output from this controller.

## What is ready

All six physical controls have stable logical names. Firmware starts red before
USB setup. The default/racing profile is red; foreground Minecraft can be green
with independent bindings. Without a valid host lease, the managed firmware returns
to red and stops emitting actionable inputs. Red therefore does not depend on AC or
SimHub running. The physical LEDs still need observation on the actual board.

| Control | Managed input | Example racing action | Current activation |
|---|---|---|---|
| Key 1 | `button_1`, down/up | `shakers.power.toggle` | Unavailable: socket identity pending |
| Key 2 | `button_2`, down/up | Operator will choose | No operation |
| Key 3 | `button_3`, down/up | Operator will choose | No operation |
| Clockwise | `knob_cw`, one impulse | `shakers.level.increase` | Unavailable: supported shaker-only control pending |
| Counterclockwise | `knob_ccw`, one impulse | `shakers.level.decrease` | Same dependency |
| Knob press | `knob_press`, down/up | Operator will choose | No operation |

`rig` names are reserved targets with visible "not activated" messages when pressed;
they do not toggle any socket or adjust any audio endpoint. These expected unavailable
messages remain visible without failing transport health; real action errors still fail health. Keyboard mappings are
implemented. All controls are retained in the managed protocol, but their functions
require a running controller and chosen bindings. The separate red baseline retains
Ctrl+Alt+A/M/S and computer volume up/down/mute for preservation testing.

## Agent-editable mapping

Copy `profiles.example.json` to a user-owned `keypad-profiles.json`. Agents can edit
this JSON without rebuilding firmware. Every profile must include all six inputs;
unassigned inputs explicitly use `{"action":"noop"}`. For a Minecraft debug-screen
key, for example, set its `button_1` to:

```json
{"action":"key","keys":["F3"]}
```

A chord such as `["CTRL","ALT","A"]` holds modifiers while the button is held;
release, profile switch, input loss or disconnect releases the injected keys. Knob
mappings send one down/up chord per detent. Only bounded, recognized key names and
reserved rig actions are accepted; JSON cannot execute shell commands.

Conditions in `when`:

- `foreground_process`: any exact executable basename in the list owns focus.
- `title_contains`: case-insensitive foreground-window title substring.
- `running_process`: any listed executable is running, including in the background.

Conditions supplied together must all match. Non-default profiles need a condition.
Highest priority wins; ties use file order. `manual_override` names a profile or is
`null` for automatic selection. The default is unconditional. Minecraft Java uses
both foreground `javaw.exe`/`java.exe` and a Minecraft title so another Java app or a
background game does not change the profile. Bedrock uses `Minecraft.Windows.exe`.
The example leaves Minecraft bindings unassigned for the operator to choose.

```powershell
python -m tools.rig_controls --config keypad-profiles.json --validate
python -m tools.rig_controls --config keypad-profiles.json --simulate tools/rig_controls/scenario.example.json
python -m tools.rig_controls --context
python -m tools.rig_controls --inspect
```

Validation and simulation work without hardware or HIDAPI. Simulation uses explicit
transport/context/action doubles; it does not prove an LED colour or send key input.
`--context` reads Windows foreground state. `--inspect` enumerates HID and reads the
custom capability if present; it sends **zero output reports**. HIDAPI is needed only
for inspection and a real managed controller: install `.[controls]`.

The worker rereads the file every 500ms. Foreground state stays fresh on each tick;
optional running-process queries are cached for 500ms. Inspection acquires the same
ownership mutex before opening a managed device and refuses contention. Invalid/partial edits leave the last valid
configuration active and show a reload error. Write a validated temporary JSON file,
then atomically replace the destination. A valid selected-profile edit releases old
keys and renegotiates before routing new inputs.

## Game Point activation after physical qualification

Game Point is the usual owner. In its existing user settings set `keypad_profiles`
to the absolute JSON path (or relative to the existing launcher root). Alternatively
set `AC_COPILOT_KEYPAD_PROFILES` before starting Game Point. Empty/unset is disabled
and never enumerates HID. The Keypad status row reports disabled, unavailable,
negotiating, active or stopping, profile name and action/reload errors. Normal
negotiation stays healthy while errors and configured missing hardware remain visible.
If shutdown takes longer than two seconds, status reports pending shutdown and the
worker retains exclusive ownership until it exits.
A machine-wide Windows mutex
prevents competing Game Point/diagnostic workers across sessions from opening
competing handles.

Source launchers need `.[controls]`; Windows EXE builders should install
`.[launcher,controls]`. The PyInstaller build includes controller modules/data and
collects `hid` if installed. A frozen Windows build still requires packaging proof.
`--run` is a diagnostic alternative to Game Point, with the same ownership mutex;
stop it before starting another owner. Controller activation is intentionally not
written into the installed PC settings during software preparation.

## Lease and recovery

The [firmware guide](../../firmware/keypad/README.md) and
[implementation plan](../../docs/10_Development/15_Keypad_Profile_Plan.md) define the
nine-byte USB contract. A matching colour ACK is required before the new profile's
inputs execute. A 3-second firmware lease is renewed every second, with a 500ms ACK
deadline. After a missed renewal the host discards queued inputs and reconnects
before routing anything. An orderly shutdown releases injected keys; force-killing
the process or an OS crash cannot guarantee Windows key-up delivery. Input sequences start at zero, wrap at 255 and expose queue loss; a
transport gap
releases held actions and negotiates a fresh epoch. Firmware queue overflow ends
the lease immediately, avoiding modulo-256 loss hiding a missing key-up. Lease expiry is steady red with
inert inputs. No master-volume fallback is introduced in the managed build.

Both HEX files are **DO-NOT-FLASH**. When the boot adapter arrives, first confirm ROM
identity, stock recovery and outer-button GPIO order. Then verify every physical
control, red startup/idle/held keys, Minecraft green and return to red, lease expiry,
power cycles, sleep/resume, reconnect and recovery. Smart-socket and shaker gain
activation additionally need exact target identification and observed target-only
results. See the canonical [external racing controls](../../docs/01_Vault/AcCopilotTrainer/10_Rig/external-racing-controls.md).
