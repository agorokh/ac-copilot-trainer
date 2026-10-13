# Keypad firmware and PC profiles implementation plan

Refs Atelier-AppliedAI/workstation-ops#3863. Operator approved implementation on
2026-10-12; defer flashing and hardware acceptance until the adapter arrives.

**Goal:** prepare buildable CH55x firmware, a Windows profile controller, editable
conditions/mappings and the canonical external-controls documentation.

**Architecture:** extend the pinned KeypadFlasher candidate with a vendor HID
collection. Keep the six physical inputs independent from host actions. Game Point
owns an opt-in controller worker and status; agents edit validated JSON profiles.

**Tech stack:** CH55xDuino 0.0.26/SDCC C, Python 3.11+, HIDAPI, Windows foreground
queries/SendInput, JSON. No device flash, driver change, AC launch or plug toggle.

## USB contract (v1)

Every report is 9 bytes including report ID. Vendor collection usage page `FF31`,
usage `1`, VID/PID `1209:C55D`; verify capability before any output. Stock
`1189:8890` and ROM `4348:55E0` are never controller targets.

| ID | Direction | Eight payload bytes |
|---|---|---|
| 4 | input event | version=1, epoch, sequence, control, pressed, 0, 0, 0 |
| 5 | output profile lease | version=1, epoch, R, G, B, lease in 100ms (1..50), 0, 0 |
| 6 | input acknowledgment | version=1, epoch, R, G, B, managed=1, 0, 0 |
| 7 | GET_FEATURE capability | ASCII A, ASCII C, version=1, epoch, R, G, B, managed |

Controls: 1 button_1, 2 button_2, 3 button_3, 4 knob_cw, 5 knob_ccw, 6 knob_press.
Buttons/press emit down/up; rotary detents emit pressed=1 impulses. Epoch changes
flush queued events. Sequence increments modulo256; host duplicate reports do not
repeat actions. Sequence gaps invalidate held keys and require a new epoch.
ACK precedes new-epoch events. MCU lease expiry sets red and ends managed input;
host must renegotiate, and no Windows master-volume action is invented.

Managed build emits vendor events only; separate baseline build preserves existing
Ctrl+Alt+A/M/S and consumer volume-up/down/mute reports. Both start steady red.
Keep the existing, physically unverified boot-button/chord recovery, compile both artifacts as DO-NOT-FLASH.
GPIO remains provisional until physical identity reconciles the outer buttons.

## Tasks and verification

- [x] Recover earlier candidate from the durable PC archive and verify its SHA256;
  retain upstream licence/provenance when placing source under `firmware/keypad/`.
- [x] Write failing native C tests for report validation, all-six input events,
  epoch/ACK order, queue pressure, red boot/lease timeout and baseline preservation.
  Implement firmware, then run tests and compile with the actual CH55x toolchain.
- [x] Write failing Python tests in `tests/test_rig_controls.py` for strict JSON,
  foreground/running/manual conditions, protocol identity, ACK-before-routing,
  duplicate/gap handling, held-key release, disconnect and invalid reload.
- [x] Implement `tools/rig_controls/{profiles,protocol,controller,windows}.py` and
  the CLI. Example JSON covers red default/racing and green Minecraft; unchosen
  functions use noop. Key chords are data, never shell commands or eval.
- [x] Test and implement opt-in Game Point settings/status/worker ownership. Keep
  installed launcher unchanged while staging. Runtime controller must not open a
  HID handle unless an exact unique candidate and capability are established.
- [x] Exercise the real CLI with a deterministic simulated transport/context,
  including a reload and bad config; run Windows validate/context/stock-exclusion
  checks over SSH without keyboard injection or output to the stock device.
- [x] Update `10_Rig/external-racing-controls.md`, a focused runtime guide, and a
  dated vault SAVE. Record prepared versus physically verified acceptance.
- [ ] Run `make ci-fast`, create the scoped draft PR, resolve exact-head review/CI,
  merge when permitted and stage a source/firmware recovery bundle on the PC.

Shaker entity and SimHub volume ownership remain explicit activation dependencies.
This delivery prepares profile routing; it must not guess the smart socket or
silently bind the knob to Windows master volume. Existing AC/screen freezes hold.
