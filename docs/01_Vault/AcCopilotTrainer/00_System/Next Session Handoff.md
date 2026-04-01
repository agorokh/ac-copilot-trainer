---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-01
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/01_Decisions/csp-api-field-safety.md
  - AcCopilotTrainer/01_Decisions/csp-render-geometry.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **Branch:** `fix/issue-24-marker-polish` — **PR #32** open: https://github.com/agorokh/ac-copilot-trainer/pull/32
- **Issue #24 progression:** PRs #25-#31 merged. PR #32 addresses final visual polish (flat discs, depth occlusion, backface culling).

## What was delivered this session

- **PR #29** (merged): Diagnostic coordinate logging — confirmed world coords are valid (not zero).
- **PR #30** (merged): Enabled diagnostics flag for in-game testing.
- **PR #31** (merged): Replaced 1px debug primitives with real filled geometry (render.circle, render.debugText, render.rectangle, render.quad). Brake markers and racing line became visible for the first time.
- **PR #32** (open): Polish — removed distracting text/rectangle from markers, kept only flat transparent discs. Added depth occlusion (DepthMode.Normal). Fixed racing line gaps via CullMode.None. Reset cull mode in restoreRenderDefaults.

## Key findings this session

- **render.debug* primitives are 1px wireframes** — invisible from cockpit at driving distance. Must use render.circle, render.quad, render.rectangle for visible 3D markers. See ADR: `01_Decisions/csp-render-geometry.md`.
- **Backface culling breaks quad strips** — track curves flip winding order; CullMode.None required for racing line quads.
- **Depth mode matters** — DepthMode.ReadOnly or Off causes markers to render through all geometry. Use DepthMode.Normal for proper occlusion.
- **Coordinates were valid all along** — diagnostic logging (PRs #29-30) proved px/py/pz are correct; the rendering API choice was the problem.

## What remains

- Merge PR #32, test in-game: flat discs visible, no see-through, continuous racing line.
- If confirmed: close #24 and move to epic work.
- **Known bugs:** coast time in throttle analysis shows ~1000+ seconds (accumulation bug). Separate issue.
- **Racing line source:** currently best-lap trace only. User wants best-segment composite (future issue).

## Blockers

- Assetto Corsa + CSP runtime required for visual validation.
