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
| 3115226944 | chatgpt-codex-connector[bot] | yes |
| 3115286347 | chatgpt-codex-connector[bot] | yes |
| 3115287680 | cursor[bot] | yes |
| 3115341635 | chatgpt-codex-connector[bot] | yes |
| 3115346219 | coderabbitai[bot] | yes |
| 3115346235 | coderabbitai[bot] | yes |
| 3115377868 | cursor[bot] | yes |
| 3115531186 | Copilot | yes |
| 3115531217 | Copilot | yes |
| 3115531234 | Copilot | yes |

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

### Post-`769bf82` audit (Codex inline)

- **3115226944**: Do **not** reset `nonzeroExitStreak` on successful `runConsoleProcess` return; only clean exit (`code == 0`), permanent code **2**, `tryOpen()`, and configure/reset clear it — so the streak reaches the **8**-exit backoff across fast crash loops.

### Post-`a176b26` audit (Codex + Cursor inline)

- **3115286347**: `loadConfig` migrates persisted `wsSidecarUrl` to `CONFIG_DEFAULTS.wsSidecarUrl` when empty **or** not `ws://127.0.0.1:8765` / `ws://localhost:8765` (after trim), then `set()` so auto-launch and dial target stay aligned.
- **3115287680**: While `currentSimT < spawnAbandonUntilT`, gate `tryOpen()` with `lastBackoffTryOpenT` + `LAUNCH_RETRY_SEC` instead of calling it every frame after the main launch throttle elapses.

### Post-`61ec94f` audit (Codex + CodeRabbit)

- **3115341635**: `carLapInvalidatedFlag` no longer returns early for non-table `car`; only `nil` is rejected so userdata `ac.StateCar` is probed via `pcall` field reads.
- **3115346219**: Ledger “Local verification” lines match `Makefile` targets `ci-test` / `ci-format` / `ci-lint`.
- **3115346235**: `lap_archive.write` treats flush/close as failed when `pcall` errors **or** the method result is not truthy (`not flushRes` / `not closeRes`); renamed inner error locals to avoid shadowing `ferr` from `io.open`.

### Post-`26bfda8` audit (Cursor inline)

- **3115377868**: `lap_archive.buildRecord` reads `sim.trackLengthM` via `pcall` without a `type(sim) == "table"` guard so userdata `ac.StateSim` populates `track.lengthM`.

### Copilot inline (sidecar frame order + EmmyLua + PR text)

- **3115531186**: `script.update` calls `wsBridge.startSidecarIfNeeded(appDir)` before `wsBridge.tick(...)` so `tick()` does not run its `tryOpen()` cadence in the same frame as the spawn path’s dial attempt.
- **3115531217**: `persistence.archiveCarIdFromCar` / `archiveTrackIdFromSim` document `ac.StateCar|nil` and `ac.StateSim|nil` (userdata-safe `pcall` field reads).
- **3115531234**: PR description files table + risk section updated to match `start_sidecar.bat` (walk-up repo discovery, optional `AC_COPILOT_REPO_ROOT` override) — no hardcoded checkout path.

## Issue comments (`issues/78/comments`): 7

Bot-only notices (review in progress, guide, Qodo summary). **N/A** (no code actions). `4285289269` (CodeRabbit guide) had `updated_at` after `5f0ce39` and again after `9e3ceca` — still **N/A**. `4285619084` / `4285661809` / `4285796677` / `4285928383` (Codex usage limit notices) — **N/A**.

## PR reviews (`pulls/78/reviews`): 39

Automated summaries; actionable items are the inline threads above. **N/A** (including Codex review `4144721164` and Cursor Bugbot summary `4144723642` after `5f0ce39`, Bugbot summary `4144770623` after `2bf60e6`, Bugbot summary `4144802228` after `34eb015`, Codex review `4144824801` after `7370f28`, and post-`582514f` / `4095bd9` / `862255a` / `29d1f82` / `099d7a2` bot summaries). CodeRabbit review `4145106151` (flush/close / partial-file cleanup on `lap_archive.write`) is **resolved** in code — listed here because it is a top-level review, not an inline thread. Post-`9e3ceca` review events `4145194031` (Codex) / `4145194773` (Cursor Bugbot) correspond to inline **3115178703** / **3115179416** above — **resolved** in code, not separate scope. Post-`769bf82` Codex review `4145245239` maps to inline **3115226944** — **resolved** in code. Post-`a176b26` reviews `4145310407` (Codex) / `4145311753` (Cursor Bugbot) map to inline **3115286347** / **3115287680** — **resolved** in code. Post-`61ec94f` Codex review `4145370656` → inline **3115341635**; CodeRabbit review `4145375398` → inline **3115346219** / **3115346235** — **resolved** in code. Post-`26bfda8` Cursor Bugbot review `4145407903` → inline **3115377868** — **resolved** in code.

## Issue #77 scope proof

| Requirement | Evidence |
|-------------|----------|
| Auto-launch sidecar | `ws_bridge.lua`, `start_sidecar.bat` |
| Per-lap archive + disk cap | `lap_archive.lua`, lap-completion block in `ac_copilot_trainer.lua` |
| Settings / status / archive controls | `hud_settings.lua` |

## Local verification

Same as `make ci-test`, `make ci-format`, `make ci-lint`:

`python -m pytest -q --cov=ac_copilot_trainer --cov=tools --cov-fail-under=80`, `python -m ruff format --check src tests tools scripts`, `python -m ruff check src tests tools scripts`.
