---
type: decision
status: active
created: 2026-03-31
updated: 2026-03-31
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# CSP API field safety

## Context

CSP `ac.StateSim` and `ac.StateCar` are C-structs. Accessing a non-existent field **throws an error** instead of returning `nil`. This caused total app failure (issue #24).

## Decision

1. Never access unknown or unconfirmed fields directly on `sim` or `car` objects.
2. Use `csp_helpers.lua` for `pcall`-guarded reads of risky fields and for identity helpers; direct `sim`/`car` reads are allowed only for fields listed below as confirmed valid.
3. Use global functions (`ac.getTrackID()`, `ac.getCarID(0)`) instead of struct fields for identity data.

## Confirmed valid fields

**ac.StateSim:** `isInMainMenu`, `time`, `trackLengthM`

**ac.StateCar:** `speedKmh`, `brake`, `gas`, `steer`, `gear`, `look`, `position`, `splinePosition`, `lapCount`, `bestLapTimeMs`, `previousLapTimeMs`, `wheels`

## Confirmed invalid (throw)

`sim.trackName`, `sim.track`, `sim.trackConfiguration`, `sim.trackLengthMeters`, `sim.trackLength`, `car.id`, `car.name`, `car.driverName`, `car.lastLapTimeMs`, `car.steering`

## Unconfirmed / keep pcall-guarded

`car.velocity` — treat as unsafe in some CSP builds; keep `pcall`-wrapped reads where used.

## Render API

**Prefer:** `render.debugLine`, `render.debugSphere`, `render.debugCross`, `render.debugArrow`, `render.debugText`

**Avoid:** `render.line` (not present on target CSP).

**Legacy:** On builds where all `debug*` helpers are missing, `track_markers` may fall back to `render.drawSphere` so markers still appear; prefer `debugSphere` when available.

## Global functions

`ac.getTrackID()`, `ac.getTrackFullID("/")`, `ac.getCarID(0)`, `ac.getTrackLayout()`
