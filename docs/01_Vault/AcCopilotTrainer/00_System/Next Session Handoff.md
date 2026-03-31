---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-03-31
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/01_Decisions/deep-research-synthesis.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/glossary/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **Branch:** `fix/issue-24-visuals-coaching` — **PR #27** open: https://github.com/agorokh/ac-copilot-trainer/pull/27
- **Issue #24:** CSP struct fixes (PR #25 merged), render fixes (PR #26 merged), visual+coaching improvements (PR #27 open — needs merge + in-game test).
- **In-game status:** App runs without crashes. Racing line visible (faint). Brake markers not yet confirmed visible. Coaching hints not yet confirmed showing.

## What was delivered this session

- **PR #25** (merged): Fixed root crash — CSP C-struct field access (`sim.trackName`, `car.id`, etc.) replaced with `ac.getTrackID()` etc. via `csp_helpers.lua` module.
- **PR #26** (merged): Fixed `sim.trackLengthMeters` → `sim.trackLengthM`, `render.line` → `render.debugLine`, pcall-wrapped `car.velocity`, removed dead `car.steering`, added Draw3D diagnostics.
- **PR #27** (open): Brake markers now use cross+sphere+vertical pillar (red/orange, radius 1.2, 300m range). Racing line draws 5-layer ribbon. Coaching hints have fallback messages + throttle analysis + 15s hold. Brighter colors throughout.

## CSP API learnings (critical for future work)

- `ac.StateSim` and `ac.StateCar` are **C-structs that THROW** on invalid field access — always pcall or use known-good fields.
- **Valid sim fields:** `isInMainMenu`, `time`, `trackLengthM`
- **Valid car fields:** `speedKmh`, `brake`, `gas`, `steer`, `gear`, `look`, `position`, `splinePosition`, `lapCount`, `bestLapTimeMs`, `previousLapTimeMs`, `wheels`
- **INVALID (throw):** `sim.trackName`, `sim.track`, `sim.trackConfiguration`, `sim.trackLengthMeters`, `car.id`, `car.name`, `car.driverName`, `car.lastLapTimeMs`, `car.steering`
- **Render API:** prefer `render.debugLine`, `render.debugSphere`, `render.debugCross`, … — NOT `render.line`. Legacy `render.drawSphere` only when no `debug*` helpers exist.
- **Global functions:** `ac.getTrackID()`, `ac.getTrackFullID("/")`, `ac.getCarID(0)`, `ac.getTrackLayout()`

## What remains

- Merge PR #27, deploy, test in-game: confirm brake markers visible, line ribbon visible, coaching text showing.
- If `render.debugSphere`/`render.debugCross` still invisible, investigate CSP version or switch to `render.debugText` as label-based markers.
- Epic issues #7, #8, #9 have merged foundational code; next phases per Project State.

## Blockers / dependencies

- **Assetto Corsa + CSP runtime** is required for in-game validation (markers, ribbon, coaching HUD); this cannot run in CI and blocks confirming PR #27 behavior until tested locally.
