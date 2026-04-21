# PR #78 — Comment ledger (full inventory, zero sampling)

Watermark (last pushed commit before this document update): see git `HEAD` at push time.

## Inline review comments (23) — `GET /repos/.../pulls/78/comments`

| ID | Author | File | Resolution |
|----|--------|------|------------|
| 3114511556 | gemini-code-assist | lap_archive.lua | RESOLVED — `stats()` TTL cache (2s) + bust on write |
| 3114511559 | gemini-code-assist | lap_archive.lua | RESOLVED — rotate throttled every N writes (prior commit) |
| 3114511561 | gemini-code-assist | start_sidecar.bat | RESOLVED — `%~dp0..\..` REPO_ROOT (prior commit) |
| 3114511563 | gemini-code-assist | ac_copilot_trainer.lua | RESOLVED — `isLapInvalidated` ORed (prior commit) |
| 3114515719 | sourcery-ai | ws_bridge.lua | RESOLVED — check `runConsoleProcess` return; `spawnedAlive` only on success |
| 3114515722 | sourcery-ai | lap_archive.lua | RESOLVED — `traceToColumns` iterates `TRACE_FIELDS` |
| 3114515728 | sourcery-ai | hud_settings.lua | RESOLVED — clamp via `lapArchive.clampArchiveCapMB` + normalize cfg |
| 3114521845 | chatgpt-codex-connector | ac_copilot_trainer.lua | RESOLVED — migrate empty per-key URL to default + persist |
| 3114521847 | chatgpt-codex-connector | ws_bridge.lua | RESOLVED — `M.reset()` clears `lastLaunchAttemptT` |
| 3114521894 | cursor | lap_archive.lua | RESOLVED — `persistence.dataDir().."/journal/laps"` (not missing API) |
| 3114521895 | cursor | ac_copilot_trainer.lua | RESOLVED — same URL migration as Codex |
| 3114522448 | Copilot | ac_copilot_trainer.lua | RESOLVED — empty stored URL migration |
| 3114522470 | Copilot | ac_copilot_trainer.lua | RESOLVED — removed dead `state.sessionUuid` |
| 3114522484 | Copilot | ws_bridge.lua | RESOLVED — docstring matches `sock ~= nil` semantics |
| 3114522493 | Copilot | ws_bridge.lua | RESOLVED — comment documents `spawnedAlive` only (no PID) |
| 3114522505 | Copilot | lap_archive.lua | RESOLVED — flattenSetupSnapshot comment matches `{section,key,value}` |
| 3114522515 | Copilot | lap_archive.lua | RESOLVED — same as RC-3114521894 (`dataDir`) |
| 3114525805 | coderabbitai | ac_copilot_trainer.lua | RESOLVED — removed `sessionUuid` field |
| 3114525810 | coderabbitai | hud_settings.lua | RESOLVED — write clamped capMB back when divergent |
| 3114525815 | coderabbitai | lap_archive.lua | RESOLVED — honor `opts.car` / `opts.sim` for ids |
| 3114525820 | coderabbitai | lap_archive.lua | RESOLVED — rotate deletes when size unknown + ~250KB fallback |
| 3114525824 | coderabbitai | start_sidecar.bat | RESOLVED — CRLF + `.gitattributes` `*.bat text eol=crlf` |
| 3114525826 | coderabbitai | start_sidecar.bat | RESOLVED — `py -3` then fallback `python` on failure |

## Issue conversation comments (3) — `GET /repos/.../issues/78/comments`

| ID | Author | Resolution |
|----|--------|------------|
| 4285289269 | coderabbitai | N/A — bot “review in progress” notice (no actionable code) |
| 4285291480 | sourcery-ai | N/A — reviewer’s guide / diagrams (no open code task) |
| 4285294093 | qodo-code-review | N/A — automated summary (no open code task) |

## PR reviews (5) — `GET /repos/.../pulls/78/reviews`

| ID | Author | Resolution |
|----|--------|------------|
| 4144456773 | gemini-code-assist | RESOLVED — inline threads addressed |
| 4144461381 | sourcery-ai | RESOLVED — inline threads addressed |
| 4144468446 | chatgpt-codex-connector | RESOLVED — inline threads addressed |
| 4144468497 | cursor | RESOLVED — Bugbot inline threads addressed |
| 4144469140 | copilot-pull-request-reviewer | RESOLVED — inline threads addressed |

## Scope proof (#77)

| Requirement | Evidence |
|-------------|----------|
| Sidecar auto-launch | `ws_bridge.startSidecarIfNeeded` + `start_sidecar.bat` |
| Per-lap archive + rotation + Settings | `lap_archive.lua`, `hud_settings.lua`, `ac_copilot_trainer.lua` lap block |
| Portable paths / WS default / validity | This commit + prior `f5b6648` lap invalidation + relative bat |

## Verification

- `python -m pytest tests/ -q` — pass  
- `python -m ruff format --check` / `ruff check` — pass  
- `python -m pytest -q --cov=... --cov-fail-under=80` — pass  
- `python -m bandit -r src tools -ll -ii` — pass  
- `python scripts/check_agent_forbidden.py` — pass  
