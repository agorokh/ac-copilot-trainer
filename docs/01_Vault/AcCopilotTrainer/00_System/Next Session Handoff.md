---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-07
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/glossary/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **PIVOT (user directive, end of this session):** Post-lap debrief ("LAP suggestions") is NOT wanted — Track Titan already does that and we're duplicating their work. The user wants **in-race / real-time per-corner LLM coaching** delivered WHILE DRIVING, keyed to the upcoming corner. **Round 9 `drawLapDebrief` should be removed or repurposed.** The round 8 sidecar plumbing (non-blocking, reconnect=true, WS-RECV logging, follow-up pipeline) is keeper infrastructure and should be kept.
- **On `main` (`72be94d`), with 9 rounds of uncommitted patches.** Rounds 1-8 delivered window visibility, persistent settings, CSP web.socket callback-API rewrite, and a proven-working non-blocking sidecar with `reconnect=true` that holds sockets open across the Ollama call window. Round 9 added `keep_alive=30m` to Ollama calls (cut latency 6.8s → 3.2s, PROVEN via `.scratch/e2e_test_round8.py`), `compose_llm_debrief_only()` that returns None on true LLM failure (so follow-up no longer fake-sends rules as "ollama"), and `drawLapDebrief` render in WINDOW_1 during post-lap hold **which the user has now rejected as scope**.

## Round 10 plan (PIVOT — in-race per-corner advisories)

**Architecture:** Ollama runs ONCE per lap completion (in the existing background follow-up task), generates per-corner advisories as JSON `{"T1": "brake 5m later", "T2": "carry more mid-corner", ...}`, Lua stores them in `state.cornerAdvisories[label]`. The realtime engine (`realtime_coaching.lua`) reads `state.cornerAdvisories[topCornerLabel]` and uses it as `view.secondaryLine` for the TOP tile when approaching or inside that corner. Each new lap refreshes the advisories with the freshest telemetry → LLM advice is always one lap old, which is the freshest we can get given Ollama's ~3s response time.

**Changes required:**

1. `tools/ai_sidecar/coaching/llm_coach.py`:
   - New `compose_corner_advisories_only(inbound, imp) -> dict[str, str] | None` — prompts Ollama for strict JSON output keyed by corner label (e.g. `T1`, `T2`), 8-word max per value. Extract per-corner telemetry facts from `inbound.telemetry.corners` and include in the prompt. Parse the response as JSON, validate keys match the lap's corner labels, return dict or None on failure.
2. `tools/ai_sidecar/protocol.py` `build_ollama_followup`:
   - Call `compose_corner_advisories_only` INSTEAD of `compose_llm_debrief_only`.
   - Emit `coaching_response` with new field `cornerAdvisories: {T1: "...", T2: "...", ...}`. Drop the `debrief` field from the follow-up.
3. `src/ac_copilot_trainer/modules/ws_bridge.lua` `pollInbound`:
   - Parse `data.cornerAdvisories` as a table keyed by label string.
   - Store in a new `pendingCornerAdvisories` module field alongside `pendingCoaching`.
   - Expose `M.takeCornerAdvisories()` for the entry script.
4. `src/ac_copilot_trainer/ac_copilot_trainer.lua`:
   - New `state.cornerAdvisories = {}` field cleared on track reset.
   - In `script.update`, after `takeCoachingForLap`, also call `wsBridge.takeCornerAdvisories()` and merge into `state.cornerAdvisories`.
5. `src/ac_copilot_trainer/modules/realtime_coaching.lua` `tick`:
   - Read `opts.cornerAdvisories` passed from the entry script.
   - If `topCornerLabel` is set and `cornerAdvisories[topCornerLabel]` exists, OVERRIDE `view.secondaryLine` with the LLM advice for that corner.
6. **Remove or demote `coachingOverlay.drawLapDebrief`** and `script.windowCoaching` post-lap debrief swap. The TOP tile always shows live coaching (with or without per-corner LLM override); the BOTTOM tile always shows live approach data.

## What was delivered this session (rounds 6-9) — DON'T LOSE THIS WORK

- **Round 6:** `ws_bridge.lua` rewritten for CSP callback-based `web.socket(url, callback, params)` signature. Fixed `Callback should be a function` error. **KEEPER.**
- **Round 7:** Killed orphaned sidecar, fresh env-var propagation via `export`. **KEEPER (operational).**
- **Round 8 Python (PROVEN):** Non-blocking sidecar — `prepare_outbound_message` returns rules-debrief only in <10ms, `_send_ollama_followup` background task sends a second `coaching_response` when Ollama completes. **KEEPER — this is the foundation for per-corner advisories in round 10.**
- **Round 8 Lua (PROVEN in-game via `[WS-RECV]` log lines user saw):** `reconnect=true`, verbose `_onRecv` logging, `pollInbound` handles `debriefSource` follow-ups. **KEEPER.**
- **Round 9 Python (PROVEN via e2e test, MSG #1 6ms + MSG #2 3195ms):** `keep_alive="30m"` baked into every Ollama call (cut latency from 6.8s to 3.2s), `compose_llm_debrief_only` returns None on real LLM failure. **KEEPER.**
- **Round 9 Lua (`drawLapDebrief` + windowCoaching swap):** **USER REJECTED.** Remove in round 10 — don't want post-lap text blob, want in-race per-corner overrides instead.

## What remains

- **Round 10 per-corner advisories** — implement the 6 changes listed above. Expected to produce an "in-race" experience where the user sees fresh, corner-specific LLM advice as the TOP tile's secondary line when approaching each corner, refreshed every lap.
- **Branch + PR** — once round 10 works in-game, batch rounds 1-10 into one large PR with careful commit message narrative.
- **Racing line "Reset PB" button** — optional, still outstanding.
- **Settings WINDOW_2 FADING flag** — still outstanding.

## Blockers / dependencies

- **Active in-game test required.** User reloads AC and drives 2 laps; I grep CSP log for `[WS-RECV]` #2 with `cornerAdvisories` field.
- **Sidecar state:** PID **10796** on 8765 (round 9 sidecar). `keep_alive=30m` baked in, `DEBRIEF_TIMEOUT_SEC=60`. E2E test proved 6ms+3.2s round trip.

## Failure protocol notes

- **Round 9 post-lap debrief rejected by user** — not a technical failure, a scope correction. The plumbing work (non-blocking sidecar, reconnect=true, keep_alive) is fully reusable for round 10.
- **Env var propagation on Windows MSYS:** must `export VAR=value && python -m X`, NOT `VAR=value python -m X`. Orphaned processes can keep ports bound silently.
- **Round 8 `[WS-RECV] #2 (544 bytes)` arrived in-game, proving reconnect=true holds the socket.** That was the critical round-trip verification.
