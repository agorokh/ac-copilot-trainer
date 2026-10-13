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

# Keypad firmware and conditional Game Point profiles prepared

The operator commissioned software preparation without waiting for the adapter.
[PR #820](https://github.com/agorokh/ac-copilot-trainer/pull/820) carries source,
tests and documentation, authored by OpenAI/Codex at
`9c673bbfc1a75f0da544b0762efe10498cf12c94`. CI is green. Independent daemon review remains in flight; no exact-head review
has arrived and the feature is not merged at this SAVE. The review lease was
renewed at 06:45:17Z through 07:25:17Z; the bounded round ends at 07:01:46Z.

## Delivered software and PC staging

Both actual CH55xDuino/SDCC firmware builds succeed. Baseline preserves the six
stock functions with steady red; managed firmware emits the six logical controls
and accepts leased colours. Both are DO-NOT-FLASH pending hardware qualification.
Game Point owns the opt-in worker. Strict JSON controls all six bindings, colour,
foreground/title/running conditions, priority and manual override. The default is
red/racing; foreground Minecraft selects green. Invalid edits retain the last
valid configuration. Ownership, ACK, gaps and lease failures end input safely.

Full `make ci-fast`: 4,313 passed, 75 skipped, 87% coverage, with lint/security/
policy checks. Ten native firmware tests execute protocol/HID/endpoint/LED code
under stubs; 34 host tests also pass on AG_PC. Native Windows foreground reading
and cross-session ownership exclusion pass. Red/green/red simulation is software
proof; actual Minecraft focus switching and physical colours remain unverified.
Stock HID inspection found no managed candidate and sent zero output reports.

Prepared PC bundle: `C:/Users/arsen/AppData/Local/WorkstationOps/Recovery/keypad-prepared.zip`.
Expanded build is `Recovery/keypad-profiles-prepared-20261012` under that same root;
`dist/AC-Copilot-Game-Point.exe` is built and includes controller modules and HIDAPI.
The agent-editable working file is
`C:/Users/arsen/AppData/Local/AC Copilot Trainer/GamePoint/keypad-profiles.json`.
It validates and is not activated; installed Game Point settings remain unchanged.
Stable Mac receipts: `/Users/arseny_gorokh/.codex/artifacts/keypad-profiles-20261013/`.

## Remaining and resume

#3863 remains OPEN for physical acceptance: verify ROM identity and returning to
all six stock functions twice, resolve GPIO/button ordering, then flash only the
qualified candidate. Observe red startup/power cycles, every input, managed ACK,
Minecraft green/red return, disconnect and sleep/resume, plus recovery.
The smart-socket entity remains unidentified; supported SimHub/shaker-only volume
integration remains unverified. Named shaker actions report unavailable, never
master-volume fallback. Buttons 2/3, knob click and Minecraft actions remain unassigned.
Do not adopt the Yamaha plug or alter speaker/headset routing. AC session and
screen-firmware ownership/freeze boundaries remain unchanged.

Dependency follow-ups after merge: optional HIDAPI controls dependency and Windows build
scripts; isolated PC preparation installed launcher/controls dependencies. No
migration or required setting is introduced. Two Council challenges were partial
quorum and are not approval; unsupported discovery claims were checked against
primary tests. Independent PR review is the merge boundary recorded above. Resume PR #820 with
the complete paginated feedback ledger, current checks and the OpenAI vendor
exclusion; do not flash or activate the prepared configuration to test it.
