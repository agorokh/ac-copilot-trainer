---
type: handoff
status: active
created: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-202215Z-issue988-human-attestation-4876fb.md
  - AcCopilotTrainer/03_Investigations/2026-11-14-issue988-attestation-prerequisites.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# PR 997 merged: default-off human-control attestation is on main; #988 stays open

**Resume pointer.** PR [#997](https://github.com/agorokh/ac-copilot-trainer/pull/997) squash-merged
as `abf0864c` at 2026-11-14T21:01:25Z, bound to audited head `fb1b5886`. Issue
[#988](https://github.com/agorokh/ac-copilot-trainer/issues/988) is **open**: its acceptance
verdict needs the operator-attended bench session, which has not run (0 of 1 rig sessions used).
The earlier node for this issue said the PR was held in draft; this one supersedes that state.

## Delivered on main

- `tools/human_control_attestation.py` (producer, capture monitor, offline scorecard, bench
  verdict), the human-authority path in `tools/lap_qualification.py`, the buttons-only `attest`
  binding in `tools/rig_controls`, and the trainer's `trace.control_observation` block.
- Contract, limits and bench procedure:
  [41_Human_Control_Attestation.md](../../../../10_Development/41_Human_Control_Attestation.md).
- The opt-in is default off. On `main` nothing sets `AC_COPILOT_HUMAN_CONTROL_ATTESTATION`; only
  the exact value `1` enables the producer, registration and the human-only uses.

## Merge record

- Author vendor: anthropic. Merged by the roadmap session on the operator's typed instruction
  "Finish PR #997 and get it merged", after it re-ran the exact-head barrier.
- Self-hosted review on `fb1b5886`: antigravity lens, no findings at or above medium (round 1's
  one MEDIUM was adopted). The cursor lens errored in both rounds; quorum floor 1 was met.
- Required checks on the PR head were green. `build` on the merge commit was still running when
  this node was written; `conformance` had passed.
- Post-merge classification: no flags (no migration, env, dependency or workflow action).
- Sync: the primary checkout's `main` is at `abf0864c`; the local feature branch is deleted. The
  session's own worktree was left in place, detached at `origin/main`.

## Deployment boundary

Merging does not deploy. The rig's app junction serves the rig's primary checkout, which must be
pulled before new archives carry `trace.control_observation`. Nothing was changed on the rig.

## Remains (all on #988)

1. Operator decision on the declaration surface: the keypad firmware is not flashed
   (workstation-ops#3863).
2. The bench session, at most 45 minutes, operator driving. Not to be run by an agent.
3. Unknown until then: whether a clean human lap certifies at all, and the live behaviour of
   the CSP fields, the vendor save cadence and the vendor lap numbering.
4. The final review fixes (third adversarial round) were not re-reviewed by that reviewer.
