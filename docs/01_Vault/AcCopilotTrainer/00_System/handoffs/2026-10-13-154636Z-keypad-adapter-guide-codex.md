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
  - AcCopilotTrainer/00_System/handoffs/2026-10-13-125748Z-post-merge-pr826-keypad-db789d.md
---

# Adapter arrival: wiring guide and temporary test profiles

Operator: "Save the wiring guide and test profiles in AC Copilot Trainer so agents
can pick this up when the adapter arrives. Keep the controller inactive and both
firmware variants staged."

The [canonical arrival guide](../../../../../firmware/keypad/qualification/README.md)
and three adjacent test JSON files preserve the passive two-resistor USB-C circuit,
stock recovery checks, all six controls, manual red/green Notepad mappings, automatic
Minecraft focus conditions and interruption/recovery acceptance. Firmware/controller
READMEs and the rig plan link to the same folder; no second configuration owner.

The PC copy is `adapter-guide/` within the existing prepared recovery root
`C:/Users/arsen/AppData/Local/WorkstationOps/Recovery/keypad-profiles-prepared-20261012`.
The prior staged HEX/ZIP/EXE and inactive working JSON remain the source package
recorded by the linked software SAVE. No upload, erase, driver installation,
controller activation, socket action or audio mutation is part of this SAVE.

Profiles are software-validated through the actual production parser/controller:
manual red and green route all six A-F inputs; automatic Java requires foreground
process AND Minecraft title, Bedrock requires foreground, background Minecraft
stays red. Automatic colour-test actions are all no-ops. This is not physical colour/GPIO proof.

Resume under OPEN workstation-ops #3863 when the board arrives. Inspect delivered
pin labels; assemble unpowered with Uno disconnected. Read ROM identity only,
remove adapter and verify all six stock controls twice. Reconcile outer-button
P11/P16 order and other GPIO evidence before choosing any firmware. Flash replaces
the factory program; baseline is not a factory backup. Later qualify each installed
variant, six controls, steady red, green/red focus, lease expiry, power/sleep,
reconnect and repeated recovery. Park the controller inactive afterwards. Shaker
socket/gain targets and unchosen racing actions remain unavailable.
