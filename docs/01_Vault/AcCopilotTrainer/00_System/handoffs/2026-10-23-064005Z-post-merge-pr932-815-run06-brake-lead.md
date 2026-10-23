---
type: handoff
status: active
created: 2026-10-23
updated: 2026-10-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
pr: https://github.com/agorokh/ac-copilot-trainer/pull/932
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-10-23-051404Z-post-merge-pr930-815-reverb-completeness.md
---

# #815 run 06: brake heads-up timely where the driver braked; two gate decisions remain

[PR 932](https://github.com/agorokh/ac-copilot-trainer/pull/932) merged as `3d88b17` from the
vetted head `b116211` (author vendor anthropic). antigravity and grok found 0 findings; the
cursor lens hit its quota. Checks were green.

## Cause and fix

In run 05, time-to-mark was predicted accurately. But the driver braked 30–34 m before the T1
mark, and the 3.2 s budget was timed to the mark, which left about 0.45 s of margin. Onsets
within `CAL_MATCH_TOL_M` (50 m) are credited to the zone by calibration and by
`live_acceptance.match_brake_target`.

`RealtimeObserver._lead_start` now opens the budget before `mark − 50 m`. Braking inside that
band latches the zone even on slow approaches.

**Gotcha:** replaying a capture's `producer_tick_ingress` rows through each checkout's observer
reproduces live leads within 0.06 s. Use it to predict a scheduling change before spending a
capture (rig script: `reverb-criterion-proto/replay_lead.py`).

## Run 06 (fresh, `3d88b17`, same conditions as run 05)

- Conditions: AC master 0.08, restored byte-exact; voice on [5, 6].
- Run: guardian armed before the hijack and closed AC and the sidecar gracefully; `auto_drive`
  PASS, 1 lap of 347.099 s; tap had 0 drops.
- Analysis (`c53c68b2…`): 19/19 complete, timebase ±35.2 ms, inputs and reference targets valid.

Minimum lead to measured braking (required 1200 ms):

| Cue | Run 05 | Run 06 |
|---|---|---|
| T1 lap 0 | 349 ms | **1635 ms** |
| T1 lap 1 | 796 ms | **2142 ms** |
| T9 | 3136 ms | 4881 ms |

The lap was registered `authority=ai` after analysis (ledger 164). Cleanup was verified, and
`audio.ini` was restored. Evidence:
[#815 run 06](https://github.com/agorokh/ac-copilot-trainer/issues/815#issuecomment-6359094903).

## Remaining (#815 open, clause 36 unchecked, operator decisions)

1. **Cues with nothing to brake for.** 6 of 9 cue targets (T3–T8) are corners where the slow AI
   lap never braked. Those cues fired with intensity 0.0–0.026, at or below the target apex
   speed. They fail `brake_cues_complete_with_reaction_lead` and `timely_brake_coverage` (3/9).
   Decision: suppress a heads-up when there is nothing to brake for?
2. **`act_latency_budget`.** It requires an `act` cue, but the observer has none by #522 design,
   so it cannot pass under `producer_mode: observer`.
3. **`loopback_no_discontinuities`.** One WASAPI loopback discontinuity occurred mid-run. It is
   diagnostic only; the phrase proof is still 19/19.

Recorded, not filed:
- During autonomous runs, the AI lap calibrates lap-1 marks (`legacy_unknown` qualifies for
  `human_progression` until post-run attribution).
- The instantaneous-speed lead ignores acceleration (about −0.2 s on the out-lap).

Fan-out: none created.
