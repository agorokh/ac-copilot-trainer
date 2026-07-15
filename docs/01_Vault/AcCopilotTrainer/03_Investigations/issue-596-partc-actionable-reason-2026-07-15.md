---
type: investigation
status: resolved
memory_tier: canonical
created: 2026-07-15
updated: 2026-07-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/596
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-596-pit-stall-sim-death-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-531-partd-live-vitals-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/tier3-consumer-repoint-drift-2026-07-15.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #596 Part C — actionable `auto_drive` failure reasons (PR #598)

## Root cause

The rig repro drove two laps and wrote a valid archive but returned `ok=False` with an empty
`reason`. The only reason field belonged to `DriveStats`, so it could explain a failed drive leg but
not a clean drive vetoed by the pipeline. `evaluate_sequence` already produced exact
`Check(name, ok, detail)` results, but `run_auto_drive` discarded them before report creation.

PR #598 retains the checks and composes a run-level reason with precedence:

1. stage error;
2. drive-leg veto;
3. exact failed pipeline checks.

The caller-only `--laps N` zero-timed-lap assertion is now a real `laps:timed-window` check rather
than an unactionable “see notes” fallback.

## Review hardening

Construction-time repair was insufficient because `apply_handshake_outcome` mutates an already-built
report. The final design makes `AutoDriveReport.reason` a computed property. Direct reads,
`summary()`, and `to_dict()` therefore reflect current `ok`/`error`/checks/drive state without
serialization side effects, including both PASS→FAIL and FAIL→PASS mutations.

The self-hosted reviewer then identified duplicated veto predicates. `drive_veto_reason` is now the
single source of truth; `drive_leg_succeeded` is exactly `drive_veto_reason(stats) == ""`. A new veto
cannot make the run fail silently.

## Resolution state

PR [#598](https://github.com/agorokh/ac-copilot-trainer/pull/598) merged as `9f1b9ca`:

- GitHub state `MERGED`; all required checks were green.
- 0 unresolved GraphQL threads; resolve-gate clean; Qodo 0 bugs.
- Current-SHA self-hosted Cursor review: no medium-or-higher findings.
- Two complete post-push 10-minute cooldowns.
- Local `make ci-fast`: 2,952 passed, 113 skipped, 87.56% coverage.

Issue #596's remaining Parts A/B shipped through PR #600 (`613fae2`) and the issue is closed. See
[[issue-596-pit-stall-sim-death-2026-07-15]] for the stationary-high-gear root cause, bounded
sim-death retry, and live-drive proof.
