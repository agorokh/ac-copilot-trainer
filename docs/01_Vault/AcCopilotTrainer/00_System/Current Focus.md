---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-08
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Current focus

**Repo:** ac-copilot-trainer. **Branch:** `fix/issue-75-in-game-smoke-test` (`57ed33b`). **Draft PR #75 open.**

**Status:** 10 rounds of in-game iterative fixes applied. Both HUD windows render, live-frame cascade fires correctly (APPROACHING / BRAKE NOW / CARRY MORE SPEED / EASE OFF / ON PACE), per-corner real-time LLM coaching via Ollama at sub-550ms, WebSocket bridge fully rewritten for CSP callback API, per-key ac.storage persistence for sidecar URL and approach distance.

**Open gate:** Round 10d staleness expiry (currentSimT clock fix) unverified in-game. PR #75 awaiting code review + CI checks.

**Next:**
- Resolve PR #75 review comments, get CI green, merge
- Verify round 10d staleness expiry in-game after merge
- Fix corner_analysis.lua segment quality (brake-to-brake spans too long)
- LLM coaching prompt tuning with real driving data
- Next epic selection (Phase 6 TBD or Phase 4 #19)
