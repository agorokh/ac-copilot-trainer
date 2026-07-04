---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-04
updated: 2026-07-04
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-490-tier1-dynamic-channels-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/telemetry-capture-surface-for-ml-2026-07-03.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/488
---

# #488 Part A — Tier-2 CSP force/slip channels (PR #497, rig-verified)

PR [#497](https://github.com/agorokh/ac-copilot-trainer/pull/497) **MERGED** (squash
[`6eba176`](https://github.com/agorokh/ac-copilot-trainer/commit/6eba176)) — `/autonomous-deliver 488`.
Advances EPIC #488 **Part A** (Tier-1 base-AC channels shipped in #490/#492). Epic stays OPEN (B/C/D remain).

## Delivered

**24 append-only per-wheel Tier-2 trace cols (76→100)** — `slipRatio` (longitudinal, unitless),
`slipAngle` (**degrees**, lateral), `mz` (self-aligning torque Nm), `fx`/`fy` (contact forces N),
`dy` (peak μ). Read via CSP `ac.StateWheel` in `wheel_read.lua` (grounded to the rig's on-disk
lua-sdk stubs), assembled in `telemetry.lua`, serialized in `lap_archive.lua`, byte-identical mirror
in `reference_lap.py` (new 76-col pre-#488 variant + parity test). Car-level **`extendedPhysics`**
availability flag persisted in the lap header (`car.extendedPhysics`). Export path extended.
Analysis wiring: `lap_dynamics` loads the channels; `corner_attribution` derives front-vs-rear
**slip-angle balance** and a new **`handling_balance`** rule (channels_needed=`("slipAngle",)`) that
flips advisory→verdict — a direct under/oversteer diagnosis the archive alone cannot produce.

## Rig verification (911 GT3 R, Magione, `auto_drive --driver ggv`, 4 laps / 11.8 km)

Read the real rows of a fresh archive (`lap_..._aaaea0bc_2`, 100 fields, valid):
- **All 24 Tier-2 channels carry real values** (~98.5% nonzero): `slipRatio_fl` −0.157 (front lockup),
  `slipRatio_rl` +0.215 (drive-axle wheelspin), `slipAngle` ±4.6°, `mz` −70…241 Nm, `fx` to 9898 N,
  `fy` −6542 N, `dy` peak μ 3.75. `car.extendedPhysics == true`.
- **Attribution verified live**: slip-angle balance marker in 5/5 corners; `handling_balance` correctly
  **silent** (balance 0.17–0.42°, near-neutral car on the GGV line) and fires an `advisory=False`
  verdict on a synthetic 3° imbalance. Full pipeline (capture→lap_dynamics→attribution) works on real data.

## brakeTemp Tier-boundary question (from the #490 comment) — RESOLVED

`brakeTemp` (`discTemperature`) read a **flat 26.000 °C** on all 4 wheels across this hard-braking lap
**while `extendedPhysics == true`** → **NOT extended-physics-gated** (the operator's "move to Tier-2"
hypothesis is refuted). It is a per-**car** brake-thermal-model dependency — it heats in sessions where
the model is active (a prior stock-surfaces session read 227–496 °C), flat when not. Stays a Tier-1
base-AC channel; caveat documented on `M.brakeTemp` ([`6c3489d`](https://github.com/agorokh/ac-copilot-trainer/commit/6c3489d)).
Treat a flat 26 °C as "not modelled for this car", not a capture bug.

## Grounded corrections vs the research node

- The issue framed slip/force as "CSP extended physics only"; on this rig `extendedPhysics` is the
  normal state for the GT3 R (stock surfaces), so the channels populate on a standard harness launch.
  The availability-gated design is validated (flag recorded, never fails the archive).
- CSP `ac.StateWheel` field names (verified on-disk): `slipRatio`, `slipAngle` (deg), `mz`, `fx`, `fy`,
  `dy` (lateral μ), `dx` (longitudinal μ, not captured). Availability flag: `ac.StateCar.extendedPhysics`.

## Review / merge

`make ci-fast` OK (2390 passed). Qodo's own recommendation endorsed the append-only wide-trace design.
Gemini/Codex quota-limited; self-hosted daemon does not review this repo (App not installed) → gate vacuous.
0 unresolved threads, resolve-gate ledger clean.

## Remaining on EPIC #488

Part B (tyre identity & `tyres.ini` specs → feed `tyre_model.py`), Part C (grain + serialization,
`build_analytics.py` 3-grain + Parquet + SchemaVer), Part D (setup⟷outcome linkage + dynamic-vs-static deltas).
