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
button boxes and knobs expected. This node records the function plan. The racing
bindings below are **not deployed**; existing controls remain the lighting baseline.
The keypad lighting/recovery owner is [workstation-ops #3863](https://github.com/Atelier-AppliedAI/workstation-ops/issues/3863).
Former AC #798 is superseded. No simulator-runtime changes are commissioned here;
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

## Constant red is independent of functions

All three LEDs should remain `#FF0000` during powered normal use: initialization,
idle, held/released keys, rotation, host restart and USB reconnection. They are a
styling element matching the fence and other lighting, not socket-status indicators.
No rainbow, breathing, white press effect or volume/power color changes. Firmware
must apply red before USB/host setup; no SimHub/AC session is required for the color.
Unpowered LEDs cannot light; ROM recovery has its own behavior and needs measurement.

The offline candidate now sends red before USB initialization, removes its startup
off frame and replaces its blue recovery-entry indication with red. Tests cover
startup ordering and 228 red renderer frames, plus the preserved six HID functions;
the build is 12,387 bytes. **The actual keypad has not been flashed or proved red.**
Exact-board GPIO/ROM identity and repeatable recovery remain required before flashing.

## Staged acceptance

First prove recovery, physical steady red and power-cycle persistence while all six
baseline controls work. Then identify the shaker socket and verify shaker-only level
control without changing speaker/headset audio. Implement the operator's chosen
racing profile only when commissioned; Buttons 2/3 and future encoder press stay
unassigned until chosen. Register later external devices here with their identity,
physical labels, logical actions, target ownership and observed recovery evidence.
