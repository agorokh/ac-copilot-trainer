---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-03-28
relates_to:
  - ProjectTemplate/00_System/Current Focus.md
  - ProjectTemplate/00_System/Project State.md
  - ProjectTemplate/00_System/invariants/_index.md
  - ProjectTemplate/00_System/glossary/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **#21 / Tier 1+2:** branch `feat/issue-21-repo-intelligence`, **PR:** https://github.com/agorokh/template-repo/pull/30 (draft). Hand off to **`pr-resolution-follow-up`** until checks + review threads are clean.
- **PR #29** (#15): if still open, merge when maintainer is satisfied (separate line of work).
- **#26** remains blocked on #21 training-data readiness; **#27** template sync is the parallel track if #21 is done.

## What was delivered

- **#21 (in flight):** `tools/process_miner/` + `scripts/process_miner.py`, optional extras `[mining]` / `[knowledge]`, learned rules dirs, `.github/workflows/process-miner.yml`, `tools/repo_knowledge/` + MCP wiring in `.mcp.json` / `.cursor/mcp.json`, structure doc + `check_agent_forbidden` updates, CI installs `dev+mining+knowledge` for coverage.
- #15 scope (prior): orchestration/`learner`/hooks/MCP pin/CI gates — **PR:** https://github.com/agorokh/template-repo/pull/29

## What remains

- Land **#21** PR (draft → review → merge) and sanity-check weekly miner workflow (`workflow_dispatch`) on GitHub.
- Merge **#29** for #15 if still open when ready.
- **#26** after stable miner outputs; **#27** Copier/template sync still separate.

## Blockers

- None. If Stop hook `timeout: 60000` behaves incorrectly in Claude Code (seconds vs ms), confirm against upstream hook docs and adjust.
