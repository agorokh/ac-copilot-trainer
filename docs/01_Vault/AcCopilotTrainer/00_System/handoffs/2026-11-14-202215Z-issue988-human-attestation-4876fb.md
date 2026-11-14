---
type: handoff
status: active
created: 2026-11-14
updated: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-11-14-issue988-attestation-prerequisites.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-073046Z-roadmap-expansion-a51188.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Issue 988: producer built and reviewed; bench not run, PR held in draft

**Resume pointer.** Draft PR #997 (`feat/issue-988-human-control-attestation`) holds the
default-off human-control attestation producer. #988's acceptance verdict is **open**: the
operator-attended bench session has not run and 0 of 1 rig sessions is used. Do not enable
`AC_COPILOT_HUMAN_CONTROL_ATTESTATION` anywhere until that verdict is recorded on #988.

## What exists on the branch

- `tools/human_control_attestation.py`: producer, read-only capture monitor, offline scorecard,
  bench verdict. `tools/lap_qualification.py`: `human_witness_reasons` (the one decision),
  `register_human_attestation` (the only human-authority writer), revocation by a restrictive
  fact. `tools/rig_controls`: an `attest` button binding. Trainer Lua: per-frame
  `trace.control_observation` (AI state, user control, live frames, wall-clock elapsed).
- Contract, limits and bench procedure:
  [41_Human_Control_Attestation.md](../../../../10_Development/41_Human_Control_Attestation.md).
- Rig facts behind the design: the linked prerequisites investigation.

## Evidence, and what it does not show

- Offline scorecard, run read-only on the rig at commits `987659cc`, `def723ab` and `f85bfcd0`
  (the final code): 0 certified
  of the 156 archives still present from the 174 named laps; 18 have rotated out and were not
  evaluated; 0 of 175 across the 193-entry ledger. The ledger hash and archive listing were
  identical before and after. This is a rejection-only result by construction.
- An independent adversarial review ran three times. Round one found real false-certification
  paths (a vendor record saved before the finish vouching for a lap, a paused mixed lap
  starting before the probed window, a `null` qualification bypassing the never-relabel
  guard). Rounds two and three re-ran every reproduction against the fixes and found
  progressively narrower residuals, each needing the vendor record to contradict itself; all
  were fixed and tested. The fixes for round three have not themselves been re-reviewed.
- The fixes trade yield for safety. In particular a vendor record must be saved a full second
  after the finish, so a lap may certify only after the following lap's save. Whether a clean
  human lap certifies at all on the rig is unknown until the bench.
- Local `make ci-fast` on the macOS development venv (Python 3.14) is not green: 10 tests in
  `test_pressure_bench*` and `test_traffic_eligibility` fail there. The same 10 fail identically
  on unmodified `origin/main` in that environment (no `/proc`, no LuaJIT build of lupa, Python
  3.14 bytecode constants). GitHub `build` was green on the first pushed head. See the PR for
  the result on the final head.

## Blockers and decisions waiting on the operator

1. **Declaration surface.** The button path needs the managed keypad firmware, which is not
   flashed (workstation-ops#3863). Options are on #988: flash it, generalise PR #995's Game Point
   declaration form, or choose another surface.
2. **Bench slot.** One session, at most 45 minutes, operator driving. Not to be run by an agent.

## Seam with PR #995 (#529)

#995 merged at 2026-11-14T20:03Z (`e17f5a54`) and added `attested_human` for permit-bound
practice uses. `main` is merged into this branch. The one conflict was
`tools/lap_qualification.py`; the resolution keeps #995's `attested_human` branch and its
`_append_attribution` ledger helper, and carries the #988 human branch and the revocation rule
into them. #988 stays narrow (`human` for `human_progression` and `analysis`). The two labels
are mutually exclusive per lap, with a test: a practice-attested lap is never certified, and a
verified-human lap gains no practice use. Practice registration happens live and attestation
after the session, so on a shared lap the practice label is the one that lands.

## Next actions

1. Hand PR #997 to `/resolve-pr` for the ready transition and review quorum.
2. After the operator picks a surface and a slot: follow the bench procedure, post the manifest
   hash before running `attest`, record the verdict on #988.
3. Unowned finding: the macOS development venv fails those 10 tests on `main`. It also lacked
   `psutil`, which #995 declared; that was installed into the shared venv during this session.
