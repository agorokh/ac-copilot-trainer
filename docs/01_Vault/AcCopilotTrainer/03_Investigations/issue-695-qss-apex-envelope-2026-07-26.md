---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-26
updated: 2026-07-26
issue: https://github.com/agorokh/ac-copilot-trainer/issues/695
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-582-l3-corner-refinement-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-577-alien-selfplay-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-543-uncertainty-aware-plant-id-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-575-stale-app-junction-2026-07-15.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #695 — the QSS apex solve violated the plant lateral envelope at bin edges (PR #696)

**Merged:** squash [`7702b42`](https://github.com/agorokh/ac-copilot-trainer/commit/7702b42),
PR [#696](https://github.com/agorokh/ac-copilot-trainer/pull/696); **#695 CLOSED**. Found while
driving EPIC #529's rig gates, not by inspection.

## The lie the report told

The `--iterations 6 --max-scale 1.15` ladder set a new best flying lap (**88.425 s** at
`ggv_scale=1.10`) and then reported iteration 5 as *falsified*:

```
alien line build failed — QSS profile exceeds the plant lateral envelope at point 355:
  v=16.68 m/s, kappa=0.03845 -> 1.0020x ay_max
iteration 5 FALSIFIED (stage report missing …)
```

No spin, no invalid lap, no recovery — **the 1.15 envelope was never driven.** Two defects wearing
a physics falsification's clothes.

## Root cause: `ay_max` is a STEP function of v

`GGVModel._uncertainty_safe_g` picks `safe_g` from discrete 10 km/h bins (#543), so the lateral
envelope is discontinuous in speed. `forward_backward_profile` solved the apex with a bare 8-step
fixed point `v <- sqrt(ay_max(v)/κ)`, which on a discontinuous map need not converge: it can settle
on the **high branch** of a bin edge, returning a speed that lands in a lower-grip bin than the one
used to compute it. `alien_line._verify_lateral_envelope` (`_ENVELOPE_TOL = 1e-6`) then correctly
rejects the build. **The verifier was right; the solver fed it infeasible input**, and the
docstring's "by construction" claim was simply false for a binned envelope.

Measured on the live Magione 911 GT3 R plant, ~3960 curvature samples:
**445 violations (11%), worst 1.4004×** before; **0, worst 1.0000** after. Latent for any combo
whose corner curvature lands in a violating band — iteration 5 was not unlucky.

## What shipped

- `apex_speed()` + `feasible_speed_at_or_below()`: iterate, then **descend until
  `v²·κ <= ay_max(v)` actually holds**. Each corrective step strictly decreases; bin count finite.
- `lateral_envelope_floor_ms2(ggv, v_max_ms)`: a provable lower bound over `[0, v_max]` for the
  exhausted-budget fallback. **Takes the range explicitly** — a binless model with negative
  `k_aero_lat` has its minimum at the TOP, so sampling only zero returns its *maximum*.
- **Every lowering** routes through the feasibility check, not just the apex: both propagation
  passes, coincident-point copies, the drivability floor, and the final `v_top` clamp. Lowering is
  not automatically safe — a 40.1 → 39.9 km/h step on the real plant drops the limit 29% while `v²`
  falls 1% (a 1.4× violation produced by *slowing down*).
- The drivability floor is **not** derived from the apex (that made a sub-floor apex a hard minimum
  and blocked braking entirely).
- `auto_drive` writes the evidence bundle on the pre-launch alien-asset exit, so a line-stage failure
  surfaces `stage="alien_line"` + its real reason instead of the oracle's generic
  `stage report missing` — #577's contract is that the report *names* the falsification.

## Review — 4 rounds, every finding real

Qodo: unchecked exhausted budget; propagation can reintroduce violations; apex-misused-as-floor.
Self-hosted daemon: floor not a lower bound for binless models (**HIGH**, correct). All fixed with
tests that **fail when the specific guard is neutered** — a passing test that cannot fail is worthless.

**Honest limitation kept in the test docstring:** the whole-profile upward-step test is a broad
guard, *not* a reproduction — it passes even unguarded, because the backward pass only lowers points
*toward* an apex, so lowered values stay in the same-or-higher bin. No profile-level reproduction of
the downward crossing was constructible; the rule is proved at the helper level.

## Durable lessons

- **A binned/uncertainty-aware envelope is not a continuous one.** Any fixed-point iteration against
  `ay_max` must end with an explicit feasibility check, and any *lowering* must be re-checked.
  "Smaller is safer" is false for a non-monotonic envelope.
- **A falsification message that names a symptom is worse than none** — it converted a solver bug
  into a fake physics verdict and would have had the next session hunting the controller.
- **Do not branch a fix off a feature branch.** #696 was cut from the #693 docs branch, so its squash
  swept an early, defective copy of that doc into main; PR #694 had to be rebased to supersede it.
  Branch from `origin/main`.
