---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-25
updated: 2026-07-25
issue: https://github.com/agorokh/ac-copilot-trainer/issues/675
pr: https://github.com/agorokh/ac-copilot-trainer/pull/687
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/issue-522-parts12-coverage-calibration-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/issue-527-coachable-brake-coverage-2026-07-12.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
---

# #675 Coach V2 successor — phase-slot, calibration, between-lap advice

## Outcome

**CLOSED** by PR [#687](https://github.com/agorokh/ac-copilot-trainer/pull/687) MERGED squash
[`13c60e4`](https://github.com/agorokh/ac-copilot-trainer/commit/13c60e43e58cdc34cb24f96dc4d5862b4690ea17)
(2026-07-25T16:16:26Z). Issue [#675](https://github.com/agorokh/ac-copilot-trainer/issues/675) CLOSED.

## Design (council lean)

- **Option A:** calibrate `CoachRuntime` directly (EMA brake action points → PRIME anchors + SAVE
  `brake_point_spline`); `_brake_calibration_active` true when v2 **or** legacy observer is live.
- **Phase-slot policy:** RESLOT — defer `prepare` behind a playing `info` exit micro-verdict
  (same deferred channel as `brake_release` behind a brake alarm); do not drop the next mark.

## What shipped

| Part | Change |
|------|--------|
| 0/3 | `_brake_calibration_target()` prefers `_coach_runtime`; `CoachRuntime.calibrate_from_driver_lap` |
| 1 | `voice/scheduler.py` prepare↔info RESLOT + deferred TTL drop |
| 2 | `coaching/between_lap.py` — one validated `corner_advice` (`slot=between_lap`); T{index+1} labels |
| 4 | Off-pace gate: reference slower than rolling best → suppress PRIME/SAVE; `/health` `cue_suppress_reason` |

## Review hardening on the PR

1. **Daemon MEDIUM (cursor):** plain `lap_complete` must not fold into rolling-best without known
   validity — fixed with separate fold/advice dedup keys + archive/`isValid` gate.
2. **Qodo advisory:** between-lap labels were `T{index}` (T0…); fixed to `T{index+1}` to match
   observer/voice.

## Observed verification

- Local focused pytest: 9/9 green on merged-main symbols after fetch
  (`test_between_lap_advice`, RESLOT, v2 calibration wiring, plain-frame poison guard, off-pace).
- Hosted CI green on head SHA `e3e950b` before merge; squash merge `13c60e4`.
- Symbols confirmed on `origin/main`: `select_between_lap_advice`, `_brake_calibration_target`,
  `phase-slot reslot`, `calibrate_from_driver_lap`, `cue_suppress_reason`.
- **Not run this session:** live harness / `semantic_timeliness.py --assert-coaching` on the rig
  (no AC session). Residual operator proof on next voice-armed stint.

## Coordination

#672 still open and also touches `supervisor.py`, but this PR did **not** edit the launcher —
`alien_line` → `AC_COPILOT_COACH_V2=1` already shipped via #656.
