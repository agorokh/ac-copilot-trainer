---
type: investigation
status: completed
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
Review resolution's final code commit is `c33c6b7`; the following vault SAVE records its handoff.
All required GitHub checks are green, all 25 GraphQL review threads are resolved, and the
enforce-mode resolve gate reports no substantive findings. The PR remains open and unmerged;
Windows-rig proof remains a separate future state.

## Review hardening

- The watcher distinguishes an incomplete trace from a terminal failure, requires render progress
  plus LIVE/not-in-pit readiness, rejects a go-live sample at the timeout boundary, tolerates short
  hitches, and preserves the last terminal retry verdict.
- The machine-wide rig lock is acquired before any preset mutation and stays held until AC exits or
  the operator releases it. Generated presets live under the approved per-user Harness root and use
  PID-scoped names.
- Content Manager startup failures fail the attempt cleanly; retries kill the complete `acs.exe`
  process tree and wait for a killed CM to leave before reusing its IPC name; finite
  positive/non-negative CLI types reject NaN and infinity. A CM shutdown timeout aborts separately
  rather than consuming a fake launch attempt, and an exhausted failure budget removes any wedged
  `acs.exe` before releasing ownership. CM actuator launch exceptions become `never_live` retry
  verdicts instead of unwinding the loop.
- Shared preset and foreground-window helpers remove the `auto_drive` layering dependency.
- The driver-facing path now follows the Game Point invariant: non-secret car/track/layout settings,
  a Stable AC action, an AC Session status row, dedicated logs, source/frozen child dispatch, and
  PyInstaller coverage. Restarted Game Point instances read the live machine lock rather than
  claiming an owned rig is idle; AC-session failures make aggregate status non-green and point the
  operator to **Stable AC**, not the unrelated START action. Status uses the OS lock byte as
  authority (not reusable PID metadata); on Windows it queries ownership with a locked-byte read
  that never acquires the exclusive byte, and lock I/O failures report an explicit unknown owner
  rather than crash the GUI or claim idle. Game Point passes any configured lock-path override to
  its child. After a local child exits, external lock ownership supersedes the stale exit row.
  PID-scoped generated presets are removed when ownership ends. Transient readiness flicker uses
  the same consecutive-sample threshold as render stalls, unknown shared-memory observations break
  both consecutive runs, and STABLE additionally requires the rig-proven Car0 drivability
  handshake (#466), not only LIVE + not-in-pit. The handshake uses the proven five-second window;
  samples are timestamped before that blocking work, mapping failures stay retryable, and a failed
  controller close invalidates the handshake so Custom-AI ownership cannot leak into the human
  handoff. Its lazy dependency is included in the frozen package. A surviving `acs.exe` after
  bounded cleanup aborts relaunch and holds machine-wide ownership while retrying teardown rather
  than exposing the wedged sim as idle; abnormal retry exits run the same safety path before
  propagating. Ctrl-C remains the console escape hatch, while Game Point's **Release AC** writes a
  durable sibling signal that works for its no-console child even after the GUI is closed and
  reopened. Lock-probe I/O uncertainty is visibly fail-closed (`AC Session: UNKNOWN`) rather than
  silently reported as a healthy owner. An `acs.exe` that appears and then exits before go-live
  fails immediately instead of burning the full timeout, and the developer preview action map
  remains synchronized with the production buttons. A stable child that later loses `acs.exe`
  without an explicit operator release exits nonzero. Portable Content Manager installs are
  configurable through the Game Point settings/environment/CLI path rather than being forced to
  the default Program Files location, including readiness and restart probes keyed to the
  configured executable name. A pre-stability release now attempts AC cleanup and exits nonzero;
  if taskkill cannot remove the process, the durable Release AC signal remains the frozen
  no-console child's explicit unsafe-hold escape hatch. A Car0 probe-close failure aborts through
  the same rig-safety path instead of constructing another controller over a leaked mapping.
  Unknown lock state directs the operator to inspect ownership rather than offering a Stable AC
  action that is guaranteed to be refused. Release AC is also checked throughout bounded
  `acs.exe` cleanup and Content Manager startup/settle waits, then again immediately before the
  actuator call, so an operator release cannot race into a new AC launch. Retry attempts call
  `launch()` after the already-completed cleanup instead of entering a second taskkill window;
  CM-shutdown and unsafe-hold retries remain cancellation-aware. Each attempt performs at most one
  bounded Car0 probe, so a failed handshake cannot repeatedly reassert Custom-AI control. Game
  Point snapshots its local child under `_proc_lock` but performs machine-lock I/O after releasing
  that mutex, keeping Tk-thread START/stop actions independent of filesystem latency. Rig-lock
  timing rejects NaN/infinity at the constructor boundary. A failed one-shot Car0 handshake ends
  its attempt immediately, and durable lock metadata marks Stable AC ownership so **Release AC**
  refuses unrelated harness owners that do not consume the sentinel.

## Verification contract

Final code commit `c33c6b7` passed focused launcher/theme tests and repository-venv `make ci-fast`
(`3144 passed`, `77 skipped`, `86.78%` coverage), followed by the mandatory reviewer cooldown and
current-head re-audit. GitHub reports the build, canonical-docs, and conformance checks green;
GraphQL reports 25/25 threads resolved; the enforce-mode resolve gate is clean. `/resolve-pr` did
not merge the PR or substitute macOS tests for the pending Windows-rig proof.
