---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-28
updated: 2026-06-28
relates_to:
  - AcCopilotTrainer/01_Decisions/curated-setup-as-data-platform-entity-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/curated-setup-hash-bridge-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/setup-aware-coaching-2026-06-20.md
  - AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Porsche 911 GT3 R 2016 — balanced fast-race setup @ Magione

First curated setup in the data platform. File:
`assets/setups/ks_porsche_911_gt3_r_2016/magione/Copilot_Balanced_Fast.ini` (deployed to
`%AC_USERDATA%/setups/ks_porsche_911_gt3_r_2016/magione/`, so the rig screen lists it via
`setup.list` when driving Magione). Catalog `canonical_hash=054245cb`, 59 numeric params.

> "Mangione" in the request = **Magione** (Autodromo dell'Umbria), the project home/test track.

## Goal & method

A **balanced, fast-race** setup: neutral-stable, confidence-inspiring over a stint, taming the
rear-engine 911's power-on oversteer and lift-off snap **without** dulling rotation on a twisty,
low-to-medium-speed track. Grounded entirely in the operator's own validated references
(`generic/last.ini`, `spa/Realistic_BB_v1→v3`) so every VALUE is an in-range, proven spinner
position. Adversarially verified: 4 vehicle-dynamics lenses → red-team synthesis (overall
confidence **high**).

## Final values (verified)

| Group | Values |
|---|---|
| Brakes/elec | FRONT_BIAS **63**, BRAKE_POWER_MULT 100, ABS **7**, TRACTION_CONTROL 3 |
| Drivetrain | DIFF_POWER 28, DIFF_COAST **60**, FINAL_RATIO 7 (+ gears at car default) |
| Aero | WING_1 1, WING_2 **16** |
| Tyres | TYRES 1, PRESSURE 17 all four (cold) |
| Alignment | CAMBER f **-18** / r **-19**, TOE_OUT f 5 / r **9** |
| Suspension | ARB f **6** / r **1**, SPRING f 118 / r 105, ROD f 18 / r 8, PACKER f 50 / r 80 |
| Dampers | BUMP f7/r9, FAST_BUMP f5/r6, REBOUND f10/r8, FAST_REBOUND f4/r5 |
| Fuel | FUEL 40 L (adjust to race length; 30–45 proven) |

## Why these (the levers that matter for this car)

- **FRONT_BIAS 63** — rear-engine 911 wants *lower* front bias (KB: ~50-56% "true") to avoid entry
  understeer / front lock. 63 = operator's latest hand-tune; 62 is the proven floor.
- **ARB f6 / r1 + SPRING 118/105** — stiff front / soft rear bar+spring sources stability
  *mechanically* (speed-flat, reliable) for a snap-prone rear-heavy car.
- **DIFF_COAST 60, rear TOE 9** — both add entry/trailing-throttle stability where the 911 bites.
- **WING_2 16 (not 20)** — aero is v²-gated; at Magione's low speeds near-max rear wing adds drag and
  over-plants the already-stable rear, dulling rotation. Source stability mechanically, free the wing.

## Corrections made vs the first proposal (by the red-team)

1. **DIFF_COAST 55 → 60** — 55 sits at the lift-off-snap-prone end; the goal is to tame snap.
2. **TOE_OUT rear 8 → 9** — 8 favors rotation; 9 adds cheap rear stability (single biggest fix).
3. **WING_2 20 → 16** — see above (synthesis overruled a 20→18 compromise).

## On-track watch items / tuning hints

- Trail-brake **rear-lock snap**: if it bites, nudge FRONT_BIAS to 64–65 (not below 62).
- **Cold-tyre flat-spots** (ABS 7): manage brake pressure until tyres reach the window.
- If it **won't rotate** → WING_2 toward 14; if **nervous on the fast kink** → back to 18–20.
- Attribution is archive-inferred until live `wheelSlip`/`wheelsPressure` channels are persisted
  (see [[setup-aware-coaching-2026-06-20]] Tier-B). Confirm verdicts against live telemetry.
