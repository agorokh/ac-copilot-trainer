---
type: decision
status: active
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
issue: https://github.com/Atelier-AppliedAI/workstation-ops/issues/3863
relates_to:
  - AcCopilotTrainer/10_Rig/_index.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/10_Rig/audio-5.1-positional-engine-2026-07-12.md
  - AcCopilotTrainer/10_Rig/single-bs-1-recovery-phase1r-v1.md
---

# External racing devices, buttons and knobs

The operator's 2026-10-11 PDT direction establishes external controls as part of the
Assetto Corsa / SimHub rig: the current keypad is the first device, with further
button boxes and knobs expected. This node records the function plan and the prepared controller. The operator
commissioned firmware and conditional PC profiles on 2026-10-12, with physical
verification deferred until the adapter arrives. Shaker bindings remain **inactive**;
existing stock controls remain the physical baseline.
The keypad lighting/recovery owner is [workstation-ops #3863](https://github.com/Atelier-AppliedAI/workstation-ops/issues/3863).
Former AC #798 is superseded. Keypad software preparation is commissioned;
the #627 freeze and screen-firmware ownership remain unchanged.

## First device: three keys and one encoder

Black stacked-acrylic USB keypad, seller item `3256807158746757`, current USB
`1189:8890`, blank product/serial strings. Number keys using the operator's established
1/2/3 labels. Physical labels, GPIO numbers, HID messages and rig functions are four
different mappings; a USB ID alone does not prove a PCB revision or pin ordering.

| Physical control | Preserved current behavior | Intended racing function | Delivery state |
|---|---|---|---|
| Button 1 | Ctrl+Alt+A → Content Manager | Switch shaker amplifier's smart socket on/off | Planned; exact HA entity not identified |
| Button 2 | Ctrl+Alt+M → Minecraft | Operator will choose a car/rig function | Intentionally unassigned |
| Button 3 | Ctrl+Alt+S → Steam | Operator will choose a car/rig function | Intentionally unassigned |
| Encoder clockwise | Consumer Volume Increment | Increase **shaker output** level | Planned; target output identified, control integration unverified |
| Encoder counterclockwise | Consumer Volume Decrement | Decrease **shaker output** level | Planned; same target |
| Encoder press | Consumer Mute | Operator has not specified a future function | Preserve current mute during lighting work |

The 2026-10-12 operator capture saw Ctrl/Alt transitions and A/M/S releases; the
first press sequence was imperfect. Shortcut metadata matches the key assignments.
Separate knob-press/CW confirmation recorded `02-E2-00` (mute), then `02-E9-00`
(increment); earlier rotation recorded `02-EA-00` (decrement). This qualifies the
current baseline; it is not a full byte-level USB keyboard trace.

## Shaker target and ownership

A fresh read-only SSH query of AG_PC on 2026-10-12 found the playback endpoint
**`Rig Shakers - Seat and Pedals (3- USB PnP Sound Device)`**, status OK, endpoint
`{0.0.0.00000000}.{3BBEE5DD-43BB-4FBD-8A86-27F0577D463C}`. PCM2902 hardware
`08BB:2902` is present. The separate `Rig Speakers - Front and Rear` endpoint must
keep its own level. Hardware ID and friendly name are corroboration; bind to the
chosen render endpoint, because multiple PCM2902 devices currently exist.

The existing SimHub ShakeIt output uses that exact endpoint ID and is enabled,
with `ControlVolume=true`, `GlobalGain=75`, `GainChangeStep=1`, `IsMuted=false`.
These are observations, not requested new settings. Prefer supported SimHub
controls; direct endpoint adjustment needs testing because SimHub controls its volume.
[SimHub's gain documentation](https://github.com/SHWotever/SimHub/wiki/ShakeIt-V3-Effects-configuration#general-gain)
distinguishes overall, effect and channel gains. Future implementation must verify
whether supported SimHub controls or the selected endpoint's volume provide the
required shaker-only adjustment and persist without SimHub overwriting it. Retain
the current effect mix, channel routing and thermal protections.

The operator reports the shaker smart socket already works and may be in Homestead.
An authenticated HA state-name search for shaker/SimHub/racing on 2026-10-12 found
no matching rows; that does **not** show the socket is absent. Its entity ID,
integration and physical load need reconciliation before binding Button 1.
The documented Yamaha `switch.smart_plug_socket_1` belongs to another amplifier;
do not adopt it as the shaker socket without evidence. Homestead owns the socket
identity/control, AC Copilot Trainer owns the racing action mapping, and workstation-ops
owns this keypad's lighting and recovery.

## Mapping model for this and later devices

Use physical input → stable logical action → explicit target → observed result.
Examples: `shakers.power.toggle`, `shakers.level.increase`, `shakers.level.decrease`.
These names describe the plan, not an existing API. Keep per-device bindings separate
from action execution so later buttons/encoders can invoke the same rig functions.
Prefer existing SimHub controls and Game Point status/settings paths over another
standalone launcher or dashboard. Dedicated HID inputs may be chosen later; changing
the current consumer-volume outputs alone cannot select a sound card.

One physical press must produce one power transition; filter repeat/bounce, read
the socket state, request the explicit opposite state, then observe it. Never retry
a blind toggle. A missing/offline/ambiguous target must report unavailable and leave
other plugs and the default audio endpoint untouched. Encoder steps require bounded
increments and a visible actual level; reconnection must not invent a new target.

## Default red and conditional game styling

All three LEDs should remain `#FF0000` in the baseline and default/racing profile:
initialization, idle, held/released keys, rotation, host restart and USB reconnection.
The operator subsequently requested explicit profile styling: Minecraft green
(`#00FF00`) while its profile is selected, with independent action bindings. They are a
styling element matching the fence and other lighting, not socket-status indicators.
No rainbow, breathing, white press effect or volume/power color changes. Firmware
must apply red before USB/host setup; no SimHub/AC session is required for the color.
Unpowered LEDs cannot light; ROM recovery has its own behavior and needs measurement.

## Prepared software and agent control

Source is now owned here: [firmware/keypad](../../../../firmware/keypad/README.md)
and [tools/rig_controls](../../../../tools/rig_controls/README.md). The PC controller
is an opt-in Game Point worker with a Keypad status row. Agents edit a strict JSON
file containing all six mappings, RGB colour, foreground/title/running conditions,
priority and optional manual override. Valid edits reload automatically; invalid
edits preserve the last valid configuration and report an error. Keyboard actions
are implemented as held chords for buttons and impulses for the encoder. Rig names
remain visibly unavailable until their target integration is verified.

Two build variants are prepared. **Baseline** preserves Ctrl+Alt+A/M/S and consumer
volume up/down/mute with steady red. **Managed** emits all six logical controls and
accepts a leased colour; actions require the PC controller. Without that controller
it remains red with inert inputs. This prevents global volume or stale application
bindings from becoming an accidental fallback. The current physical keypad retains
its stock firmware until hardware qualification.

The custom collection is `1209:C55D`, usage `FF31:1`, with an `AC` version-1 feature
identity. The controller excludes stock `1189:8890` and ROM `4348:55E0`, verifies a
unique candidate and capability before writing, and requires the new colour's ACK
before routing its inputs. Held actions are released on profile change, gaps,
timeout or disconnect. A machine-wide ownership mutex prevents competing workers.
The prepared local USB identifiers are not a claim of a globally allocated product.

The real CH55xDuino 0.0.26/SDCC build succeeds for both variants within CH552's
application boundary. Native tests exercise actual protocol, HID, endpoint and LED
code under test stubs; host tests exercise selection, reload and routing without
hardware. These are **software proofs**, not GPIO, electrical or LED observations.
Both HEX artifacts remain **DO-NOT-FLASH** pending ROM identity, outer-key P11/P16
ordering and repeatable recovery. Source provenance and CC-BY-SA licence remain in
the firmware subtree. The wiring adapter is removed during normal operation.

## Staged acceptance

Software preparation is commissioned and implemented; physical acceptance is
explicitly deferred. First prove ROM identity and recovery returning to all six
stock controls twice; reconcile GPIO order before programming. Then test steady red,
all six baseline functions, managed ACK/input routing, green Minecraft and red
return, disconnect/lease fallback, power cycles, sleep/resume and recovery.
Identify the shaker socket and verify supported shaker-only level control without
changing speaker/headset audio before enabling those actions. Buttons 2/3 and the
future encoder press stay unassigned until chosen. Register later external devices
here with identity, physical labels, logical actions, target ownership and observed
recovery evidence. AC session and screen-firmware freezes remain unchanged.
