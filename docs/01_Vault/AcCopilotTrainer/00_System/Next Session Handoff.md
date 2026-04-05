---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-05
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/01_Decisions/deep-research-synthesis.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/glossary/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **Issue #57 Phase 5 Part B:** branch `feat/issue-57-phase5-part-b` — **PR #60** (draft): https://github.com/agorokh/ac-copilot-trainer/pull/60 — Settings window (WINDOW_2); mark ready when green; Parts C–E still on #57.
- **Branch:** `feat/issue-46-ollama-debrief` — **PR #55** (draft): https://github.com/agorokh/ac-copilot-trainer/pull/55 — issue **#46** Ollama debrief + HUD; mark ready when green, then pr-resolution-follow-up (~10 min between polls).
- **Also open:** `feat/issue-49-ai-sidecar-shap` — **PR #54** (issue **#49** ranking / SHAP).
- **Merged:** **#45** / PR #53 (WebSocket v1); **#43** / PR #52 (coaching UX); **#47** journal — confirm PR #51 status on GitHub.
- **Parent #9:** remaining **#44** (focus practice), **#49** (PR #54), **#51** (journal slice — confirm merge), **#19** (Phase 4 — later).

## What was delivered this session

- **Issue #57 Part B (PR #60):** `manifest.ini` WINDOW_2 Settings; `hud_settings.lua`; main HUD slimmed; `Draw3D` gated by `racingLineEnabled` / `brakeMarkersEnabled`; `tests/test_manifest_phase5.py`.
- **Issue #46 (PR #55):** `tools/ai_sidecar/coaching/llm_coach.py`; optional `debrief` on `coaching_response`; `AC_COPILOT_OLLAMA_*` env (see WARP / `.env.example`); Lua `telemetry.corners` on `lap_complete`, HUD + Coaching debrief UI, `sidecar_debrief_last` in journal; `tests/test_llm_coach.py` (mocked HTTP).
- **Issue #49 (PR #54):** `features.py` / `improvement_ranking.py` / `session.py`; optional `improvementRanking` on `coaching_response`; `--compare-laps`; `[coaching]` adds numpy/sklearn/shap; tests + fixtures + protocol doc.
- **Issue #45 (merged):** `tools/ai_sidecar/protocol.py` + extended `server.py` (`--no-reply`, `analysis_error` on bad JSON); `ws_bridge.lua` inbound queue + `takeCoachingForLap`; `ac_copilot_trainer.lua` `protocol:1` on `lap_complete` and sidecar override; `tests/test_ai_sidecar_protocol.py`; `12_WS_Sidecar_Protocol.md` + WARP; `websockets` added to `dev` optional deps for CI.
- **PR #52 (merged):** Issue #43 — coaching max visible hints + contract tests + WARP.
- **PR #51:** Phase 3 journal slice for epic #9 — `session_journal.lua` writes schema v1 JSON under `ScriptConfig/ac_copilot_trainer/journal/` when returning to AC main menu after ≥1 lap and successful persist; append-only `journal_index.jsonl` via `persistence.encodeJsonCompact`. `persistence.encodeJson` / `ensureParentDirForFile` exposed. Doc `docs/10_Development/11_Session_Journal_Schema.md`; Python `tools/session_journal.py` + tests.

## What remains

- **#9 epic:** ML ranking (#49 in PR #54), focus practice (#44); Ollama debrief (#46) in PR #55; WebSocket (#45) merged; coaching UX (#43) merged.
- **In-game check:** Confirm journal files appear on disk after menu exit (AC + CSP).

## Blockers / dependencies

- **Assetto Corsa + CSP runtime** for end-to-end journal verification; CI covers Python schema + repo checks only.
