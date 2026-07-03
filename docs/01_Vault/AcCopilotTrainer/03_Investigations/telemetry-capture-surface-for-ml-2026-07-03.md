---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-03
updated: 2026-07-03
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/pr-480-simhub-launcher-toggle-2026-07-03.md
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
source_path: "AcCopilotTrainer/03_Investigations/telemetry-capture-surface-for-ml-2026-07-03.md"
---

# AC telemetry capture surface for ML — full inventory + gaps (2026-07-03)

Research (3 spawned agents: runtime SM/CSP surface, `tyres.ini` specs, telemetry/ML best practices)
into **everything capturable** from Assetto Corsa for a tyre/chassis ML lake, after the operator
noted we store setup knobs + driver inputs but are blind to dynamic response. → EPIC
[#488](https://github.com/agorokh/ac-copilot-trainer/issues/488) + quick-win
[#490](https://github.com/agorokh/ac-copilot-trainer/issues/490).

## Current baseline (post-#478, verified on origin/main)

Per-sample trace = **30 cols** (`lap_archive.lua::TRACE_FIELDS` ⟷ byte-identical `reference_lap.py`):
`spline,speed,eMs,throttle,brake,steer,gear,px/py/pz, wheelAngularSpeed[4], wheelSlip[4],
tyreCoreTemp[4], rpm, accG_long, accG_lat, yaw_rate, wheelsPressure[4]`. Header adds `compoundIndex`
+ compound **short** name (#478). **Static setup** = flattened setup INI → `setup_params` (all systems:
`WING/CAMBER/TOE/DAMP/SPRING/ROD_LENGTH/ARB/DIFF/FRONT_BIAS/BRAKE_POWER/FUEL/TC/ABS/PRESSURE/[TYRES]`),
captured when `setup_snap` is passed. `tyre_model.py` still uses generic soft/med/hard windows.

## What's capturable (the durable field map)

**Tier 1 — BASE AC `acpmf_physics`** (verified in Kunos `SharedFileOut.h` + CSP `sim_info.py`; reachable
via our CSP Lua `ac.getCar().wheels[i]` — **no extended physics needed**). The important correction:
tyre temp bands and brake temps are **base AC, not ACC-only**.
`tyreTempI/M/O[4]` (°C), `brakeTemp[4]` (°C), `wheelLoad[4]` (**N**), `tyreWear[4]`, `tyreDirtyLevel[4]`,
`camberRAD[4]` (**rad**), `suspensionTravel[4]` (**m**), `rideHeight[2]` (m), `brakeBias` (0=rear..1=front),
`turboBoost`, `fuel` (L), `tyreContactPoint/Normal/Heading[4][3]`, `kersCharge`, `heading/pitch/roll`.
**`accG` axis order = `[0]=lat, [1]=vert, [2]=long`** (empirically confirmed — validates #478's mapping).

**Tier 2 — CSP extended physics only** (via `ac.getCar()` Lua; NOT in base-AC shared memory):
`slipRatio[4]`, `slipAngle[4]`, `Mz[4]`, `Fx/Fy[4]`, `Dy[4]` (μ). (ACC exposes these in its shared
memory struct + `brakePressure`/`padLife`/`tyreSet` — irrelevant since we run base AC + CSP.)

## Tyre identity & specs (resolve the index → real numbers)

Setup `[TYRES] VALUE=N` → `[FRONT_N]`/`[REAR_N]` in the car's **`data/tyres.ini`** (inside encrypted
`data.acd`; key = folder name; CM/CSP decrypt; mod cars ship unpacked `data/tyres.ini`):
`NAME` ("Toyo R888R"), `WIDTH`, `RADIUS`, `RIM_RADIUS` (→ size `255/10/R21.8`), **`PRESSURE_STATIC`**
(ideal cold), **`PRESSURE_IDEAL`** (ideal hot), `DX_REF/DY_REF` (peak μ), `[THERMAL_*] PERFORMANCE_CURVE`
LUT (→ **optimal temp window** = LUT peak), `[HEADER] VERSION` ("version 10"). **Live** (no ACD decrypt):
`ac.getCar(0).compoundIndex` (== setup `[TYRES] VALUE`), `.tyresLongName`, `.tyresName`,
`SPageFileStatic.tyreRadius[4]`. **No game-level tyre brand** — `NAME` is car-authored free text; segment
ML by `(car_id, compound_name)`. (`ac.getCarBrand` = car make, orthogonal.)

## ML best-practice takeaways

- **Three grains** — per-sample trace **+ per-lap scalar features** (avg/max/end temp+pressure,
  cross-tread gradient, tyre-energy `Σslip·load·dt`, wear delta, fuel-corrected laptime) **+ per-stint
  series** (`deg_slope` vs `laps_on_set`). Intra-lap traces alone **cannot** express degradation.
- **Primary segmentation keys = `compound × laps_on_set`** (tyre age; AC exposes no per-set serial →
  derive from pit/change tracking). Confounds: fuel mass, air/road temp, grip level.
- **Serialization:** immutable JSON as raw landing → **Parquet/columnar** ML surface; retain per-sample
  `dt`; SchemaVer + DuckDB `union_by_name` for additive evolution.

## Canonical sources (vendor into repo when implementing)

Kunos `SharedFileOut.h` (base-AC struct + units) · CSP `sim_info.py` (canonical ctypes) · mdjarv C#
(cross-check) · PyAccSharedMemory (ACC deltas) · `tyres.ini` schema (assettocorsamods) · CSP
extended-physics docs · F1 degradation modeling (compound × age, fuel-corrected) · MoTeC/iRacing channel
refs. Full URLs in #488.

## Gaps → tracked

- **#490** — Tier-1 base-AC channels (quick win, no CSP dependency).
- **#488** — EPIC: Tier-2 CSP channels + tyre identity/specs (Part B) + degradation-grade serialization
  (Part C) + setup⟷outcome linkage (Part D). Delta beyond closed #478/#345/#402/#344/#403; roadmap #401.
