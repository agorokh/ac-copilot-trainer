---
type: investigation
status: active
created: 2026-07-18
updated: 2026-07-18
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/pr-365-game-point-launcher-2026-06-29.md
  - AcCopilotTrainer/03_Investigations/issue-555-cross-worktree-rig-ownership-2026-07-13.md
source_path: "AcCopilotTrainer/03_Investigations/pr-626-resilient-launch-review-2026-07-18.md"
---

# PR #626 — resilient AC launcher review convergence

## Current truth

PR [#626](https://github.com/agorokh/ac-copilot-trainer/pull/626) implements issue
[#624](https://github.com/agorokh/ac-copilot-trainer/issues/624): bounded retries around the
stochastic CSP initialization livelock, followed by a stability proof and a live operator handoff.
The resolve loop is active; merge and Windows-rig proof remain separate future states.

## Review hardening

- The watcher distinguishes an incomplete trace from a terminal failure, requires render progress
  plus LIVE/not-in-pit readiness, rejects a go-live sample at the timeout boundary, tolerates short
  hitches, and preserves the last terminal retry verdict.
- The machine-wide rig lock is acquired before any preset mutation and stays held until AC exits or
  the operator releases it. Generated presets live under the approved per-user Harness root and use
  PID-scoped names.
- Content Manager startup failures fail the attempt cleanly; retries kill the complete `acs.exe`
  process tree; finite positive/non-negative CLI types reject NaN and infinity.
- Shared preset and foreground-window helpers remove the `auto_drive` layering dependency.
- The driver-facing path now follows the Game Point invariant: non-secret car/track/layout settings,
  a Stable AC action, an AC Session status row, dedicated logs, source/frozen child dispatch, and
  PyInstaller coverage.

## Verification contract

Before declaring review convergence: run focused resilient-launch and rig-launcher tests, run the
repository-venv `make ci-fast`, push once, observe the mandatory ten-minute reviewer cooldown, then
re-audit current-head checks, GraphQL review threads, the self-hosted reviewer body, and the resolve
gate. Do not merge as part of `/resolve-pr`.
