---
type: handoff
status: active
created: 2026-11-16
updated: 2026-11-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/1006
relates_to:
  - AcCopilotTrainer/03_Investigations/simhub-shakeit-runtime-gain-2026-11-16.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-15-171923Z-game-point-settings-change-a51188.md
---

# #1006 keypad racing: decision gate settled, code blocked on the memory host

**Resume pointer.** Branch `feat/issue-1006-keypad-racing`. On the operator's instruction
"unblock it please and do autonomously as much as you can", `status:blocked-on-rig` was removed
from #1006. Part 1's decision gate is settled (see the investigation node) and the default
choices for the open operator decisions are recorded in
[the #1006 comment](https://github.com/agorokh/ac-copilot-trainer/issues/1006#issuecomment-6914583317).

## Block

Every code-path edit is refused by `hook_memory_gate.py`: the Tier-3 host `m4max-studio` was
offline on the tailnet (Tailscale: last seen about 2 h before 11:00Z on 2026-11-16), so the
SessionStart prefetch could not stamp the gate. The gate has no agent bypass; recovery is the
host coming back, or the operator's audited `EMERGENCY_BYPASS_GOVERNANCE=1`.

## Rig state read this session

- The pad is plugged into `AG_PC` as `1209:C55D` with only COL01-03 (keyboard, mouse, consumer
  control): the baseline image, not managed. Part 0's reflash and button checks still need hands.
- Live `controls.ini` (OneDrive Documents): keyboard keys exist for `ACTION_HEADLIGHTS` (L),
  `ACTION_HORN` (H), `__EXT_HAZARDS` (Alt+Down), turn signals and camera. `__EXT_PIT_LIMITER` and
  `STARTER` / `__EXT_STARTER` are wheel buttons only.
- The main checkout's `.venv` has no `hid`, so `--inspect` cannot run there.

## Planned implementation (not written yet)

1. `tools/rig_controls/ac_controls.py`: read-only `controls.ini` resolver; new `car` binding
   that names an AC section; conflict check that treats vanilla Ctrl shortcuts (`HIDE_APPS`,
   `IDEAL_LINE`, `DRIVER_NAMES`, `AUTO_SHIFTER`, `ABS`, `TRACTION_CONTROL`, `ACTIVATE_AI`,
   `MOUSE_STEERING`) as Ctrl+letter.
2. Shaker client in `rig_controls`: loopback TCP, token from a rendezvous file the plugin writes
   in the Game Point folder; requests run on a background thread so the keypad lease never
   stalls; ceiling enforced by the plugin under a lock; no fallback to any Windows volume.
3. Second plugin class in `tools/simhub_car_enrichment` calling `TriggerAction` /
   `GetPropertyValue` (names in the investigation node).
4. `racing.json`: `racing` (acs.exe foreground), `racing-background` (acs.exe running, knob only),
   inert `desktop` default; all red.
5. Game Point: `"keypad_profiles": "racing"` seeds an editable copy; `shaker_gain_max` (75);
   status row with level, mute, last action and warnings; `hidapi` in the `launcher` extra and
   `hid` in `FROZEN_REQUIRED_MODULES`; docs and tests.

## Not done

Everything after the decision gate: code, PR, review, EXE rebuild, plugin install, and the
"Done means" checks on the rig.
