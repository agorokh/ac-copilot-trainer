---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-11
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/glossary/_index.md
  - AcCopilotTrainer/03_Investigations/csp-web-socket-api.md
  - AcCopilotTrainer/03_Investigations/csp-cdata-callable-guards.md
  - AcCopilotTrainer/03_Investigations/ac-storage-persistence.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **Branch `fix/issue-75-in-game-smoke-test` — PR #75** implements the in-game smoke-test gate and CSP/sidecar fixes on top of **`main` @ `72be94d`** (PR #73 Phase 5 HUD rebuild merged).
- **Top priority:** clear remaining PR #75 review threads, confirm Actions **CI** + **Policy** runs on the latest pushed SHA, then merge when GitHub shows a clean merge (no conflicts).
- **`main` context:** Issue #57 / #66 / #69 / #72 are closed; the only product gate called out on `main` was the **in-game smoke test** of PR #73 — PR #75 is the active branch carrying fixes and tests toward that gate.
- **Round 10d staleness** (`currentSimT` vs `os.clock`) should be re-checked in-game after the PR lands.

## What was delivered this session

- **On `main` (pre-#75):** PR #73 — live-frame coaching engine, bundled fonts, FIXED_SIZE windows, ETE tests in `tests/test_phase5_rebuild_ete.py`, review-resolution rounds documented in prior handoff.
- **On PR #75:** Multi-round in-game-driven fixes — CSP cdata-callable guards, `web.socket` callback bridge, per-key `ac.storage`, AI sidecar + `corner_query` / `corner_advice`, bounded Ollama follow-ups, server-side async prepare for `corner_query` with lock serialization against `lap_complete`, `ws_bridge.configure` closing the previous socket, HUD/footer debrief wiring, and expanded protocol tests (191 tests passing locally on branch tip).

## What remains

- Merge **origin/main** into PR #75 (or rebase), resolve vault/doc conflicts, push, and wait for CI on the new head.
- **In-game smoke test** — both windows, BRAKE NOW / PREPARE / CARRY MORE SPEED / EASE OFF from live-frame inputs, drag without breaking FIXED_SIZE recovery (132×456), sidecar URL persistence, per-corner advice where enabled.
- Optional: threshold tuning, corner segment quality, LLM prompt tuning from real laps.
- Next epic after smoke test passes.

## Blockers / dependencies

- None technical beyond finishing merge + CI on the integration head.

## Key learnings (see investigation nodes)

1. CSP cdata-callable: `type(vec2)` is `"cdata"` not `"function"` — use nil-checks before invoking.
2. CSP `web.socket`: callback-based API; `sock(data)` to send; `reconnect: true` where supported.
3. `ac.storage` table form can fail silently — use per-key `ac.storage("name", default)`.
4. `os.clock()` in AC Lua is not wall time for low-CPU scripts — use sim time (e.g. `sim.gameTime`) for staleness.
5. Ollama: pass `keep_alive` on generate calls as required by your deployment.
