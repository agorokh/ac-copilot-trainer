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

- **Branch:** `feat/issue-7-track-markers-delta` — implements GitHub **#7** (traces, delta, sectors, 3D markers, throttle, post-lap HUD).
- **PR #20:** https://github.com/agorokh/ac-copilot-trainer/pull/20 — **Fixes #7**, ready; **required CI** (build + Canonical docs) **green** on latest SHA; **Cursor Bugbot** completed **SUCCESS**; **GraphQL `reviewThreads`**: **zero unresolved** after **600s** post-push poll (2026-03-31, head `75ab14a`).
- **PR-resolution fixes shipped (this pass):** persist **`bestReferenceLapMs`** with **`bestLapTrace`** (no blanking trace on disk when PB improves but span guard kept prior trace); load **`bestReferenceLapMs`** in **`applyLoaded`**; **`traceHasPbSplineCoverage`** before promoting PB reference trace; **`interpAtSpline`** nil-safe numeric endpoints; **track_markers**: spline in **brakeListHash**, **snapY** max keys, **%.3f** cache keys, **pcall** for **hit.position.y**, numeric guards in **addList**.
- **Earlier PR #20 fixes (still relevant):** prime **lastLapCount** / **beginLapClock**; span guard for **bestLapTrace**; persistence **version** + **bestLapTrace** coerce; **analyzeTrace** + **eMs**; approach HUD spline + track length; **FT%** time-based; delta bar symmetric rounding.
- **Windows tools:** if `gh` / `git` are missing from PATH, use `C:\Program Files\GitHub CLI\gh.exe` and `C:\Program Files\Git\bin\git.exe`. Verify issue **#7** is **OPEN** before merge (`gh issue view 7 --repo agorokh/ac-copilot-trainer`).
- **#6:** assumed merged on `main` before this branch (telemetry/brake/HUD foundation).

## What was delivered this session

- **Part A:** `telemetry.lua` — per-lap trace buffer, `finalizeLapTrace()` with ≤2000 samples; raw cap + intermediate downsample.
- **Part B:** `delta.lua` — sorted-spline interpolation, live delta + ~30-sample smoothing; HUD bar (ASCII) + numeric.
- **Part C:** Three spline sectors; messages at boundaries vs reference lap sector times.
- **Part D:** `track_markers.lua` — best=green, last=yellow, ≤50 primitives, 200m fade; `render.debugSphere` / `drawSphere` in `pcall`; optional `physics.raycastTrack` for Y snap (API varies).
- **Part E:** Approach panel when within 200m of nearest **best** brake (distance, ref speed from trace, current speed).
- **Part F:** `throttle_detection.lua` — live coast streak + warning; post-lap trace analysis (FT%, coasting ms, throttle-on count, sawtooth reversals).
- **Part G:** Post-lap panel ~5s — brake deltas vs previous best + coasting line from throttle analysis.
- **Persistence v2:** `bestLapTrace` JSON alongside brakes; `manifest.ini` **RENDER_CALLBACKS TRANSPARENT=Draw3D**, app **0.2.0**.

## What remains

- Human/agent: **await approval** on PR `#20`; **merge** when approved (re-run **pr-resolution-follow-up** if new inline threads appear after push).
- In-game: confirm CSP **Draw3D** + **`render.debugSphere`** on your CSP build; if markers invisible, adjust API per acc-lua-sdk and follow up.
- Optional: per-sector PB coloring (purple) if we persist best sector splits separately.

## Blockers

- None in repo; runtime verification needs Assetto Corsa + CSP.
