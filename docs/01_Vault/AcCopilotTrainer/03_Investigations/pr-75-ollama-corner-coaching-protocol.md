---
type: investigation
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/03_Investigations/csp-web-socket-api.md
  - AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
---

# PR #75 — Ollama corner coaching protocol

Closed issue #75 on 2026-04-14. 10 rounds of in-game iterative fixes covering CSP runtime compatibility, WebSocket bridge rewrite, `ac.storage` persistence, and **real-time per-corner LLM coaching via Ollama**. This node captures the corner-coaching protocol + pipeline; the CSP runtime findings are already in [`csp-cdata-callable-guards`](csp-cdata-callable-guards.md), [`csp-web-socket-api`](csp-web-socket-api.md), and [`ac-storage-persistence`](ac-storage-persistence.md).

## The pipeline

Sub-550 ms round-trip corner-by-corner coaching. Two-phase response:

1. **Immediate rules-based hint** (<10 ms) — sent back the moment the Lua side dispatches a `corner_query`.
2. **LLM follow-up** (~3–7 s) — same corner ID, enriched response from Ollama. Sent asynchronously via `asyncio.create_task` so the sidecar loop is never blocked.

## Protocol — new message types

Landed as protocol v1 extension (lives alongside the `{v,type}` envelope from PR #83 / issue #81):

### `corner_query` (Lua → sidecar)

```json
{
  "v": 1,
  "type": "corner_query",
  "corner_id": "T4",
  "sim_time": 1234.56,
  "context": {
    "carID": "ks_porsche_911_gt3_r_2016",
    "trackID": "ks_vallelunga_club_circuit",
    "speed_kmh": 142,
    "target_speed_kmh": 95,
    "dist_to_apex_m": 31,
    "current_best_at_apex_kmh": 98,
    "rules_hint": "BRAKE NOW"
  }
}
```

### `corner_advice` (sidecar → Lua)

```json
{
  "v": 1,
  "type": "corner_advice",
  "corner_id": "T4",
  "sim_time": 1234.56,
  "source": "rules" | "ollama",
  "hint": "BRAKE HARD NOW.",
  "body": "Car's still pushing at 142 — brake now and trail off to 95 by the apex. You'll hit the kerb on exit if you over-rotate; stay on the throttle through the rumble strip.",
  "ttl_sim_s": 6.0
}
```

- `source=rules` arrives <10 ms after query. `source=ollama` arrives 3–7 s later for the same `corner_id`.
- `ttl_sim_s` is wall-clock sim-time staleness. After 6 s of sim-time, Lua clears the cached advice from its overlay. This is **sim-time, not `os.clock()` time** — see [`ac-storage-persistence`](ac-storage-persistence.md) for why we use sim clock everywhere.
- Lua dedupes by `corner_id` → keeps the most recent `source=ollama` response, falls back to `source=rules` if the Ollama one never arrives or is stale.

## Smart re-query logic

Lua only fires a new `corner_query` for the same corner if:

- Speed has drifted > 5 km/h from last query's measured speed, OR
- Distance-to-apex has drifted > 20 m from last query's `dist_to_apex_m`, OR
- 6 s of sim-time have elapsed since last query

Prevents spamming Ollama with "hit the same corner on the next lap, same conditions" pings.

## Prompt engineering (server-side `llm_coach.py`)

- `keep_alive=30m` on Ollama API calls — avoids model reload cost between corners.
- Race-car-grounded system prompt (not a generic coach voice).
- **Verb whitelist**: the LLM response is post-filtered to strip any verb not in the allowed set. Drivers at race pace don't want flowery coaching; the whitelist enforces "BRAKE / LIFT / TURN / STAY ON / RELEASE / EASE / PUSH" style.
- Few-shot examples in the prompt showing the expected short-imperative style.
- `compose_corner_hint` (immediate) vs `compose_llm_debrief_only` (async follow-up) — two separate prompts with different length targets.
- Better trimmer strips filler tokens before they reach the Lua overlay.

## Relevance for rig-screen + EPIC #59

The rig screen can subscribe to `corner_advice` frames directly via the external WS hub (PR #83 protocol extension). Two implementation patterns:

1. **Full-passthrough**: screen opens its own WS client connection, joins the hub, receives both `corner_advice` frames + other trainer state. Screen renders the `hint` field on the "Coaching" tile.
2. **Sidecar fan-out subscription**: screen sends `{v:1,type:"state.subscribe",topics:["corner_advice"]}` at hello-time; sidecar filters fan-out per topic.

The full-passthrough path is simpler and was planned in the [`external-ws-client-protocol-extension`](../01_Decisions/external-ws-client-protocol-extension.md) ADR. Fan-out subscription is a future optimization if we have bandwidth issues.

## Files changed (10)

| File | What changed |
|------|-------------|
| `ac_copilot_trainer.lua` | autoPlaceOnce force-resize, per-key storage, Settings VM wiring, RT-DIAG, cornerAdvisories state, windowCoaching cleanup |
| `modules/hud.lua` | cdata-safe guards, safeWindowSize pcall fallback, grey border, HUD-DIAG |
| `modules/coaching_overlay.lua` | cdata-safe guards, OV-DIAG, spacing fix, drawLapDebrief, grey border |
| `modules/coaching_font.lua` | DWriteFont / pushDWriteFont nil-checks |
| `modules/hud_settings.lua` | AI sidecar URL section, approach slider persistence |
| `modules/realtime_coaching.lua` | Tight apex window, keep nextBrake in-corner, approachLabel, corner_query trigger, smart re-query |
| `modules/ws_bridge.lua` | Full rewrite for CSP callback API, reconnect:true, WS-RECV logging, corner_query/corner_advice, currentSimT clock, staleness expiry |
| `tools/ai_sidecar/llm_coach.py` | keep_alive=30m, compose_corner_hint, compose_llm_debrief_only, race-grounded prompt, better trimmer |
| `tools/ai_sidecar/protocol.py` | corner_query handler, build_ollama_followup, non-blocking debrief |
| `tools/ai_sidecar/server.py` | Background Ollama follow-up via asyncio.create_task |

## Test coverage (shipped)

- Lua syntax check (lupa `load()`) on all 7 Lua files
- Python compile check on all 3 Python files
- Synthetic `corner_query` over 6 scenarios, all sub-850 ms round-trip, 6/6 correct
- Synthetic `lap_complete` round-trip: msg #1 in 7 ms, msg #2 in 3195 ms
- Staleness expiry clears stale advice after 6 s sim wall-clock (lupa-tested)
