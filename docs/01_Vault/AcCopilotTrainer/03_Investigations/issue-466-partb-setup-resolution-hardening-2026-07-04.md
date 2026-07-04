---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-04
updated: 2026-07-04
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-466-setup-drive-rebake-race-2026-07-03.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/466
---

# #466 Part B — setup-resolution + `race.ini` concurrency hardening (PR #496)

`/autonomous-deliver 466`, 2026-07-04. PR [#496](https://github.com/agorokh/ac-copilot-trainer/pull/496)
**MERGED** (`b9f597a`). Off-rig, unit-tested — no rig needed.

## Reconciliation (why this was the remaining work)
Live-checked, not the issue body: #466 `OPEN`; criterion **(b)** shipped (#482 MERGED); criterion
**(a)** is a documented fundamental CSP/CM limit (#495 MERGED — see
[[issue-466-setup-drive-rebake-race-2026-07-03]], I did **not** re-litigate it). The only
unaddressed, actionable scope was **Part B** — 3 self-hosted-daemon (cursor) MEDIUM findings on the
merged #461/#465 code, captured on the issue. They are **separable from the criterion-(a) limit**:
B1/B2 harden the setup **archival/resolution** path (used by `--setup` alone and manual play), B3 is
a `race.ini` write-integrity risk on the re-bake loop. `git log` confirmed no commit after #482
touched `setup_reader.lua` / `auto_drive.py`.

## What shipped
- **B1 — session-cache staleness** (`setup_reader.lua`). The `race.ini` setup cache keyed only on
  session-identity fields, so a long-lived `acs.exe` that REUSES a Quick-Drive session index with a
  different baked setup kept serving the first spawn's path. Fix: `M.resetRaceIniCache()` called from
  the trainer's `resetSessionState` / `resetRollingDrivingState` (next to `lifecyclePublisher.reset()`).
  **Key insight:** `race.ini` + session-index alone cannot tell "same spawn, edited in place" (keep —
  the car hasn't re-read it) from "new spawn, reused index" (refresh). The **spawn signal** is the
  discriminator; the trainer holds it. So the existing `test_race_ini_setup_resolution_is_cached_within_session`
  (same-spawn edit ⇒ keep) stays green AND the new back-to-back test (reset between ⇒ refresh) passes —
  the finding is resolved **without weakening a test**.
- **B2 — transient miss vs vanilla fallback** (`setup_reader.lua`). `readActiveSetupPathFromRaceIni`
  now returns `(value, transient)`. A momentarily missing/locked `race.ini` → `transient=true` →
  `guessSetupIniPath` returns nil (retry), never the legacy `setups/<car>/<track>/` folder guess
  (which can archive the WRONG setup). Vanilla `SETUP=` without `_EXT_SETUP_FILENAME` → `transient=false,
  value=nil` → still folder-guesses (927b07ed fallback preserved).
- **B3 — `race.ini` read contention** (`auto_drive.py`). `write_setup_baked_race_ini` requires a
  **stable two-read snapshot** (two identical back-to-back reads) and treats an **unparseable read**
  as a no-op — either guard failing returns `"unstable"` and writes nothing. A torn CM write can no
  longer be baked back and atomically drop CM-owned `race.ini` sections. Added an `unstable` counter
  to `RaceIniBakeState` (excluded from `ready`).

## Verification (observed)
- 5 new tests mapped to the Part B acceptance criteria (lupa B1 reset-refresh + B2
  transient-no-guess / vanilla-still-guess; pytest B3 torn-read + unparseable-snapshot both leave
  `race.ini` byte-for-byte intact). `make ci-fast` **green** (format, lint, full suite, bandit,
  secrets, policy, CSP API/UI safety).
- Qodo reviewed and **endorsed** the double-read + unparseable-noop design, explicitly rejecting
  lock-based and mtime/size-backoff alternatives; no bug findings. Gemini quota-limited (24 h,
  external, non-gating). Self-hosted daemon posted no current-SHA review after two cooldowns →
  vacuously satisfied per `resolve-pr` anti-hang (head SHA resolved cleanly).

## #466 terminal state
All actionable scope complete: criterion (b) #482, Part B #496, criterion (a) = documented CSP/CM
limitation #495 (only an upstream CSP/CM change — a QuickDrive setup slot or a resettable autonomous
state — could unlock it). **Recommendation: close #466** (or relabel `blocked`/`upstream` if kept
open as the upstream ask).
