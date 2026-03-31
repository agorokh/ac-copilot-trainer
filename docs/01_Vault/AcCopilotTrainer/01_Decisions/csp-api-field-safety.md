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

1. Never access unknown fields directly on `sim` or `car` objects.
2. Use `csp_helpers.lua` module for safe API calls (`pcall`-wrapped).
3. Use global functions (`ac.getTrackID()`, `ac.getCarID(0)`) instead of struct fields for identity data.

## Confirmed valid fields

**ac.StateSim:** `isInMainMenu`, `time`, `trackLengthM`

**ac.StateCar:** `speedKmh`, `brake`, `gas`, `steer`, `gear`, `look`, `position`, `splinePosition`, `lapCount`, `bestLapTimeMs`, `previousLapTimeMs`, `wheels`

## Confirmed invalid (throw)

`sim.trackName`, `sim.track`, `sim.trackConfiguration`, `sim.trackLengthMeters`, `sim.trackLength`, `car.id`, `car.name`, `car.driverName`, `car.lastLapTimeMs`, `car.steering`, `car.velocity` (unconfirmed — pcall-wrapped as precaution)

## Render API

Use: `render.debugLine`, `render.debugSphere`, `render.debugCross`, `render.debugArrow`, `render.debugText`

Do NOT use: `render.line`, `render.drawSphere` (do not exist)

## Global functions

`ac.getTrackID()`, `ac.getTrackFullID("/")`, `ac.getCarID(0)`, `ac.getTrackLayout()`
