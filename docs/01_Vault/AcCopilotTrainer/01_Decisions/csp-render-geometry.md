---
type: decision
status: active
created: 2026-04-01
updated: 2026-04-01
relates_to:
  - AcCopilotTrainer/01_Decisions/csp-api-field-safety.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# CSP render geometry choices

## Context

Issue #24 required visible 3D markers and racing line in the TRANSPARENT render pass. Initial implementation used `render.debugLine`, `render.debugSphere`, `render.debugCross` — all confirmed as 1-pixel wireframe primitives invisible from cockpit at driving distance (100-300m). Diagnostic logging (PRs #29-30) proved world coordinates were valid; the rendering API was the problem.

## Decision

Use **filled geometry** APIs for all user-visible 3D elements:

| Use case | API | Notes |
|----------|-----|-------|
| Brake markers | `render.circle(pos, upDir, radius, col)` | Flat disc on track surface |
| Racing line | `render.quad(v1, v2, v3, v4, col)` | Quad strip, 1m wide |
| Fallback line | `render.glBegin(Quads)` + `glVertex` | If render.quad unavailable |
| Last resort | `render.debugLine` | 1px, barely visible |

## Render state requirements

- `render.setDepthMode(DepthMode.Normal)` — markers occluded by geometry (not visible through walls)
- `render.setBlendMode(BlendMode.AlphaBlend)` — semi-transparent markers
- `render.setCullMode(CullMode.None)` — racing line quads visible from both sides (winding order flips with track curves)
- Always call `csp_helpers.restoreRenderDefaults()` after draw to reset state

## Avoid

- `render.debugLine`, `render.debugSphere`, `render.debugCross` — 1px wireframe, for debugging only
- `render.debugText` — useful for dev but distracting as user-facing markers
- `render.setDepthMode(ReadOnly/Off)` — causes see-through rendering
