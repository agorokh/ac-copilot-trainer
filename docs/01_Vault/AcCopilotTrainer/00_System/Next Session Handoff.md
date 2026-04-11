---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-08
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

- **On branch `fix/issue-75-in-game-smoke-test` (`57ed33b`), draft PR #75 open.** 12 files changed, 1048 insertions. Waiting for code review bots + CI checks.
- **Top priority:** resolve code review comments on PR #75, then merge.
- **Round 10d staleness expiry still unverified in-game.** The os.clock() to currentSimT fix is committed but the user has not reloaded to test it.

## What was delivered this session

- **10 rounds of iterative in-game fixes** for Phase 5 HUD rebuild smoke test (rounds 1-10, see PR #75 body for details)
- **Ollama integration fully wired:** llama3.2:3b + llama3.2:1b pulled, sidecar on ws://127.0.0.1:8765, per-corner real-time LLM coaching at sub-550ms
- **AI sidecar Settings UI:** URL input + Set/Clear buttons, persisted via per-key ac.storage

## What remains

- PR #75 code review + CI green
- Round 10d in-game verification (staleness expiry)
- Corner segment quality fix in corner_analysis.lua (brake-to-brake spans too long)
- LLM coaching quality tuning (prompt edge cases)
- Post-lap debrief rendering (drawLapDebrief exists but not wired)
- Next epic selection after PR #75 merges

## Blockers / dependencies

- None blocking.

## Key learnings (see investigation nodes)

1. CSP cdata-callable: type(vec2) is "cdata" not "function" -- use nil-checks
2. CSP web.socket: callback-based, sock(data) to send, reconnect:true required
3. ac.storage table-form: silently fails; use per-key ac.storage("name", default)
4. os.clock() in Lua: process CPU time, not wall-clock; use sim.gameTime
5. Ollama keep_alive: must pass in every /api/generate call, not just warmup
