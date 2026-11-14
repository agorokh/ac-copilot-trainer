---
type: investigation
status: active
created: 2026-06-20
updated: 2026-06-20
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md
  - AcCopilotTrainer/03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/frontier-controller-ggv-2026-06-19.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/264
---

# Setup-aware pro coaching: comprehend setup + attribute corner pace (setup vs technique)

Issue #264. Builds the harness's pro-race-engineer brain: comprehend the car setup and connect each
parameter to driving performance, so a corner's pace can be split into a **setup** cause vs a
**driver-technique** cause. New stdlib-only modules under `tools/ai_sidecar/`.

## Architecture (4 layers)
1. **`setup_model.py`** — parse a setup `.ini` / lap-archive `setup.snapshot` / live
   `ac.getSetupSpinners()` into a typed, categorized `CarSetup` (brake bias %, ABS/TC, pressures +
   splits, ARB balance, wings, diff, compound). The vocabulary the rest speaks.
2. **`setup_knowledge.py`** — the adversarially-verified GT3 knowledge base (17 params). Carries the
   key fields the discriminator needs: `speed_dependence` (AERO=∝v² / MECHANICAL=flat / NEUTRAL) and
   `car_dependent` (rake, compound). Plus the Tier-B channel map.
3. **`lap_dynamics.py`** — derive dynamics (lat g = v²·κ of the driven path, long g = dv/dt) from the
   archive trace; segment corners; compute a falsifiable `CornerSignature` per corner.
4. **`corner_attribution.py`** — `compare_laps` (localize where time is lost), `analyze_balance`
   (the #1 discriminator), and a diagnostic engine that distinguishes setup from technique.
   `coach_report.py` renders the debrief (+ CLI).

## Verified physics principles (from the research red-team — do not "simplify" away)
- **Aero is speed-gated (∝v²); mechanical balance is speed-flat.** Binning a deficit by corner speed
  is the strongest archive-computable SETUP discriminator: grip *saturation* in high-speed corners →
  AERO levers (wings); in low-speed corners → MECHANICAL (ARB/springs/diff).
- **Rake direction is car-dependent** — prefer a wing change for an unambiguous front/rear shift.
- **The rear-engine 911 GT3 R wants LOWER front brake bias (~50-56%)** than a typical GT3.

## The honest data split (the whole point)
The saved archive trace carries only `spline, speed, throttle, brake, steer, gear, position`. So the
engine **localizes** a loss to a phase + speed band (archive), but **cannot** attribute a lockup to
an axle (needs per-wheel slip), grip loss to pressure/temp, or a TC cut — those are emitted as
*suspicions* and upgraded to verdicts only when the live channel is supplied. Highest-value
follow-up (research's #1): **persist `wheelSlip[4]` + `wheelAngularSpeed[4]`** — promotes 8 of 14
archive=false rules to confirmed verdicts. See #264 follow-up.

## Verified on real geometry
Ran the full pipeline on the real Magione `fast_lane.ai` (1754 pts, GGV 77.84s) with an optimal
reference vs a degraded "student" lap: 6 corners detected, time loss localized per corner, balance
verdict `mechanical_all_speed` (low-speed grip used 96% vs high 38%), per-corner output correctly
split "carried too little apex speed → TECHNIQUE" from "at the grip limit → SETUP". Reading the live
output also caught + fixed an inverted grip-saturation branch. 51 unit tests, ruff clean.
