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

- **Branch:** `feat/issue-8-corner-analysis-phase2` — GitHub **#8** (corner segmentation, ML-oriented features, consistency, style divergence stub, `fast_lane.ai` reader, racing line strip, tires, setup snapshot).
- **PR:** open with **`Fixes #8`**; after push use `gh pr view --repo agorokh/ac-copilot-trainer --json number,url,headRefOid`.
- **Follow-up:** run **pr-resolution-follow-up** (GraphQL `reviewThreads` full pagination, **600s** bot cooldown); merge when CI green and threads resolved.
- **Persistence:** JSON **v3** (`persistence.lua`): `trackSegments`, `lapFeatureHistory`, `setupHash`, `setupSnapshot`, `bestCornerFeatures` (plus existing v2 fields).
- **Deferred (issue #8):** in-app K-means/DBSCAN; confirmed CSP setup auto-apply API for Part I; tune `spline_parser` stride/XYZ offset per real `fast_lane.ai` variants.
- **Windows:** `C:\Program Files\GitHub CLI\gh.exe`, `C:\Program Files\Git\bin\git.exe`; local **ci-fast** without bash: `ruff` + `pytest` + `bandit` + `check_agent_forbidden.py` (policy script needs bash/Git Bash).

## What was delivered this session

- New modules: `corner_analysis.lua`, `spline_parser.lua`, `racing_line.lua`, `tire_monitor.lua`, `setup_reader.lua`; wired in `ac_copilot_trainer.lua`; HUD + `Draw3D` overlays; telemetry lap trace includes **steer** for corner features.
- App **0.3.0** (`manifest.ini` + HUD banner).

## What remains

- Mark PR **ready**, wait for CI, resolve review threads.
- In-game: validate `render.line` / `vec3` on target CSP; validate `fast_lane.ai` parse layout for your tracks.

## Blockers

- None in repo; runtime verification needs Assetto Corsa + CSP.
