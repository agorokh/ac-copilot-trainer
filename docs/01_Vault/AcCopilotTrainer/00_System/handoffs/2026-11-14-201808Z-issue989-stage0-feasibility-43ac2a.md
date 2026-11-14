---
type: handoff
status: active
created: 2026-11-14
updated: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/989
relates_to:
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-14-evidence.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-180100Z-issue529-prospective-human-start-0e6a91.md
---

# #989 stage 0 delivered as software; feasibility verdict INCONCLUSIVE

Card `REX-20261114-02`. The operator started stage 0 only. Stage 1 is not authorized, and this
result does not support scheduling it. #989 stays OPEN.

## Resume pointer

Verdict comment with every number, session identifier and hash:
[#989 comment 6883614623](https://github.com/agorokh/ac-copilot-trainer/issues/989#issuecomment-6883614623).
Code: PR [#998](https://github.com/agorokh/ac-copilot-trainer/pull/998), branch
`feat/issue-989-coaching-effect-trial`, linked with `Refs #989`.

## What shipped (new files only)

- `tools/ai_sidecar/coaching_trial.py`: append-only cue-exposure journal. A `RecordingLedger`
  (subclass of `CoachingLedger`) is swapped into `CoachRuntime.ledger`; `TrialRecorder` wraps
  `observe`. One record per ARMED approach: session, lap, corner, root, eligibility, assignment
  (`as_delivered`), commit, emitted cue, pass outcome (targeted-error magnitude, corner time).
- `tools/ai_sidecar/coaching_trial_replay.py`: replays lap archives through `CoachRuntime` with
  the journal on. Reads archives only. Replays each session with and without the journal and
  fails on any byte of difference in the advisory stream.
- `tools/coaching_lake/coaching_effect.py`: ARMED approaches per lap, per-root variance,
  simulated minimum detectable effect, and the fixed #989 thresholds.
- 51 tests in `tests/test_coaching_trial.py`, `test_coaching_trial_replay.py`,
  `test_coaching_effect.py`.

Not edited: `coaching_runtime.py`, `coaching_ledger.py`, `server.py`, `lap_qualification.py`,
`human_control_attestation.py`, `build_analytics.py`. No randomizing or withholding mode exists.

## Feasibility result

202 lap archives and `lap-attributions.json` were copied read-only from the rig journal
(2026-11-14T19:55Z to 20:02Z, after a read-only inventory showed no sim process and no rig
lock). 8 analysis-eligible sessions replayed; 412 ARMED approaches journaled; output
byte-identical in all 8. The verdict is inconclusive because:

- the ledger committed 412 cues and the runtime emitted 0: in both sessions that armed anything,
  the fastest qualifying reference from another session is slower than the replayed laps, and
  the off-pace gate mutes PRIME cues;
- 404 of 412 approaches come from one 140-lap Porsche/Spa session with `shared` control
  authority and a lap-time SD of 0.32 s, which is not human pass-to-pass variation;
- no replayed lap is attested human driving (#988 has not passed).

Mechanical readings, all reported on the issue: emitted cues give 0 projected approaches;
committed cues give 82 projected and a 9% detectable effect; the pre-set rule of 5 eligible laps
per session leaves 1 session. None is evidence about a human driver.

## What remains

- **Data.** Stage 0 needs at least 3 human sessions on one car and track, each with at least 5
  valid laps, plus a live-reference lap for that combo faster than those laps. The attested
  Porsche/Spa sessions prepared under #529 G3 would supply this as a by-product. Rerun:
  `python -m tools.ai_sidecar.coaching_trial_replay --laps-dir <journal/laps> --out <new dir>`
  then `python -m tools.coaching_lake.coaching_effect --journal-dir <dir> --out <dir>/report.json`.
- **Stage 1 hook.** When the runtime gates a PRIME before calling `due_prime` (capability,
  traffic, practice hold), the anchor-crossing instant is not visible from the ledger. Stage 1
  must log assignment before the anchor, so it needs a hook in `coaching_runtime.py`.
- **Private seam.** Pass measurements read `runtime._pass` and `_signature_from_pass`. Tests
  pass against the runtime as changed by PR #995; a rename fails them and the journal raises
  `TrialSeamError`.
- **PR #998** review and merge follow `/resolve-pr`.

## Evidence and limits

- Retained in the delivery worktree, gitignored: `.scratch/issue989/rig-copy.sha256` (203
  per-file hashes), `runs-v3/` (manifests, journals, reports), `verdict-comment.md`. The copied
  archives were kept in the session scratchpad only, never committed or uploaded.
- Rig time used: 0 s. Nothing was started, written or deleted on the rig.
- Decision-rule changes made after seeing the data are disclosed in the issue comment.
- Local `make ci-fast` on the macOS host: every non-test step passes; `ci-test` has 10 failures
  in `test_pressure_bench*.py` and `test_traffic_eligibility.py` that also fail on untouched
  `origin/main` there (Python 3.14 code-constant serialization, `/proc`, LuaJIT). GitHub `build`
  is the authority for this PR.
- Tier-3 `ac_copilot` was queried at LOAD and before edits; vault Tier-2 supplied the card.
