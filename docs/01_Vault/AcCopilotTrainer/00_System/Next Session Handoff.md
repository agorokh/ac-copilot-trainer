---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-03-30
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
- **PR #20:** https://github.com/agorokh/ac-copilot-trainer/pull/20 — **Fixes #7**, ready; **required CI** (build + Canonical docs) **green** on latest SHA; **GraphQL `reviewThreads`** showed **no unresolved** threads after the last **600s** post-push poll (2026-03-30). Cursor Bugbot may still show **IN_PROGRESS** in the rollup; resolve again if it leaves new threads.
- **PR-resolution fixes shipped:** lap trace clock only at start/finish (no mid-lap arm); do not overwrite disk **bestLapTrace** with an empty finalized trace on first-lap PB; approach HUD uses forward spline + **track length** for meters when available; **FT%** from elapsed time; live throttle detector trimmed; **delta** bar symmetric rounding; **track_markers** snap cache + safe **userdata** read; redundant **wasBraking** branch removed.
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
