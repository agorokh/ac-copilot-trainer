---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-15
updated: 2026-06-15
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/csp-cdata-callable-guards.md
  - AcCopilotTrainer/01_Decisions/csp-api-field-safety.md
issue: https://github.com/agorokh/ac-copilot-trainer/pull/185
---

# CSP `car.wheels` is 0-indexed (FL=0, FR=1, RL=2, RR=3)

## Finding

CSP exposes `ac.StateCar.wheels` as a **0-indexed** array. Per the `ac.Wheel` enum
(SDK comment: *"Wheel index (from 0 to 3)"*):

| index | corner |
|------|--------|
| `wheels[0]` | FrontLeft |
| `wheels[1]` | FrontRight |
| `wheels[2]` | RearLeft |
| `wheels[3]` | RearRight |
| `wheels[4]` | **out of bounds** (returns a zeroed struct, not nil) |

Reading `wheels[1..4]` (the Lua 1-based habit) silently **shifts every corner by one**
and reads the out-of-bounds slot for RR — which surfaces as a plausible-looking but
wrong payload with `rr = 0`.

## Evidence (PR #185)

The live `tire_temps` producer published `rr = 0` while the AC physics oracle
(`acpmf_physics.tyreCoreTemperature[4]`, order FL,FR,RL,RR — the #175 shared-memory
reader) read **all four wheels non-zero** (RR ≈ 68.8 °C). Three independent lines of
evidence agreed it was a read bug, not a genuine zero:

1. **`ac.Wheel` enum** — `FrontLeft=0 … RearRight=3`, "index from 0 to 3".
2. **Shipped CSP app** — `CMRT-Essential-HUD/tires/first.lua` iterates `for i=0,3 do … my_car.wheels[i].tyreCoreTemperature`.
3. **Empirical signature** — `wheels[1..4]` puts FR/RL/RR into fl/fr/rl and an out-of-bounds zero into rr → exactly the observed `rr=0`.

## Fix

Index wheels by the `ac.Wheel` order `[0..3]`. In `tire_monitor.lua`, both
`Mon:currentTemps` (the `tire_temps` producer) and `Mon:update` (lap-temp aggregation +
lockup detection) were corrected — they share the wheel-order contract, so fixing one
without the other would make the streamed temps disagree with the lap aggregates.

## Reuse rule

**Any new `car.wheels` access must use `[0..3]`, not `[1..4]`.** A `for i=1,#wheels`
loop is wrong on CSP (and `#wheels` is unreliable on a 0-indexed array — don't probe it;
a car always has exactly 4 wheels). This pairs with the [CSP field-safety](../01_Decisions/csp-api-field-safety.md)
rule (unknown StateCar fields throw) and [cdata-callable guards](csp-cdata-callable-guards.md)
as the third CSP-API gotcha this project has hit.
