---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-03-30
issue: "https://github.com/agorokh/ac-copilot-trainer/issues/6"
pr: "https://github.com/agorokh/ac-copilot-trainer/pull/10"
branch: "feat/issue-6-telemetry-brake-persistence"
relates_to:
  - ProjectTemplate/00_System/Next Session Handoff.md
  - ProjectTemplate/00_System/Project State.md
  - ProjectTemplate/00_System/invariants/_index.md
  - ProjectTemplate/01_Decisions/local-reviewer-model.md
---

# Current focus

**Repo:** ac-copilot-trainer. **Issue #6:** telemetry engine, brake point detection, JSON persistence, lap promotion of brake sets, ImGui HUD — implemented under `src/ac_copilot_trainer/` (pending PR).

**Branch:** `feat/issue-6-telemetry-brake-persistence`. **PR:** https://github.com/agorokh/ac-copilot-trainer/pull/10 (draft, `Fixes #6`).

**Next:** wait for Actions + bots (`sleep 600` after pushes), GraphQL `reviewThreads`; then `gh pr ready 10` when you want full review signal; in-game smoke test after copying the app folder into `assettocorsa/apps/lua/ac_copilot_trainer/`.
