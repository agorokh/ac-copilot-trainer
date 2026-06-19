---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-19
updated: 2026-06-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/244
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/stanley-steering-live-verified-2026-06-19.md
  - AcCopilotTrainer/03_Investigations/racing-driver-and-controller-2026-06-17.md
---

# Frontier racing controller — GGV friction-circle profiler (EPIC #154 Part G, #244)

Push from consumer-grade to RESEARCHER-grade pace, grounded in a 15-agent deep-research workflow +
adversarial red-team + multi-model council (Gemini) + empirical plant-ID from `human_laps.csv`.
PR [#256](https://github.com/agorokh/ac-copilot-trainer/pull/256) (branch
`feat/issue-244-frontier-racing-controller`). Live-verified on `AG_PC`.

## Empirical plant model (from human telemetry)
- **Braking grip rises with speed (aero): `brake_g(v) ≈ 0.95 + 0.0215·v_ms`** → ~1.0g@40, ~2.2g@180.
  The old fixed `brake_g=1.4` brakes far too early at speed → the #1 pace lever.
- Peak lateral ~1.3g (mechanical; **no high-speed cornering data → no aero-lateral claim**, the
  red-team contamination guard: high-speed lateral bins are straight-line-braking artifacts).
- Human used only 0.24–0.97g accel (relaxed). Gear ratios + slip thresholds extracted.

## What shipped (Stage 1 — `tools/ac_harness/ggv_profile.py` + `RacingDriver.from_ggv_profile`)
Forward-backward QSS **minimum-time speed profile** vs a de-contaminated GGV (fitted ay_max,
aero-rising brake, fitted ellipse exponent), arc-length-aware Menger curvature, baked `v_target`
tracked verbatim (no fixed-brake_g, no cap). GGV-tuned longitudinal defaults (minimal re-brake
look-ahead, tighter brake/throttle). Pure stdlib, deterministic, 17 unit tests.
- **LIVE: old Stanley 106.8s → GGV 95.3s** flying lap, AC-valid, 0 stuck, 216 km/h. QSS ceiling 86.2s.

## What is built but OFF by default (Stage 2 — FF + slip limiter)
`ax` feedforward (`_profile_ax` → command the profile's demanded accel/braking; max-not-sum, gated)
+ pure `slip_ratio`/`slip_limited_controls` TC/ABS surrogate (from `acpmf_physics`
`wheelAngularSpeed@104`, NOT AC `wheelSlip`) + `accel_peak_g` override. Unit-tested.
- **LIVE FINDING: enabling FF + aggressive accel on Stanley REGRESSES 95.3s → 104–110s.** The more
  aggressive longitudinal carries more speed into corners than **Stanley can hold (steer saturates →
  overshoot)**. This is the red-team-predicted line↔controller coupling. So `ax_feedforward` defaults
  **OFF**; the shipped controller stays the verified 95.3s. r_eff≈0.347 (fit so cruise slip ≈ 0).

## The wall to beat the human (90.7s) → Stage 3
Stanley is now the binding constraint. **Stage 3 = curvature feedforward + velocity-scheduled
feedback lateral** (Kapania/Gerdes limits-of-handling: `δ = wheelbase·κ + K_ug·v²κ + k·e_lookahead`),
with the steer-units-per-radian + `K_ug` understeer gradient fit from `human_laps.csv` (steer vs
v²κ). Then re-enable Stage 2 FF (the longitudinal gains unlock once the line can be held), then
Stage 4 (min-curvature optimized line for higher apex — the stock fast_lane line is tighter than the
human's, so apexes are line-limited). Targets: <90.7s, toward ~70s.

## Rig recipe (reusable)
surfaces.ini `[SURFACE_0] WAV_PITCH=extended-0` + `[_EXTRA_PERMISSIONS] ALLOW_CUSTOM_AI_MANIPULATION=1`
(saved at `.scratch/part-g/surfaces_customai.ini`; restore from `.bak-precustomai`). Live drivers:
`.scratch/part-g/race_drive_ggv.py` (Stage 1), `race_drive_ggv2.py` (Stage 2). Offline: `model_id.py`,
`qss_estimate.py`, `validate_ggv.py`. Research: `.scratch/part-g/research_synthesis.md`.
