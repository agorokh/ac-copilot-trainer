---
type: handoff
status: active
created: 2026-11-11
updated: 2026-11-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/955
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-11-190538Z-issue955-ci-recovery-0fbd8a.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
---

# Issue 955 native capture and first review corrections

Owner is #955, PR #960, feat/issue-955-traffic-coaching-eligibility. The operator
instructed autonomous input discovery, without another request for asset help.
The recursive replay inventory found five real multi-car recordings: three Spa
11-car inputs, Nordschleife with 16 cars, and Nurburgring with eight. All nine
original recordings and 397 cfg files have hash-verified preservation copies in
this worktree's .scratch/issue955-preserved. The C: filename scan included denied
paths; it does not establish every machine path was readable.

Local ci-fast on 83ea33a passed 5406 tests with 34 skips; hosted build also passed.
Automatic review round 1 terminally reviewed that exact head at 19:32:21Z, with
cursor, antigravity and grok provenance. Three findings were adopted in this
coherent correction: stream traffic in the same large-budget session-end archive
flush; make explicit traffic denials managed restrictions and also quarantine
reference_comparison; validate the optional bounded wire roster and strip it from
all non-observer peripheral broadcasts. Existing managed-only brain/report callers
are covered without changing session_review or setup-prescription logic. The
targeted suite passes 82 tests, including 12000-roster single-step flush readback,
actual consumer denial and 128-car observer/peripheral routing. Full ci-fast of
these corrections exited 0: 5419 passed, 34 skipped (489.20 s); policy/security/CSP
checks also passed. Log: .scratch/issue955-ci-review-fixes.log.

The first playback attempt did not start the lazy collector and left the trainer
active despite an ACTIVE-list edit. It was closed. CSP's documented LAZY=NONE
starts the observation-only collector; the exact trainer junction was temporarily
moved intact into .scratch/issue955-preserved/AC_Copilot_Trainer-disabled-junction
while AC was closed. Its target remains the primary checkout's source. Restore
that link, original app selection and any task-caused mutable coaching state after
capture; retain diagnostics and immutable archives. The active rig lock belongs
to PID 24936 in this worktree, session_kind replay_capture_955.

The isolated first capture uses native CSP 0.3.1/4302 and the unchanged collector
module at 83ea33a: 4534 complete 11-car rosters, replay frames 8 through 8654,
zero sampling errors, 20 Hz p99 0.3554 ms, max 0.8253 ms. Capture SHA256 is
80d96b193a062ed1919e0ae381bc787e8c3f36f357ed1c01d49066a39dd3ec3f;
source replay SHA256 is 406c99e84a35009c19920bd536d6e6cd3144f277732c3b692a2abf00f140331e.
Raw data, source binding and histogram are under .scratch/issue955-native-captures.
This is 11-car proof, not the required 20-car timing. Only normal replay Play and
Exit controls were used; no autonomous driving, live race or setup actuation.

Native capture and independent label preparation continue. A raw-trajectory
labeling aid under .scratch imports no candidate eligibility code; initial capture
has 14 player approach candidates, not a frozen 45-case scorecard. No thresholds
have been tuned. Frozen accuracy, 20-car timing, final review/gate, merge,
distribution, normal-path verification and verified rig teardown remain with #955.
No new issues or spawned sessions were created outside the assigned delivery PRs.
