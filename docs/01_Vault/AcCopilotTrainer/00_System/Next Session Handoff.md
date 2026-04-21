---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-21
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

- Post-merge steward propagation is prepared on a rollout branch: adds deterministic `post-merge-steward`, `post_merge_sync.sh`, `post_merge_classify.py`, `check_vault_follow_up.sh`, `post-merge-notify.yml`, `vault-automerge.yml`, plus `.claude/settings.json` commit-guard/routing updates. Next action is PR-resolution follow-up on that rollout PR after push.
- **Branch:** `feat/issue-46-ollama-debrief` — **PR #55** (draft): https://github.com/agorokh/ac-copilot-trainer/pull/55 — issue **#46** Ollama debrief + HUD; mark ready when green, then pr-resolution-follow-up (~10 min between polls).
- **Also open:** `feat/issue-49-ai-sidecar-shap` — **PR #54** (issue **#49** ranking / SHAP).
- **Merged:** **#45** / PR #53 (WebSocket v1); **#43** / PR #52 (coaching UX); **#47** journal — confirm PR #51 status on GitHub.
- **Parent #9:** remaining **#44** (focus practice), **#49** (PR #54), **#51** (journal slice — confirm merge), **#19** (Phase 4 — later).

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
