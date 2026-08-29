---
type: handoff
status: active
memory_tier: canonical
created: 2026-08-29
updated: 2026-08-29
last_updated: 2026-08-29T21:11:12Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/751
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-08-29-210600Z-c1-issue750-wol-failed-596c29.md
  - AcCopilotTrainer/00_System/handoffs/2026-08-29-210200Z-c1-issue764-mcp-verified-4b119a.md
  - AcCopilotTrainer/00_System/handoffs/2026-08-29-195400Z-c1-issue750-rig-gated-59f02b.md
---

# BLOCKED: #751 off-rig re-verified; C1 still needs AG_PC

## Resume here

1. Keep #749, #750, #751, and #764 open together. Do not close #751 alone. No split.
2. #751's source-side scoping is on `main` via PR #766 merge `57f01a6`.
3. Do not retry WoL-only. Next resume needs **physical power-on** of AG_PC, then the
   retained #749/#750 live scientist.

## Closing reconciliation (pasted 2026-08-29T21:11Z)

```
gh issue view 751 --repo agorokh/ac-copilot-trainer --json state
→ OPEN
gh issue view 749/750/764 --json state
→ OPEN / OPEN / OPEN
gh pr view 766 --json state,mergedAt,mergeCommit
→ MERGED 2026-08-29T15:13:04Z  57f01a66bfdeb4ed97f4671fd07f3bb9d2194a26
git grep -n "def scope_lap_archives" origin/main -- tools/ac_harness/auto_drive.py
→ origin/main:tools/ac_harness/auto_drive.py:2747:def scope_lap_archives(
```

## Observed this session (not inferred from comments)

Independent retry+over-scan walkthrough against `scope_lap_archives` on this checkout:

- raw scan = 7 paths (2 failed-session + 3 final-session + 1 same-session extra + 1 foreign car)
- expected timed batch = 3
- scoped = `lap_final_1.json`, `lap_final_2.json`, `lap_final_3.json`
- `len(scoped) == len(expected)`; failed-attempt and over-scan paths excluded

Focused pytest: **11 passed** (`test_scope_lap_archives_*`,
`test_collect_lap_archives_waits_for_scoped_final_attempt_count`,
`test_main_wires_scoped_archives_to_report_and_handshake_refit`,
`test_mixed_session_batch_falsifies_*`, `test_stage_outcome_readers_round_trip`).

Wiring checked in source: `archive_since_epoch = report.attempt_started_epoch or run_started_epoch`;
selector applied inside each poll; extras publish both `lap_archives` and `lap_archives_all`;
handshake `refine_ggv_from_lap_archives(...)` and `stage_lap_archives()` consume the scoped list
only.

## C1 live gate (status probe only — no WoL)

```
tailscale status --json → AG_PC Online=False LastSeen=2026-08-10T22:37:24.1Z
ping -c 2 100.75.251.87 → 100.0% packet loss
ssh arsen@100.75.251.87 → Operation timed out
gh api .../actions/runners → no pc-workstation-ops runner
```

## Unblock

Power on AG_PC at the wall. Then run the retained three-lap scientist from
[[2026-08-29-195400Z-c1-issue750-rig-gated-59f02b]]. No new issue. No split.
