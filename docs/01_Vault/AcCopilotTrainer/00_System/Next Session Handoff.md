---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-03-30
relates_to:
  - ProjectTemplate/00_System/Current Focus.md
  - ProjectTemplate/00_System/Project State.md
  - ProjectTemplate/00_System/invariants/_index.md
  - ProjectTemplate/00_System/glossary/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **#6 (ac-copilot-trainer):** Telemetry + brake detection + JSON persistence + lap-aware best/last brake sets + ImGui HUD. **Branch:** `feat/issue-6-telemetry-brake-persistence`. **PR:** https://github.com/agorokh/ac-copilot-trainer/pull/10 (draft, `Fixes #6`). Next: wait for CI; **`sleep 600`** after any push; GraphQL `reviewThreads`; `gh pr ready 10` when you want reviewers/bots notified; then merge when green.
- **#11 Cursor Task delegation:** branch `feat/issue-11-cursor-task-delegation`, **PR:** https://github.com/agorokh/template-repo/pull/34 (`Fixes #11`, ready). **pr-resolution-follow-up (2026-03-30):** required checks green on the **current PR HEAD** (re-check in GitHub before merge); GraphQL `reviewThreads`: no blocking unresolved threads (full pagination audit). Next: human approval / merge if branch rules require it.
- **#27 template sync:** branch `feat/issue-27-template-sync`, **PR:** https://github.com/agorokh/template-repo/pull/32 (draft, `Refs #27`). **`pr-resolution-follow-up` done (2026-03-29):** required checks green on latest SHA; Cursor Bugbot **SUCCESS**; GraphQL `reviewThreads` has **zero** unresolved threads. Next: human review / mark ready / merge when satisfied. Epic #14 stays open until tracker closed.
- **#26 Phase 1:** branch `feat/issue-26-model-training-phase1`, **PR:** https://github.com/agorokh/template-repo/pull/31 (draft). **`pr-resolution-follow-up` done (2026-03-29):** required checks green on latest SHA; GraphQL `reviewThreads` has **zero** unresolved threads. Next: human review / mark ready / merge when satisfied. Epic #26 stays open (Phases 2–4 deferred).
- **#21 / Tier 1+2:** branch `feat/issue-21-repo-intelligence`, **PR:** https://github.com/agorokh/template-repo/pull/30 (draft). Hand off to **`pr-resolution-follow-up`** until checks + review threads are clean.
- **PR #29** (#15): if still open, merge when maintainer is satisfied (separate line of work).

## What was delivered

- **#6 (repo workspace, pending PR):** `src/ac_copilot_trainer/modules/{telemetry,brake_detection,persistence,hud}.lua`, rewired `ac_copilot_trainer.lua`, `manifest.ini` (`LAZY=PARTIAL`, `FUNCTION_MAIN` / `FUNCTION_ON_HIDE`). CI hygiene: `Makefile` pytest `--cov=ac_copilot_trainer`, `tests/test_smoke.py` import fix, `pyproject.toml` dev extra includes `requests`. **Issue:** https://github.com/agorokh/ac-copilot-trainer/issues/6
- **#11 (in PR):** `.cursor/rules/cursor-task-delegation.mdc`, `CLAUDE.md` / `.cursorrules` / `AGENTS.md` / `.claude/rules/orchestration.md` + agent markdown alignment for Cursor `Task` enum. **PR:** https://github.com/agorokh/template-repo/pull/34
- **#27 (in PR):** `copier.yml`, `scripts/copier_post_copy.py`, reference workflows `template-sync.yml` / `template-feedback.yml` / `cross-repo-mining.yml`, `tools/process_miner/aggregate.py` + tests, `[bootstrap]` optional extra, docs (BOOTSTRAP, MAINTAINING, WARP, `.env.example`), learner upstream subsection. **PR:** https://github.com/agorokh/template-repo/pull/32
- **#26 Phase 1 (in PR):** `tools/model_training/` — `data_pipeline` + `format_sft` export to `sft_pairs.jsonl` / `sft_decisions.jsonl`, `dataset_stats.py`, stub `format_dpo` / `format_cpt`, `config/*.yaml`, tests, `models/` gitignore, vault `01_Decisions/local-reviewer-model.md`. **PR:** https://github.com/agorokh/template-repo/pull/31
- **#21 (in flight):** `tools/process_miner/` + `scripts/process_miner.py`, optional extras `[mining]` / `[knowledge]`, learned rules dirs, `.github/workflows/process-miner.yml`, `tools/repo_knowledge/` + MCP wiring in `.mcp.json` / `.cursor/mcp.json`, structure doc + `check_agent_forbidden` updates, CI installs `dev+mining+knowledge` for coverage.
- #15 scope (prior): orchestration/`learner`/hooks/MCP pin/CI gates — **PR:** https://github.com/agorokh/template-repo/pull/29

## What remains

- Land **#32** for #27 (review/merge when satisfied); epic #14 remains until closed.
- Land **#31** for #26 Phase 1; epic #26 remains open for training loop (Phase 2), integration (Phase 3), continuous loop (Phase 4).
- Land **#21** PR (draft → review → merge) and sanity-check weekly miner workflow (`workflow_dispatch`) on GitHub.
- Merge **#29** for #15 if still open when ready.

## Blockers

- None. If Stop hook `timeout: 60000` behaves incorrectly in Claude Code (seconds vs ms), confirm against upstream hook docs and adjust.
