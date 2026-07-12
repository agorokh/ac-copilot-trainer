---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-12
updated: 2026-07-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/522
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-511-partd-tablet-voice-endpoint-2026-07-11.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #522 — coaching cues were not actionable; timing redesign (PR #523, `56dd3a4`)

## Operator ground truth → measured

"Brake arrives mid-straight when braking happened 4 s ago — useless." Instrumented laps
(semantic-timeliness tap: 20 Hz telemetry + every dispatch on one clock, scored at
heard-in-ear time) reproduced it exactly: **0/8 brake cues actionable; 8/8 finished with
the mark 7–26 m behind the car**; only 5/10 brake zones coached.

## Root causes (all measured)

1. `_LEAD_S = 0.8 s` vs the true audibility budget: clip (~1.3 s) + audio latency
   (0.1–0.45 s) + human reaction (~1.2 s) ≈ **3.2 s**. Arithmetically unfixable at any tone.
2. The `act` tier fired on *"past your brake point and still coasting"* — reactive by
   definition. **Deeper truth: a live brake-fault imperative is unfixable in principle** — a
   driver braking exactly at the mark is indistinguishable from one about to miss it until
   the mark itself, so a spoken correction is either a false alarm or after-the-fact noise.
3. The reference is a synthetic 77.8 s ideal Magione lap (real GT3 ≈ 85–95 s) with brake
   points ~25 m earlier than real driving → "late" detected every corner → act spam.
4. Corner extraction finds only 5 of the reference's 9 brake zones → back half uncoached.

## The shipped policy (PR #523)

- **One calm anticipatory heads-up per pass**, lead = full audibility budget
  (`_LEAD_S 0.8→3.2`, env `AC_COPILOT_BRAKE_LEAD_S`, cap 0.05→0.09 spline).
- **No live fault imperative** — past the mark: silence + `late_uncoached` flag; corner-exit
  grading owns the feedback ("brake earlier next lap"), including when there is NO apex
  deficit (dedicated `late_brake` info advisory; HUD/WS-only — no info clip, and the
  standalone client's arbiter skips it so the anticipatory phrase is never spoken post-hoc).
- Trail-braking a previous corner inside the (now larger) lead window does not latch
  `has_braked` (`_LEAD_LATCH_TTA_S = 1.5`).
- `timing_report` contract: `no_live_brake_imperatives` replaces
  `critical_brake_alarm_spoken`; lead constants imported from the observer.
- **New falsifiable gate**: `tools/ai_sidecar/voice/semantic_timeliness.py`
  (record/analyze/--assert-coaching): per-cue ACTIONABLE / TOO_LATE / AFTER_FACT /
  REDUNDANT / DEBRIEF_OK at heard-complete time, heard-time brake coverage,
  `evidence_present` anti-vacuous gate.

## Live proof (3 identical autonomous laps, Magione + 911 GT3 R)

| | old | lead=3.2 | final policy |
|---|---|---|---|
| ACTIONABLE | 0 | 4 | **4** |
| junk (TOO_LATE/AFTER_FACT) | 8 | 4 | **0** |
| coached brake events | 5/10 | 7/8 | 7/9 |

## Research (49 adversarially-confirmed findings; synthesis on #522)

Human budget 1.5–1.8 s for a primed one-word cue (3–4.5 s landmark sentence) — 3.2 s in
band. Industry taxonomy: **nobody speaks during the corner** — tone/marker now, words at
boundaries, analysis next lap. Closest AC competitor (Full Grip Vision): 60 Hz, <150 ms,
priority queue + driver-state gating.

## Remaining #522 scope

- **Coverage** (back-half zones; reference segmentation 5-of-9) — the `brake_events_coached`
  gate is honestly red at 78%.
- **Per-driver brake-point calibration** vs the synthetic reference (EMA from own laps).
- V2: phase-slot scheduler; LLM (Ollama corner_advice) selecting the ONE between-lap point.
