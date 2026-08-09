---
type: investigation
status: active
memory_tier: canonical
created: 2026-08-09
updated: 2026-08-09
issue: https://github.com/agorokh/ac-copilot-trainer/issues/737
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-529-g1-cold-p4-scientist-2026-08-08.md
  - AcCopilotTrainer/03_Investigations/issue-466-setup-drive-rebake-race-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/issue-596-pit-stall-sim-death-2026-07-15.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #737 — setup re-bake race: bounded retries instead of batch abort (PR #740)

## Summary

The launch-time setup bake races CM's `race.ini` regeneration (#466, characterized). Losing
the race on the **correct combo** spawns the car on default fuel; setup verification honestly
FAILed at `stage=setup` with **zero retry budget**, and one such transient miss aborted an
entire #529 P4 scientist candidate batch (`scientist_candidate_batch_incomplete`), discarding
a completed baseline (2026-08-08: r2 lost the race with the candidate file correct on disk;
identical-command r3 won it — confirmed intermittent).

## Fix (PR [#740](https://github.com/agorokh/ac-copilot-trainer/pull/740), merged `0e2b6ac`, 2026-08-09)

- **`auto_drive`:** independent `setup_verify_retries` budget (default 1;
  `--setup-verify-retries`) in the sim-death-style wrapper (#596 pattern — every attempt
  retained in `report.attempts`). Retryable is exactly the race signature — failed fuel-verify
  with `expected_fuel` present in the ack (new pure `setup_ack_fuel_mismatch`) while the loaded
  combo is NOT positively mismatched — reported as `setup_race_suspected` in report.json.
  Wiring failures, #537 cached-session exhaustion, `--skip-launch`, and persistent mismatches
  stay terminal: the verify gate is re-armed on a fresh launch, never weakened.
- **`auto_alien.run_scientist`:** retries a candidate's pipeline ONCE (fresh
  `candidate_NN_retry` evidence root, same candidate file) when the failed stage's report
  carries the marker; recorded under `setup_race_retries`; a second pipeline-level miss still
  aborts the batch honestly.

## Durable lessons

- **Two retry scopes compose — state the composed bound.** Stage budget = cheap in-run
  relaunch for one transient; batch retry = survival when a stage exhausted its budget (both
  launches lost — the p² case). Worst case `2 × (1 + setup_verify_retries)` launches (4 at
  defaults). Codex P2 and the daemon's antigravity lens both flagged the composition; the
  resolution was an explicit bound comment + a composition test through the REAL
  `run_pipeline` (exactly two pipeline entries pinned) — not a code retreat, since dropping
  either level raises batch-abort probability from p⁴ to p² on a confirmed-intermittent fault.
- **Classify retryability from machine-readable report fields, not error strings.** The
  `setup_race_suspected` marker is set where the terminal state is constructed, so the
  scientist layer keys on the same signature without parsing error text.
- **Reconcile classifiers against the real failure artifacts.** The chain was executed against
  the actual r2/r3 bundles (worktree `autonomous-deliver-672-91573d`): fires on r2's real ack
  (fuel 30.0 vs 40.0, correct combo), silent on r3's success, and
  `_candidate_setup_race_stage` returns `identify` on the real candidate report once it
  carries the marker.
- **`evidence_dir` values in `alien_report.json` are CWD-relative** — they resolve in-process
  during a live run; cross-worktree forensics must chdir to the originating worktree first.

## Verification held / residual

Off-rig regression suite is the harness's designed proof surface (injectable legs): full
`make ci-fast` green; 12 new tests across `test_ac_harness_auto_drive.py` /
`test_auto_alien.py`, including the real-pipeline composition test. Reality reconciliation as
above. Residual: a live-rig scientist batch exercising the retry needs the race to fire
naturally under a monitored run — the next P4 batch (batch-size 3, per the #529 plan) runs on
the default budgets and will produce `setup_race_retries` evidence if the race recurs.
