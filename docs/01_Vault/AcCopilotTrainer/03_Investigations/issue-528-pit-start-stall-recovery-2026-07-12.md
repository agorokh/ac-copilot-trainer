---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-12
updated: 2026-07-12
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-515-lap-archives-race-2026-07-11.md
  - AcCopilotTrainer/03_Investigations/issue-512-false-green-kpi-2026-07-11.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/528
---

# #528 — auto_drive pit-start stall: recovery escapes the off-line trap (PR #539)

PR [#539](https://github.com/agorokh/ac-copilot-trainer/pull/539) **MERGED** (`e0b5eef`,
2026-07-12), **#528 CLOSED**. Filing of the standing "autonomous driver stalls near pit start"
flake (Next Session Handoff / #459 lineage).

**Problem (~1/3 of launches FAIL at pit start), two shapes:**

1. **Recovery-to-pit-trap loop.** `spawn_teleport=failed`, `recovery cap (6) exceeded at 0 m`,
   `drove=False max_speed=0.9km/h`. Coaching pipeline healthy, HUD rendering — the car just never
   escaped the pit box.
2. **Hijack-probe exhaustion.** `FAIL (stage=hijack)`, Car0 never appears (pre-drive overlay stall).

**Root cause of shape 1.** In `rig_drive`, an off-line spawn (`off_line_m > 12`) calls
`_teleport_onto_line`; a missed 25 m read-back latched `line_teleport_works=False`, so `_recover`
only called `teleport_to_pits()` — returning the car to the **same pit-box trap it is stuck in**.
Every recovery was spent at 0 m; the `recovery_capped` veto then FAILed honestly (not a false green).

**Fix (PR #539, hardened over 3 review rounds).**
- `rig_drive` tracks a mutable `off_line` state — set at an off-line spawn AND after any
  `teleport_to_pits()` (itself an off-line position), cleared on a successful line teleport — and
  RETRIES the racing-line teleport on recovery whenever the car is off-line. Fixes both the off-line
  spawn AND the **mid-lap-spin-recovered-to-pits** re-entry (self-hosted reviewer HIGH).
- Decision extracted to the pure `should_try_line_teleport_on_recovery`, which **honors
  `--no-spawn-line`** (`spawn_to_line_enabled=False` → pit exit only; codex P2). `teleport_to_pits`
  stays the fallback. Strictly better-or-equal.
- Both shapes folded into the false-green KPI corpus (`spawn_stall_recovery_capped` +
  `hijack_never_landed`) via the extracted pure `drive_leg_succeeded` — the same drive-leg verdict
  `run_auto_drive` uses, so the success gate and the corpus cannot drift.

**Verified.** `make ci-fast` green; KPI 15 broken / 9 healthy / 0 leaks; new unit tests for both
pure predicates + drive-oracle anti-vacuity + the `--no-spawn-line` opt-out. Rig-only teleport/drive
paths stay `pragma: no cover`.

**Live rig verification — PENDING (rig busy).** At merge the rig was saturated by 5+ concurrent
agent sessions (cycling `acs.exe`), so an ambiguous live session must not be hijacked. When the rig
is free, run several `python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016
--track magione --driver racing --drive-seconds 300 --wait-lap` launches to (a) confirm clean drives
still PASS (no regression) and (b) ideally observe an off-line-spawn stall now escape via the
recovery line-teleport (was: cap at 0 m). Fold any observed live stall into the false-green corpus.
