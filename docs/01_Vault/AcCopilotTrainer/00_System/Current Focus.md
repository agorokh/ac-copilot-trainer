---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-07
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
---

# Current focus

**Repo:** ac-copilot-trainer. **Branch:** `main` (`72be94d`), **9 rounds of uncommitted in-game patches** in `src/ac_copilot_trainer/` and `tools/ai_sidecar/` (rounds 1-9).

**Major pivot at end of session:** user rejected post-lap debrief ("Track Titan already does it, we want in-race per-corner LLM coaching, sub-1-second latency"). Round 9 `drawLapDebrief` render is scrapped; round 10 replaces it with a `corner_query` / `corner_advice` WebSocket event pair that fires when the realtime engine detects `topCornerLabel` transitions.

**Status:**

- **Sub-1-second LLM latency PROVEN** with `llama3.2:3b` + `keep_alive=30m` + small prompt + `num_predict=20`: **631 ms round trip** (direct curl test). Example: prompt `"T1 approach 200m: you 140km/h target 149km/h. 1 short hint (max 6 words):"` → response `"Reduce speed by 9 km/h."`.
- **Round 8 WS infrastructure verified in-game** via `[COPILOT][WS-RECV]` log lines the user saw: `reconnect=true` holds sockets, non-blocking sidecar sends immediate rules response in 6ms, background Ollama follow-up sends second message in 3.2s.
- **llama3.2:1b pulling in background** (task `bzxiieqir`, ~21% at session end, ~75s remaining). Will cut per-corner latency further to ~300-400 ms. Not blocking round 10 since 3b already hits sub-1s.
- **Sidecar PID 10796** running on `ws://127.0.0.1:8765` with round 9 code (`keep_alive` baked into `llm_coach.py`, `DEBRIEF_TIMEOUT_SEC=60`).

**Single open task:** **Round 10 implementation** — the in-race per-corner architecture. NOT started this session, awaiting user go-ahead. 6-step plan documented in `Next Session Handoff.md`. Expected ~150 lines across 5 files (`tools/ai_sidecar/protocol.py`, `tools/ai_sidecar/server.py`, `tools/ai_sidecar/coaching/llm_coach.py`, `src/ac_copilot_trainer/modules/ws_bridge.lua`, `src/ac_copilot_trainer/modules/realtime_coaching.lua`).

**Next (trigger word: "go round 10"):**

1. Delete `drawLapDebrief` from `coaching_overlay.lua` and the `windowCoaching` debrief swap in `ac_copilot_trainer.lua`.
2. Add `event: "corner_query"` handler in `protocol.py` and `build_corner_advice_response()` that calls new `compose_corner_hint(corner, cur, ref, dist)` in `llm_coach.py` (tiny prompt, num_predict=20, keep_alive=30m).
3. Add `wsBridge.sendCornerQuery(corner, cur, ref, dist)` + `takeCornerAdvisory(label)` in Lua.
4. Trigger `sendCornerQuery` from `realtime_coaching.tick()` when `topCornerLabel` changes (debounced, one per corner per approach).
5. Store advice in `state.cornerAdvisories[label]`; use as `view.secondaryLine` override in the TOP tile.
6. E2E Python test first (expect ~631 ms round trip), then user reload + drive.

**Blockers:** None technical. Waiting on user's explicit "go" for round 10. All round 1-9 patches uncommitted.
