---
type: decision
status: active
memory_tier: canonical
created: 2026-06-22
updated: 2026-06-22
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/setup-aware-coaching-2026-06-20.md
  - AcCopilotTrainer/03_Investigations/tyre-thermal-knowledge-2026-06-21.md
  - AcCopilotTrainer/03_Investigations/conditions-grip-knowledge-2026-06-21.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
---

# Real-time coaching architecture (offline core shipped 2026-06-22)

The seam from the offline analysis **brain** to a future **real-time / agentic coach**. Three layers,
all pure-stdlib under `tools/ai_sidecar/`, each honest about its data limits (the project invariant:
never claim more than the data proves).

## The pipeline

```
setup_model + lap_dynamics + corner_attribution   (the brain, #264/#268/#275)
            │  tyre_model · conditions_model · track_reference  (#280/#282/#286)
            ▼
coach_report.build_structured_debrief  → {text, balance, corners[], tyres, conditions, corner_reference}   (#291)
            │
            ├── protocol.build_brain_followup → live coaching_response (debrief + cornerAnalysis +
            │       tyres/conditions/cornerReference), non-blocking on lap_complete                 (#291)
            │
            └── coach_handoff.build_coach_handoff → versioned per-corner verdict envelope for an
                    RL/agentic coach (cause_class, confidence, advisory, suggested_setup_delta)     (#289)

realtime_observer.RealtimeObserver  ← streaming live telemetry frames (offline-buildable core)      (#293)
            → grounded per-corner advisories: late_brake (act) + apex_deficit (info)
```

## Honesty guardrails (the part that matters)

- **suggested_setup_delta** (coach_handoff) is cause- AND car- AND confidence-gated. A *technique*
  corner suggests no setup change. Braking/exit deltas fire only while SUSPECTED (advisory); once
  per-wheel slip CONFIRMS the axle, the handoff defers to the brain's verdict (a confirmed rear-lock
  wants bias FORWARD — the opposite of the suspected-front-bias heuristic). The 911-specific
  bias-rearward range is gated to the rear-engine 911 GT3 family.
- **Tyre block** is the slick compound-window thermal model → suppressed in the wet (conditions report
  `slick_model_valid == False`); conditions surfaced from temps alone; no fabricated °C→grip%.
- **Reference target** is the corpus best (demonstrated), never a fabricated GGV theoretical optimum
  from a driven lap. The observer labels `source` as `corpus_best` vs `ggv_optimum` from provenance.
  A reference that is *slower* than the driven lap is never published as a pace target.
- **Observer lap detection** mirrors in-sim `delta.lua`: a backward spline jump is graded only on real
  lap-completion evidence (a lapCount advance, deferred a frame if it lags; or a wrap-shaped jump when
  no counter is supplied). A pit/teleport near the line never produces a spurious end-of-lap advisory.

## What's deferred

Live wiring is **[#277](https://github.com/agorokh/ac-copilot-trainer/issues/277)** (rig-gated): feed
`RealtimeObserver` from the sidecar's `telemetry_tick` stream (the observer already normalizes that
payload; the high-rate contract must add `spline`), deliver `archivePath` on lap_complete, render
`debriefSource==brain` + advisories in `ws_bridge.lua`, and confirm the in-the-ear coach on a real lap.
