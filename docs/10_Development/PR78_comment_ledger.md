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
| 3114899783 | cursor[bot] | yes |
| 3114899786 | cursor[bot] | yes |
| 3114942210 | cursor[bot] | yes |
| 3114969128 | chatgpt-codex-connector[bot] | yes |
| 3114969130 | chatgpt-codex-connector[bot] | yes |
| 3114990017 | cursor[bot] | yes |
| 3114990022 | cursor[bot] | yes |
| 3115010037 | chatgpt-codex-connector[bot] | yes |
| 3115067724 | cursor[bot] | yes |
| 3115138041 | Copilot | yes |
| 3115138063 | Copilot | yes |
| 3115178703 | chatgpt-codex-connector[bot] | yes |
| 3115179416 | cursor[bot] | yes |

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
- **3114899783**: Integer MB cap (`lap_archive.clampArchiveCapMB` floors); no per-frame persist on in-UI normalize; slider persists `math.floor`d MB.
- **3114899786**: Removed unused `setWsSidecarUrl` viewmodel field and dead `setWsSidecarUrlAndReconfigure` helper (URL is per-key + auto-launch only).
- **3114942210**: `is_pb` captured from pre-PB-update `bestLapMs` (`isPbThisLap`) for the archive record.
- **3114969128**: `SESSION_UUID` regenerated in `resetRollingDrivingState` when the lap counter rolls back without a full track leave.
- **3114969130**: `lap_archive.write` removes the partial file if `f:write` fails.
- **3114990017**: `M.reset` no longer clears `spawnedAlive` (child can outlive the reset; avoids double sidecar on 8765).
- **3114990022**: `shortUuid` uses two 16-bit `math.random` draws instead of a 24-bit bound.
- **3115010037**: `rotate` adds ~250KB per file when `io.fileSize` fails (`size == -1`), not only when total is zero.
- **3115067724**: `setLapArchiveEnabledAndPersist(enabled)` takes the new flag and assigns `config` (matches approach/cap MB setters).

### Post-`5b6fd29` audit (Copilot inline + CodeRabbit review)

- **3115138041**: `ws_bridge.startSidecarIfNeeded`: exit code **2** from `start_sidecar.bat` stops further auto-spawn for the session; streak backoff (**120s**) after **10** consecutive failed `runConsoleProcess` spawns; `tryOpen()` still connects a manually started sidecar before the backoff gate.
- **3115138063**: `lap_archive.write` builds `sessShort` from `session_uuid` with the same `[^%w]` strip as `lapKey`, with fallback `sess` when empty.
- **4145106151** (CodeRabbit PR review, duplicate of flush/close theme): `lap_archive.write` treats flush/close failures as hard errors, removes the partial file, and only runs `rotate` / `bustStatsCache` after a successful close.

### Post-`9e3ceca` audit (Codex + Cursor inline on `ws_bridge`)

- **3115178703**: Exit callback increments a **nonzero child exit** streak; after **8** rapid nonzero exits, apply the same **120s** sim-time `spawnAbandonUntilT` backoff as spawn pcall failures (covers bat start then immediate failure without `runConsoleProcess` error).
- **3115179416**: Bat **exit code 2** permanent abandon runs **outside** the `ac.log` guard so behavior does not depend on logging availability.

## Issue comments (`issues/78/comments`): 7

Bot-only notices (review in progress, guide, Qodo summary). **N/A** (no code actions). `4285289269` (CodeRabbit guide) had `updated_at` after `5f0ce39` and again after `9e3ceca` — still **N/A**. `4285619084` / `4285661809` / `4285796677` / `4285928383` (Codex usage limit notices) — **N/A**.

## PR reviews (`pulls/78/reviews`): 33

Automated summaries; actionable items are the inline threads above. **N/A** (including Codex review `4144721164` and Cursor Bugbot summary `4144723642` after `5f0ce39`, Bugbot summary `4144770623` after `2bf60e6`, Bugbot summary `4144802228` after `34eb015`, Codex review `4144824801` after `7370f28`, and post-`582514f` / `4095bd9` / `862255a` / `29d1f82` / `099d7a2` bot summaries). CodeRabbit review `4145106151` (flush/close / partial-file cleanup on `lap_archive.write`) is **resolved** in code — listed here because it is a top-level review, not an inline thread. Post-`9e3ceca` review events `4145194031` (Codex) / `4145194773` (Cursor Bugbot) correspond to inline **3115178703** / **3115179416** above — **resolved** in code, not separate scope.

## Issue #77 scope proof

| Requirement | Evidence |
|-------------|----------|
| Auto-launch sidecar | `ws_bridge.lua`, `start_sidecar.bat` |
| Per-lap archive + disk cap | `lap_archive.lua`, lap-completion block in `ac_copilot_trainer.lua` |
| Settings / status / archive controls | `hud_settings.lua` |

## Local verification

`python -m pytest tests/`, `python -m ruff format --check`, `python -m ruff check` (and CI coverage gate as in `Makefile`).
