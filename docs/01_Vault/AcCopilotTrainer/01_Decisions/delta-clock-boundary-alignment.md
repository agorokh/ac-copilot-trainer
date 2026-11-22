---
type: decision
status: active
memory_tier: canonical
created: 2026-06-15
updated: 2026-06-15
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/03_Investigations/csp-car-wheels-0-indexed-2026-06-15.md
issue: https://github.com/agorokh/ac-copilot-trainer/pull/185
---

# Decision: the `delta` WS topic publishes only when the lap clock is start/finish-aligned

## Context

`delta_s = (my elapsed since lapStartTime) − (reference lap's elapsed at this spline)`.
The reference's elapsed-at-spline is measured **from the s/f line**. So the delta is only
meaningful when *my* lap clock was also armed at s/f. A lap clock armed **mid-track**
(app load/reload mid-lap, or the post-teleport/reset re-arm via the generic
`tel:lapStartTime()==nil` start-collecting path) makes `delta_s` misaligned by the
reference's s/f→seed elapsed — a plausible but wrong number.

## Decision

The `delta` producer (`modules/telemetry_publisher.lua`, wired in
`ac_copilot_trainer.lua`) publishes **only when the lap clock is boundary-aligned**,
tracked by `state.deltaRefStale`:

- **Defaults `true`** (no delta until the first clean lap is started — an out-lap clock is mid-track).
- **Cleared (`false`) only** when `beginLapClock` fires at a real lap boundary (`car.lapCount`
  increment at the s/f line) — the one place the clock is provably s/f-aligned.
- **Set (`true`)** on: init, track re-entry, `resetRollingDrivingState`, any backward spline
  jump or teleport (guarded `car.resetCounter` change), and any mid-track clock seed.

A teleport is detected via `csp_helpers.safeCarField(car, "resetCounter")` (pcall-guarded
because `resetCounter` is not a confirmed-safe StateCar field). A *wrap-shaped* backward
spline jump (prev>0.8→now<0.25) is excluded from the **rolling reset** (conservative
`delta.isBackwardSplineReset`, to avoid wiping coaching every lap where the spline-0 point
differs from the s/f timing line) but **included** in the delta-skip (`isBackwardSplineJump`),
since skipping a delta frame is harmless.

## Consequences

- The WS `delta` is **stricter than the HUD delta** (which uses the same math but is a soft
  live display the driver eyeballs). After a pit/teleport the WS goes silent until the next
  clean s/f crossing; the HUD may still show its (misaligned) value. This divergence is
  accepted: WS is machine telemetry for the rig screen/harness and must not broadcast
  misaligned values.
- Residual: on CSP builds lacking `car.resetCounter`, the *rolling-state* reset (coaching/
  aggregates) is still not cleared on a wrap-shaped same-lap teleport — tracked in
  [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188). The delta-leak half is fixed.
