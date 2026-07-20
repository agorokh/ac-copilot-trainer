---
type: investigation
status: complete
created: 2026-07-20
updated: 2026-07-20
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/_index.md
  - AcCopilotTrainer/03_Investigations/issue-628-acpmf-corpse-classify-2026-07-19.md
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-init-livelock-2026-07-17.md
---

# PR #637 review rounds — pause semantics settled in resilient_launch.classify

## Summary

PR #637 (#630 Part B: pause read from physics-packet stagnation) went through two
self-hosted daemon rework rounds. The rounds converged on a three-way split of
pause semantics in `tools/ac_harness/resilient_launch.py` that future changes
must preserve:

1. **Stability-clock suspension is UNBOUNDED.** Physics-pinned intervals are
   never credited as proven-live time, whatever the budget — STABLE must be
   earned with physics RUNNING. (Round-2 daemon HIGH: budget-tied suspension
   let an animating-gfx pause accumulate wall-clock past `pause_budget` and
   hand off a session whose physics never resumed.)
2. **Freeze-counter clearing is BOUNDED by `DEFAULT_PAUSE_BUDGET` (300 s).**
   Within the budget, pinned streams read as an operator pause/menu (AC often
   leaves `status` at LIVE when paused — status is not a pause signal). Past
   it, sustained dual-stream stagnation falls back to the ordinary
   stall/not-ready paths: a hang pinning both streams while `acs.exe` stays
   enumerated is indistinguishable from a pause at any single instant.
3. **`_watch_live`'s deadline extends by the reported pause hold** (capped at
   `pause_budget`) via the `pause_sink` out-param — a long alt-tab stays
   PENDING instead of FROZE + taskkill of a healthy session (round-1 Codex P1
   + daemon HIGH).

## Resolution ledger

- Codex P1 (deadline) — fixed `33bb78d`, thread replied + resolved.
- Daemon HIGH #1 (deadline) — fixed `33bb78d`.
- Daemon MEDIUM (dual-stream hang read as pause) — bounded hold, `33bb78d`.
- Daemon HIGH #2 (STABLE-while-pinned past budget) — fixed `0ba0346`; the
  regression test was verified to FAIL against the pre-fix source.
- Antigravity MEDIUM (`pause_sink` mutable out-param vs. purity) — advisory,
  WONTFIX-with-rationale PR comment (return-type change churns ~95 call
  sites; sink is opt-in and inert for pure callers).

## Test-discrimination discipline (worth reusing)

Each regression test was checked against the pre-fix source (stash the source
file only, keep the test file, run) to prove it actually catches the hole —
`test_stable_requires_physics_advancing_past_pause_budget` fails as STABLE on
the un-gated code, passes PENDING with the gate.
