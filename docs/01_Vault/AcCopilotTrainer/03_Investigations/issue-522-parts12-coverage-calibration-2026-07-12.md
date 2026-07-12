---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-12
updated: 2026-07-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/522
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-522-actionable-coaching-2026-07-12.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #522 parts 1-2 — every brake zone coached + per-driver marks (PR #525, `56048ae`)

## Root causes (both measured on the real reference)

1. **Coverage**: `segment_corners` deliberately merges an esses complex into ONE
   driver-perceived corner, and `add_corpus_lap` kept only the FIRST sustained brake onset
   per window — Magione's T3/T5 complexes hid 3 gate-grade zones (marks 5, zones 8).
2. **Marks**: the synthetic 77.8 s ideal's points sit ~25 m from a real driver's, so fixed
   marks misjudge an on-pace driver every pass.

## Shipped

- `CornerReference.brake_marks` — every distinct sustained onset (peak ≥ 0.35; a 0.16-peak
  lift is filtered) of the best corpus lap; observer tracks per-ZONE pass state; zone ordinal
  joins the voice dedup keys (resolver + bank scheduler + WS CueArbiter) and per-frame cue
  pacing prevents same-batch zone collisions.
- `calibrate_from_driver_lap` — per-zone EMA (α 0.4) of the driver's onsets: 50 m METRIC
  tolerance, anchors on the marks in force, one-to-one nearest-first matching, order guard,
  wrap-aware (tail marks ~0.99 arm/carry across S/F), layout-guarded, valid laps only.
  Server folds on `lap_complete` (safe-path archive load, bounded dedup of resend forms,
  `AC_COPILOT_BRAKE_CAL=0` kill switch, inactive when `AC_COPILOT_COACH_V2=1` owns cues).
- Latent wrapped-lead spam fixed: T1's cue re-fired ~55×/lap (one-shot `armed_prewrap` +
  frame-bounded pit-return revert, `_WRAP_CONFIRM_MAX_FRAMES=3`).

## Live proof (pre-merge, this branch on the rig, `--assert-coaching` exit 0 twice)

| | V1 (#523) | run 1 | run 2 (post-calibration) |
|---|---|---|---|
| brake_events_coached | 7/9 (78%, RED) | **8/10 (80%)** | **8/9 (89%)** |
| ACTIONABLE / junk | 4 / 0 | 7 / 0 | 8 / 0 |

Calibration live: `4 zone(s) updated` after lap 1 (dup lap_complete deduped); run 2's cues
carried `mark_source: driver_calibrated` (T4 moved ~42 m). T5's three zones each ACTIONABLE.

## Review (5 rounds, converged)

Daemon HIGH ("calibration coupled to debrief") **refuted** — scheduled directly in the
lap_complete branch; live run had debrief OFF and calibrated. 22 codex/qodo P2s fixed+tested
(wrap-aware scan, one-to-one matching, carry semantics, dedup races, metric tolerance,
zone-aware cooldowns) or reasoned (dual archive load = decoupling price; wrapped-mark late
parity). ~30 new tests.

## Remaining #522 scope

V2: phase-slot scheduler; Ollama `corner_advice` picking the ONE between-lap point; coach-v2
runtime calibration (gated inactive today via `_brake_calibration_active`).
