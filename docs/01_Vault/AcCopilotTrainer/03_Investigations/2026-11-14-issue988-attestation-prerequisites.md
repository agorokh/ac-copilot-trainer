---
type: investigation
status: active
created: 2026-11-14
updated: 2026-11-14
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14-evidence.md
  - AcCopilotTrainer/03_Investigations/2026-10-13-135149Z-moza-observed-ai-capture-815-d84bb7.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Issue 988: what the rig says about the three non-human control signals

Read-only observations on the rig, 2026-11-14 UTC, made while building the default-off
human-control attestation producer (PR #997). They settle the card's two unverified
prerequisites and add one blocker the card did not know about. No sim was started and no
archive, ledger or vendor file was written.

## Native game AI: a state field exists, its live meaning is unobserved

`extension/internal/lua-sdk/ac_apps/lib.lua:5057-5058` on the rig install declares, on
`ac.StateCar`:

- `isAIControlled` — "True if car is controlled by AI (or that autopilot thing)."
- `isUserControlled` — "True if car is controlled by user (controls could be disabled completely)."

The same two lines appear in the definitions for 18 other script types. The earlier negative
code search of the public SDK repository (evidence row E-006) was a search limitation, not an
absence. AC's stock `sim_info.py` shared-memory layout on the rig has no such field, so the
signal is reachable only from CSP Lua. The trainer now counts both fields every frame into
`trace.control_observation`.

Not observed: what the fields read while AC's own AI drives the player car, and what they read
under the project's Custom-AI hijack. Treat the field as existing, not as proven.

The same definitions file declares, on `ac.StateSim`, `isLive` ("simulation is currently running
(not paused and not in replay mode)", line 5350), `isPaused` (5346) and `isReplayActive` (5352).
The trainer counts non-live frames with `isLive`. Its live behaviour is equally unobserved.

## Vendor practice record: one rolling file, not written for every session

`%LOCALAPPDATA%\MOZA Racing Lab\training-evaluation\training-evaluation-snapshot-v1.json` is
the only file under that folder that carries `aiIntervened`. It holds a single session.

- Last written 2026-10-15T01:52:26Z (session started 01:47:46Z, saved 01:52:25Z, one lap,
  `aiIntervened=false`, `eligibility=eligible`).
- 59 native laps in 27 native sessions were archived after that write, and the file did not
  change. The record is therefore **not** written for every session.
- It has session start and save times but no per-lap timestamp. `referenceKey` is a pipe-joined
  string whose first three fields are game, track and car.

Consequences for any consumer: the file must be copied during capture because the next session
overwrites it, and a lap can be joined to it only by session window, combo and lap duration.
Whether it is always written when Racing Lab observes a session, and whether switching AI on
mid-lap sets the label, are unobserved. So is whether its `lapNumber` always equals the
trainer's lap number: they agreed in the one 2026-10-13 session, and `tools/moza_ingest`
already requires it, but a constant offset would make every lap abstain.

## Declaration surface: the keypad is not flashed

`tools/rig_controls` talks only to the managed keypad firmware. workstation-ops#3863 is open and
its firmware builds are marked do-not-flash, so no rig button can deliver a declaration today.
The card's default ("a spare rig button, because the touchscreen needs firmware") assumed the
button needed no hardware step. It does.

## Ledger and archive state used for the offline check

The live attribution ledger held 193 entries (160 `shared`, 33 `ai`), up from the 174 the card
cites; the ledger is append-only, so the first 174 are that set. 18 of those 174 archives are no
longer in the live folder (retention rotation) and no backup copy was found under the user's
project folders. The producer certified 0 of the 156 present, and 0 of all 175 present across
the whole ledger. That zero is by construction, since legacy laps carry no capture signals.

## Where the rule lives

[Contract and bench procedure](../../../10_Development/41_Human_Control_Attestation.md).
The bench session is operator-attended and has not run.
