---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-22
updated: 2026-07-22
issue: https://github.com/agorokh/ac-copilot-trainer/issues/630
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-628-acpmf-corpse-classify-2026-07-19.md
  - AcCopilotTrainer/03_Investigations/pr-637-pause-semantics-review-2026-07-20.md
---

# #630 Parts C+D+E — honest launch verdicts + per-trial records (PR #646)

## Summary

PR [#646](https://github.com/agorokh/ac-copilot-trainer/pull/646) (squash `4265845`,
2026-07-22) closed three false-verdict paths in `tools/ac_harness/resilient_launch.py`:

- **Part C — `WEDGED_INIT`.** `classify()` could only reach `FROZE` after a packet-advancing
  LIVE sample, so the #627 init livelock timed out into `NEVER_LIVE` and every freeze rate
  computed from `FROZE` understated it. The new bucket requires **sustained** evidence
  (≥2 alive observations, stream never advanced); a single-sample timeout (blocking probe ate
  the budget) and a rendering-but-never-ready menu both stay `NEVER_LIVE`. `WEDGED_INIT`
  resets the stale-CM restart streak — CM demonstrably delivered an acs.exe.
- **Part D — Car0 TTL.** The drivability handshake was a one-shot latch; a session that loses
  Car0 after go-live was STABLE forever. Now a 45 s TTL re-earns the verdict; failure fails the
  attempt; a packet regression revokes cache and TTL stamp together.
- **Part E — measurement records.** `AttemptRecord` (verdict, UTC start, elapsed, machine
  uptime), `LaunchReport.as_dict()` schema `resilient-launch-report/v1`, CLI `--trials`
  (full-denominator #627 §9.2 mode; exit gated on teardown AND report write), `--no-hold`,
  `--json` (roots: Harness root / repo checkout root — caller CWD rejected).

## Review loop (3 codex rounds, every finding real)

1. `GetTickCount64` default restype is signed c_int → negative uptime past 24.9 days.
2. `--trials --json` exited 0 when the record could not be written (the record IS the
   deliverable) — now exit 1.
3. `--json` accepted arbitrary absolute/`..` paths → approved-roots boundary.
4. Round 2: caller CWD is no boundary (Downloads case) → replaced with the module-anchored
   repo checkout root; trials also fail (exit 1) when end-of-run teardown cannot confirm
   acs.exe exit (a wedged sim must not outlast a released rig lock under a "successful" run).
5. Game Point routing finding rebutted with the rig-lock fact: `--trials` acquires the same
   machine-wide `RigSessionLock`, so no ownership bypass exists; measurement is an
   agent-driven instrument, not a driver-facing launcher action.

## Follow-ups

- #630 Part G (capture driver) — PR #647 in flight.
- Rig payoff: run `--trials` at high uptime for a condition-matched rate (#627 §1/§9.2), and
  catch a real wedge with `freeze_forensics` to settle §6.1.
