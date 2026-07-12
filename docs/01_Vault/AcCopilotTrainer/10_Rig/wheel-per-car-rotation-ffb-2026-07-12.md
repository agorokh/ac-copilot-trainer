---
type: investigation
status: active
created: 2026-07-12
updated: 2026-07-12
relates_to:
  - AcCopilotTrainer/10_Rig/_index.md
  - AcCopilotTrainer/10_Rig/audio-5.1-positional-engine-2026-07-12.md
---

# Wheel — per-car rotation + FFB (config audit + fix, 2026-07-12)

Rig: **MOZA R3 base + KS (formula) wheel + SR-P pedals** (MOZA Pit House 1.3.9.35).

## Per-car steering rotation — FIXED

The realistic-per-car mechanism is **CM → Controls → AXIS → Steering → "Auto-adjust scale to
match car's steer lock" = ON** (each car uses the portion of the wheel matching its real lock —
GT uses less, road more; web-grounded 2026-07-12). It was already ON, but **Degrees (893°) did
not match the base**.

Fix applied: MOZA base **900 → 1080°**; AC **Degrees 893 → 1080** (`cfg/controls.ini [STEER]
LOCK=1080`). Now base = AC degrees = 1080, auto-adjust ON → correct per-car rotation with headroom
for road/drift cars. (Base rotation slider in Pit House; AC degrees is a wide-range slider — set by
double-click→type, not drag.)

## Per-car FFB — mechanism already present, partially tuned

AC stores a **per-car FFB gain** in `cfg/user_ff.ini` as `[car_id] VALUE=x.xxx` — one entry per car.
This is AC's built-in per-car FFB. Current state: most cars `1.000`; already hand-tuned:
`ks_porsche_911_rsr_2017=1.053`, `ks_mazda_mx5_nd=1.011`, `bmw_m3_gt2=1.010`, `ks_mazda_rx7_tuned=1.010`.
Global `FF_GAIN=1` (100%), MOZA base FFB intensity **100**, `ff_post_process` gamma OFF.

**FFB *feel* is already per-car** (computed from each car's physics). What is NOT done: a systematic
per-car **gain** calibration. Correct method = drive each car, watch in-game FFB app for **clipping**
(peaks pinned at ±1.0), lower gain if clipping / raise if peaks are low; AC saves to `user_ff.ini`.

## Candidate: harness-driven FFB calibration (issue-worthy)

`acpmf_physics.finalFF` (−1..1) exposes the live FFB level. A harness pass could drive each car,
capture `finalFF` peak/clipping %, and compute the optimal `user_ff.ini VALUE` per car (target peak
~0.9, no sustained clip) — an objective, automatable per-car FFB tune. Fits the "by-car enrichment"
theme. Not yet built.

## Physical rim swap

MOZA QR identifies the attached wheel, but auto-loading a per-car profile by rim is not reliable —
keep a Pit House profile per rim and switch on swap. Hardware-side, no AC config.
