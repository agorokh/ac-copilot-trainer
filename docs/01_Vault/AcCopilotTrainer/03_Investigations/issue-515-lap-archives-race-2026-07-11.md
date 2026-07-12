---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-11
updated: 2026-07-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/515
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-512-false-green-kpi-2026-07-11.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
workspace: "ac_copilot"
---

# #515 — auto_drive report.lap_archives empty on a driven lap (async-writer race + finalization)

Surfaced by the **live SF-26 @ Silverstone GP** verification of the #512 KPI harness generality (the
operator asked to prove the harness drives a *fresh* combo, not just Magione). A `--wait-lap` run
reported `laps=1` but `report.lap_archives: []`. First hypothesis (a scan race) was **wrong** — the
live re-verify showed **no archive on disk at all**: the real root cause was **finalization**.

## Root cause

`run_auto_drive` called `stop.set()` + `controller.close()` the instant the tap saw the `lap` WS
frame, so the trainer's **async deferred writer** (#246/#249: temp-file stream → atomic rename to
`lap_*.json`) never got the post-S/F frames to finalize lap 1's trace — the #305 "not followed by
another lap" class. (The first SF-26 run only got an archive because it happened to coast past S/F.)

## Fix — PR #516 (merged `49af0a7`, closes #515)

- **Grace-drive** (`lap_finalize_grace_s`, default 8s, `--lap-finalize-grace-s`): after a **timed**
  lap (`_has_timed_lap` — `payload.last_lap_ms > 0`; an untimed out-lap is not archived) keep the car
  driving past S/F so the async writer finalizes, then teardown.
- **Drive-budget sizing**: the drive thread brakes on budget exit, so its budget = the FULL tap
  window `tap_settle_s(120) + lap_deadline(max(180,drive_seconds)) + grace` — one source shared with
  the tap timeout, so a late lap never runs the grace against a stopped car.
- **Multi-dir archive poll**: `candidate_journal_laps_dirs` scans EVERY existing journal/laps dir
  (canonical + `app/*/*/journal/laps`) each poll and filters by mtime, so a stale default dir can't
  shadow a renamed install and a fresh-profile dir is found as it appears.
- `report.lap_archives` gated on `report.lap_grace_applied` (single source of truth) so the grace and
  the poll cannot diverge; report `journal_dir` derived from the found archive.

## Verification (observed, from merged main `49af0a7`)

Fully-merged harness, SF-26 @ Silverstone GP: **PASS**, `laps=1`, `lap_grace_applied=True`,
**`lap_archives=1`** (a real 2.2 MB trace), `dist=6215m` (the ~350m past S/F is the grace-drive).
117 off-sim tests green; `make ci-fast` OK.

## Review

**10 review rounds** (Codex + self-hosted daemon) hardened the budget/timing/path edge cases:
grace=0 hang, tap-settle budget gap, timed-lap gate, stale-dir shadowing (→ multi-dir scan). One
daemon HIGH ("unbounded recursive glob") was a **false positive** (the code uses a bounded `glob`,
not `rglob`) and was rebutted. #517 (multi-dir robustness) was implemented here and closed.
