---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-13
updated: 2026-10-13
issue: https://github.com/Atelier-AppliedAI/workstation-ops/issues/3863
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/10_Rig/external-racing-controls.md
---

# Keypad software merged and staged; hardware acceptance deferred

Controller [PR #825](https://github.com/agorokh/ac-copilot-trainer/pull/825) merged
`07c29d75271dda96014230d74b6a234b3a647e03` from reviewed head `899607ce`.
Firmware/profile [PR #826](https://github.com/agorokh/ac-copilot-trainer/pull/826) merged
`8af6a009d6923eb04f648fd99fa8ed7e0742aea3` from reviewed head `56b7db26`.
Both have an eligible independent Grok exact-head review; CI passed. The single
firmware finding was falsified with current source links and an actual unflagged
build, with disposition published before merge. Upstream imports #822/#823/#824
and the historical preparation SAVE #821 are merged. Former #820 is superseded.
There was no flash or activation. Workstation-ops #3863 remains OPEN.

The canonical [external racing controls](../../10_Rig/external-racing-controls.md)
records the six logical controls, intended shaker-only mappings, target ownership
and activation prerequisites. Agents edit validated JSON conditions and bindings;
firmware does not need rebuilding for a game profile. Racing/default is steady red,
foreground Minecraft is green, and a lost host lease returns to red/inert.
A separate red baseline retains Ctrl+Alt+A/M/S and volume up/down/mute.

## Software proof and staged package

Full `make ci-fast` passed: 4,322 tests, 75 skipped, 87% coverage, plus lint,
security and policy checks. Ten native firmware tests execute the actual protocol,
HID, USB endpoints, button debounce and LED behavior under hardware stubs.
Both CH55xDuino 0.0.26/SDCC builds passed with application bounds below 0x3800.
Compiled source remains identical to revision 9c673bbf for the sketch and builder.

The isolated PC build passed all 43 controller tests. The frozen executable includes
all nine controller modules and HIDAPI, with all five reviewed runtime fixes
verified in its bytecode. Native Windows global-mutex contention/release passed.
Simulation exercised all six logical controls and red/green/red conditions;
stock-only inspection found zero managed candidates and sent zero output reports.
Package and executable match source `56b7db26` and remain inactive.

ZIP SHA256: `e1ded1fb61883bff682d9db1a365e66981ed2f733adc51a4064cb0590854a28d` <!-- pragma: allowlist secret -->
EXE SHA256: `06ce296da595882a4b144b82523931c8fb36c4783f339fd0487b303b99f2abec` <!-- pragma: allowlist secret -->

Supplemental review evidence: an actual unflagged managed build is byte-identical
to the explicit managed build. The claimed missing USB includes were already present
on the reviewed head; the source-linked disposition is on PR #826. A scratch native
reproduction and two missing-include negative controls are retained with receipts.
The compiled production source was unchanged. No extra test patch was shipped.

Prepared PC root: `C:/Users/arsen/AppData/Local/WorkstationOps/Recovery/`.
Package: `keypad-prepared.zip`; expanded source/build: `keypad-profiles-prepared-20261012`.
Executable: `dist/AC-Copilot-Game-Point.exe` within that expanded directory.
Working JSON: `C:/Users/arsen/AppData/Local/AC Copilot Trainer/GamePoint/keypad-profiles.json`.
It validates and remains inactive. Installed launcher settings are unchanged.
Stable receipts: `/Users/arseny_gorokh/.codex/artifacts/keypad-profiles-20261013/`.

## Remaining owner and resume

Workstation-ops #3863 stays OPEN. When the ordered passive USB board arrives,
confirm ROM identity, return to all six stock controls twice, reconcile outer-key
GPIO order and repeatable recovery before selecting/flashing any candidate.
Then physically observe every control, red startup/idle/held controls, green
Minecraft/red return, lease expiry, power cycles, sleep/resume, reconnect and
recovery. Software simulations do not establish these hardware outcomes.

Key 1 is reserved for the existing shaker smart socket, but its exact Homestead
entity remains unidentified. The knob is reserved for supported shaker-only gain;
no master-volume fallback exists. Those rig actions visibly report unavailable.
Buttons 2/3, knob press and Minecraft mappings remain unassigned for the operator.
Do not adopt the Yamaha amp plug or change speaker/headset routing. AC-session
and screen-firmware ownership/freeze boundaries remain unchanged.
