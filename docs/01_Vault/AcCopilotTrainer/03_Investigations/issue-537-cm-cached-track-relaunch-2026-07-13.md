---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/537
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-532-plant-id-handshake-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/issue-528-pit-start-stall-recovery-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/menu-skip-race-and-shared-memory-oracle-2026-06-14.md
  - AcCopilotTrainer/03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md
---

# #537 — CM cached-session wrong-track: bounded relaunch on mismatch (PR #544 MERGED)

**PR [#544](https://github.com/agorokh/ac-copilot-trainer/pull/544) MERGED** (squash `41f4d53`,
2026-07-13). **#537 stays OPEN** — AC #1 (live two-track proof) is rig-gated; see below.

## Problem
On the rig (2026-07-12), `auto_drive --track magione` launched via the CM URL but AC came up on
**Spa** — Content Manager ignored the requested `presetFile` and resumed its cached last session.
The track-match guard (PR #535/#532) reads `acpmf_static.track` post-hijack and FAILed fast at
`stage="launch"` on the mismatch — an honest failure, but it aborted the whole run on the FIRST
cached-session hit instead of retrying (a `max_launches` budget and the per-attempt relaunch loop
already existed above it; the guard just `return`ed instead of re-entering them).

## Delivered (AC #2 — the mechanism)
`run_auto_drive` (`tools/ac_harness/auto_drive.py`) now, on a track/car mismatch, closes the
controller and `continue`s the retry loop (relaunch) while budget remains and not `skip_launch`.
Each relaunch kills `acs.exe` and re-issues the `acmanager://` Quick-Drive URL to the now-running CM,
which processes it via single-instance IPC without the cold-start auto-resume race that served the
stale combo. Only the terminal attempt (or `skip_launch`) FAILs fast at `stage="launch"`, preserving
the #535/#532 honest guard. Robust across the issue's hypotheses: helps for a transient race,
degrades to the honest FAIL for a persistent read failure.

## Design: two-tier guard (verdict DRY via `loaded_combo_mismatch`)
- **Authoritative post-hijack guard (#535 rig-proven):** every drivable session passes through it. A
  landed hijack means CSP created Car0 — a STRONGER "session fully initialised" signal than
  `_wait_live`'s LIVE+advancing-physics — so `acpmf_static` is reliably populated there. Single
  source of truth: a not-yet-populated static page can never slip a mismatch to the drive leg.
- **Best-effort, fail-safe setup-path early-out (#537 Codex P2):** a cached session also fails
  `apply_setup`'s fuel verify (verified before the hijack per #459); this relaunches instead of
  aborting at `stage="setup"` on the first hit. On "cannot confirm" it does NOT drive — it falls
  through to the `stage="setup"` return (safe). Known narrow edge (setup ack fails without a fuel
  read + cached + static unreadable) → `stage="setup"`, fail-safe; not worth an rig-unverifiable fix.

## Review journey (learning)
5 review rounds. The self-hosted **cursor daemon** is the primary reviewer and earned it: after an
intermediate commit UNIFIED the two checks into one *pre-hijack* gateway, the daemon flagged a **HIGH**
— a pre-hijack `acpmf_static` read can be unpopulated, and removing the post-hijack guard would let a
mismatch reach the drive leg. Correct. **Lesson: do not relocate rig-proven behavior (#535 post-hijack
read, #459 setup-before-hijack) on an off-rig assumption.** Reverted the unification; restored the
post-hijack guard. Also fixed 2 Codex P2s (setup-path retry; post-loop `stage` keyed on
`last_launch_error` so a failed relaunch reads `stage="launch"`, not a misleading `stage="hijack"`).

## AC #1 — live rig verification PENDING (credential-blocked)
AC #1 (`acpmf_static.track` reads the requested track for two tracks back-to-back, no manual CM
interaction) is rig-gated. This session ran on macOS (`epam-m5pro`); `ssh arsen@100.75.251.87` now
returns `Permission denied (publickey)` even though the documented `mac-to-ag-pc` key was authorized
as of the 2026-06-29 handoff — the rig's `authorized_keys` has evidently been reset since. Restoring
it is an operator/access-control action. **Unblocker (on the rig):**
`python -m tools.ac_harness.auto_drive --car ks_audi_r8_lms --track magione` then `--track spa`
back-to-back (non-extended car on stock surfaces per #277), confirming `acpmf_static.track` each time.

## Residual (separable)
`acpmf_static.track` reports only the **base** id (no layout) — a cached same-base-different-layout
session is not detectable from shared memory (`track_ids_match`). Not addressed here.
