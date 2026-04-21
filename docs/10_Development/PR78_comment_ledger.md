# PR #78 — zero-sampling comment ledger

Full inventory via `gh api repos/agorokh/ac-copilot-trainer/pulls/78/comments --paginate` (and the same for `issues/78/comments` and `pulls/78/reviews`). Every inline thread ID is listed below as **RESOLVED**; actionable text was implemented on this branch or marked N/A for meta-only bot posts.

## Checks (required + bots)

| Check | Outcome |
|-------|---------|
| build | pass |
| Canonical docs exist | pass |
| CodeRabbit | pass |
| Sourcery | pass |
| Cursor Bugbot | skipping (external) — not a failing GitHub job |

## Inline review threads (`pulls/78/comments`)

| Comment ID | Author | RESOLVED |
|-------------|--------|----------|
| 3114511556 | gemini-code-assist[bot] | yes |
| 3114511559 | gemini-code-assist[bot] | yes |
| 3114511561 | gemini-code-assist[bot] | yes |
| 3114511563 | gemini-code-assist[bot] | yes |
| 3114515719 | sourcery-ai[bot] | yes |
| 3114515722 | sourcery-ai[bot] | yes |
| 3114515728 | sourcery-ai[bot] | yes |
| 3114521845 | chatgpt-codex-connector[bot] | yes |
| 3114521847 | chatgpt-codex-connector[bot] | yes |
| 3114521894 | cursor[bot] | yes |
| 3114521895 | cursor[bot] | yes |
| 3114522448 | Copilot | yes |
| 3114522470 | Copilot | yes |
| 3114522484 | Copilot | yes |
| 3114522493 | Copilot | yes |
| 3114522505 | Copilot | yes |
| 3114522515 | Copilot | yes |
| 3114525805 | coderabbitai[bot] | yes |
| 3114525810 | coderabbitai[bot] | yes |
| 3114525815 | coderabbitai[bot] | yes |
| 3114525820 | coderabbitai[bot] | yes |
| 3114525824 | coderabbitai[bot] | yes |
| 3114525826 | coderabbitai[bot] | yes |
| 3114539620 | chatgpt-codex-connector[bot] | yes |
| 3114539624 | chatgpt-codex-connector[bot] | yes |
| 3114539629 | chatgpt-codex-connector[bot] | yes |
| 3114540641 | cursor[bot] | yes |
| 3114561455 | chatgpt-codex-connector[bot] | yes |
| 3114561460 | chatgpt-codex-connector[bot] | yes |
| 3114567935 | cursor[bot] | yes |
| 3114567940 | cursor[bot] | yes |
| 3114567942 | cursor[bot] | yes |
| 3114609395 | chatgpt-codex-connector[bot] | yes |
| 3114609396 | chatgpt-codex-connector[bot] | yes |
| 3114609397 | chatgpt-codex-connector[bot] | yes |
| 3114658033 | chatgpt-codex-connector[bot] | yes |
| 3114658034 | chatgpt-codex-connector[bot] | yes |
| 3114664144 | cursor[bot] | yes |
| 3114694276 | coderabbitai[bot] | yes |
| 3114694280 | coderabbitai[bot] | yes |
| 3114694284 | coderabbitai[bot] | yes |
| 3114694288 | coderabbitai[bot] | yes |
| 3114706575 | cursor[bot] | yes |
| 3114706578 | cursor[bot] | yes |
| 3114736822 | chatgpt-codex-connector[bot] | yes |
| 3114739601 | cursor[bot] | yes |
| 3114785252 | cursor[bot] | yes |
| 3114785255 | cursor[bot] | yes |
| 3114812814 | cursor[bot] | yes |
| 3114812816 | cursor[bot] | yes |
| 3114836808 | chatgpt-codex-connector[bot] | yes |
| 3114836811 | chatgpt-codex-connector[bot] | yes |
| 3114848050 | cursor[bot] | yes |
| 3114884150 | coderabbitai[bot] | yes |
| 3114884160 | coderabbitai[bot] | yes |
| 3114884161 | coderabbitai[bot] | yes |

### Latest audit batch (CodeRabbit / Cursor after `4d4eb85`)

Implemented in the same commit as this ledger refresh (see `git log -1 -- docs/10_Development/PR78_comment_ledger.md`).

- **3114694276**: Ledger uses stable wording (no stale “next commit” phrasing).
- **3114694280**: `wsBridge.cornerAdvisorySnapshotForLap(...)` supplies lap-filtered `corner_advice_used` for the archive (lap argument = in-lap index, i.e. `(state.lapsCompleted or 0) - 1` after the lap-boundary increment).
- **3114736822 / 3114739601**: Same off-by-one: snapshot must use the completed lap’s in-race index, not post-increment `lapsCompleted`.
- **3114694284 / 3114694288**: Archive filename includes `lap_uuid` fragment; `flush` before `close` after JSON write.
- **3114706575**: `start_sidecar.bat` sets `AC_COPILOT_OLLAMA_*` defaults only when undefined (respects inherited env).
- **3114706578**: Each record gets a shallow copy of trace field names, not the module `TRACE_FIELDS` table reference.
- **3114785252**: `lap_archive.write` uses `persistence.encodeJsonCompact` so large traces do not pretty-print into oversized files.
- **3114785255**: `start_sidecar.bat` exits after `py -3` sidecar exit instead of silently retrying with `python` (different interpreter).
- **3114812814**: `lap_archive.stats()` cache TTL uses `os.time` instead of `os.clock`.
- **3114812816**: Lap archive car/track ids use `persistence.archiveCarIdFromCar` / `archiveTrackIdFromSim` (single key list with `sessionKey`).
- **3114836808**: `lapArchiveEnabled` / `lapArchiveMaxMB` persisted via per-key `ac.storage` + Settings callbacks (table-form broken on target CSP).
- **3114836811**: `ws_bridge` clears `sidecarChildEverLaunched` after one-shot zombie close, on clean child exit when `sock` is nil, and in `M.reset`.
- **3114848050**: `runConsoleProcess` treats nil like failure; `M.reset` clears `spawnedAlive`.
- **3114884150**: `_recvQueue` moved to module scope so `configure`/`reset` clear the real queue.
- **3114884160**: `startSidecarIfNeeded` calls `tryOpen()` before spawn so an already-listening sidecar is dialed instead of double-launched.
- **3114884161**: `sidecarProtocolReady` gates `sidecarConnected()` until inbound JSON matches `PROTOCOL_VERSION`.

## Issue comments (`issues/78/comments`): 5

Bot-only notices (review in progress, guide, Qodo summary). **N/A** (no code actions). `4285289269` (CodeRabbit guide) had `updated_at` after `5f0ce39` — still **N/A**. `4285619084` / `4285661809` (Codex usage limit notices) — **N/A**.

## PR reviews (`pulls/78/reviews`): 22

Automated summaries; actionable items are the inline threads above. **N/A** (including Codex review `4144721164` and Cursor Bugbot summary `4144723642` after `5f0ce39`, Bugbot summary `4144770623` after `2bf60e6`, Bugbot summary `4144802228` after `34eb015`, Codex review `4144824801` after `7370f28`, and post-`582514f` bot summaries on `582514f`).

## Issue #77 scope proof

| Requirement | Evidence |
|-------------|----------|
| Auto-launch sidecar | `ws_bridge.lua`, `start_sidecar.bat` |
| Per-lap archive + disk cap | `lap_archive.lua`, lap-completion block in `ac_copilot_trainer.lua` |
| Settings / status / archive controls | `hud_settings.lua` |

## Local verification

`python -m pytest tests/`, `python -m ruff format --check`, `python -m ruff check` (and CI coverage gate as in `Makefile`).
