---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-11
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Current focus

**Repo:** ac-copilot-trainer. **Branch:** `fix/issue-75-in-game-smoke-test` (PR #75 open). **Base `main`:** `72be94d` — Issue #72 Phase 5 HUD rebuild merged via PR #73; 186 tests were green on that tip before #75 work.

**Status:** PR #75 stacks CSP runtime fixes, WebSocket sidecar (rules + Ollama follow-up), per-corner `corner_query` / `corner_advice`, HUD diagnostics, and vault investigation nodes on top of the rebuild. Latest commits address review bots (async `corner_query` prepare, `ws_bridge` reconfigure close, task cancellation, protocol edge cases).

**Open gates:** Finish PR #75 review resolution + confirm GitHub Actions CI on the latest branch head after merge-from-main. **In-game smoke test** on Vallelunga + Porsche 911 GT3 R remains the product gate (persistence file already populated so live-frame coaching should fire on first frame after `tryLoadDisk`).

**Next:**

- Land PR #75 (reviews clear, CI green, merge conflicts resolved).
- Re-verify round 10d staleness / sim-time behaviour in-game after merge.
- Threshold tuning in `realtime_coaching.lua` if the smoke test shows the 50/100 m + ±8 km/h bands are off.
- Corner segment quality in `corner_analysis.lua` if brake-to-brake spans are still too long.
- Next epic selection after the smoke test passes (Phase 6 TBD or Phase 4 #19).
