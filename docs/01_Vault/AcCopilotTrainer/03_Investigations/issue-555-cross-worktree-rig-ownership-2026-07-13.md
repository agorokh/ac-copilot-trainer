---
type: investigation
status: resolved
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/555
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/issue-537-ac1-rig-verify-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-277-rig-verify-prepped-blocked-concurrency-2026-06-27.md
---

# #555 — cross-worktree rig ownership, not Content Manager crash-respawn

**Issue [#555](https://github.com/agorokh/ac-copilot-trainer/issues/555) CLOSED by PR
[#563](https://github.com/agorokh/ac-copilot-trainer/pull/563)** (squash
[`a195b38`](https://github.com/agorokh/ac-copilot-trainer/commit/a195b3826dcaffa058fbd55f133ea03974ee758a),
2026-07-13).

## Root-cause correction

The original #537 handoff said Content Manager spontaneously crash-respawned `acs.exe` after
harness kills. That diagnosis was wrong. Content Manager's own AG_PC log shows both supposed
respawns were explicit `AppUi.HandleMessages` requests for `acmanager://race/quick` URLs from a
concurrent #532 worktree (02:25:04 and 02:32:46), immediately followed by Quick Drive starts. AC
and Content Manager are machine-global resources; independent worktrees had no machine-global
ownership boundary, so one harness could replace another harness's live session.

The alternate R8-at-Magione content-crash hypothesis is also refuted: three consecutive pre-merge
R8/Magione runs and one merged-main run all completed clean laps beyond the prior ~90-second failure
window.

## Shipped invariant and attribution

- `tools/ac_harness/rig_lock.py` owns an OS file lock under
  `%LOCALAPPDATA%\AC Copilot Trainer\Harness\rig-session.lock`, shared by every process and
  worktree. Owner PID/worktree/car/track/start metadata makes contention actionable.
- `auto_drive` acquires ownership before sidecar/CM/AC launch and holds it through HUD/archive/report
  evidence. `ExitStack` guarantees release for CLI returns and programmatic exceptions.
- The hijacked `acs.exe` PID is captured and watched off the real-time control loop. A replacement is
  reported as structured `session_replaced` with expected/current PIDs, distinct from `sim_dead`.
- Initial multi-PID ambiguity is fail-sticky but diagnostics refresh to the current live PID set.
  Stop, missing-Car0, timeout, and driver-completion paths force a synchronous final observation so
  the one-second background cadence cannot leak a sub-second replacement as green.
- Only real lock-contention OS errors become `RIG BUSY`; unrelated filesystem/locking errors retain
  their original diagnosis.

## Verification

- Live contention on AG_PC: a second full harness invocation exited immediately with `RIG BUSY`
  and named the owning PID/combo/worktree; the active `acs.exe` remained responsive and its run
  passed.
- Pre-merge R8/Magione: 3/3 hands-off PASS, each one lap, 2637–2664 m, 191.5–191.9 km/h,
  `sim_dead=false`, `session_replaced=false`, stable PIDs 15940 / 23136 / 11560.
- Merged `main` (`a195b38`) R8/Magione: PASS, one lap, 2665.5 m, 191.8 km/h, PID 12004,
  empty unexpected-PID set, both death/replacement flags false. JSON + HUD:
  `.scratch/harness-evidence/issue555-postmerge-r8/`; the HUD was visually inspected with the R8
  live on Magione and coaching rendered.
- Exact pre-review head: `make ci-fast` — 2695 passed, 113 skipped, 87.36% coverage; final focused
  harness suite 188 passed; final GitHub build/docs/conformance green.
- Review converged after three cooldown rounds: every GraphQL thread resolved, resolve ledger clean,
  Qodo no new findings, current-SHA primary reviewer zero medium-or-higher findings.

## Durable lesson

When several worktrees drive one physical simulator, repository-local coordination is not a lock.
Ground process-origin claims in the owning application's log before designing recovery. Distinguish
“the simulator died” from “another session replaced it” in structured evidence, and close the final
sampling race before accepting a clean stop.
