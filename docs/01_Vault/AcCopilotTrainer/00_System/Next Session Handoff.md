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

## CSP API learnings

Canonical rules (C-struct throws, valid fields, render API, globals) live in **[`01_Decisions/csp-api-field-safety.md`](../01_Decisions/csp-api-field-safety.md)** — read that ADR before changing `sim`/`car`/`render` usage; avoid duplicating the field lists here.

## What remains (issue #24 acceptance — in-game)

- **Visuals (PR #27):** brake markers visible; racing-line ribbon visible; coaching HUD lines show as expected.
- **Render fallback:** if `render.debugSphere` / `render.debugCross` are invisible on your CSP build, try `render.debugText` labels or confirm CSP version.
- **Best-lap / reference:** completing a faster lap updates best reference trace and related HUD where applicable; values survive a session as designed.
- **Brake points:** recording during laps; HUD counts for best/last/session look sane after several laps.
- **Persistence:** save/load (disk snapshot) restores expected state after restart or rejoin (no silent data loss).
- **Sidecar:** with `config.wsSidecarUrl` set and sidecar running (`pip install -e ".[coaching]"` then `python -m tools.ai_sidecar`), WebSocket connects and errors are visible if misconfigured.
- **Epic follow-up:** issues #7, #8, #9 — next phases per Project State.

## Blockers / dependencies

- **Assetto Corsa + CSP runtime** is required for in-game validation (markers, ribbon, coaching HUD); this cannot run in CI and blocks confirming PR #27 behavior until tested locally.
