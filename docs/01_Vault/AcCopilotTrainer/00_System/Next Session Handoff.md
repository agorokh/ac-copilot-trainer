---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-06-16T09:19:15Z
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/Architecture Invariants.md
  - AcCopilotTrainer/00_System/glossary/rig-network.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - AcCopilotTrainer/03_Investigations/screen-debugging-journey-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/cowork-session-retrospective-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md
  - AcCopilotTrainer/03_Investigations/pr-207-motec-reference-import.md
  - AcCopilotTrainer/03_Investigations/pr-75-ollama-corner-coaching-protocol.md
  - AcCopilotTrainer/03_Investigations/template-sync-pr87-2026-04-24.md
---

# Next session handoff

## What was delivered (2026-06-16 — PR #214 PR-pain PyYAML-free allowlist follow-up)

**PR [#214](https://github.com/agorokh/ac-copilot-trainer/pull/214) MERGED** `2026-06-16T09:18:15Z` as squash [`3e9c927`](https://github.com/agorokh/ac-copilot-trainer/commit/3e9c9277d867c52b6f78e8b61fe8b437895f9691). This was an owned follow-up from the #179 closeout: PR #198's post-merge `PR pain detection / score` job failed because GitHub's Python 3.11 runner did not include PyYAML. The workflow now calls `python3 -m tools.pr_pain.config` instead of importing PyYAML inline, using a repo-local parser for the owned `.github/pr-pain-config.yml` top-level list shape. `tools.pr_pain.pain_score._load_extra_bots` reuses the same parser for `extra_bot_logins`.

**Verification:** local `make ci-fast PYTHON=/Users/arseny_gorokh/.codex/worktrees/issue-179/ac-copilot-trainer/.venv/bin/python` passed (`920 passed, 74 skipped`, coverage 81.10%). GitHub checks on PR #214 were green (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery/Gemini/Codex review bots were quota-limited as comments only). GraphQL `reviewThreads` returned no nodes. The real post-merge proof also passed: PR #214's merge-triggered `PR pain detection / score` run succeeded on Ubuntu 24.04 / Python 3.11 and logged the expected allowlist skip for `agorokh/ac-copilot-trainer` without PyYAML. Post-merge classification: `.github/workflows/` changed; review triggers/permissions/secrets touched only by replacing the allowlist parser call. **Focus remains #190**.

## What was delivered (2026-06-16 — #177 / PR #200 detect-and-retry entry launcher)

**[#177](https://github.com/agorokh/ac-copilot-trainer/issues/177) CLOSED / PR [#200](https://github.com/agorokh/ac-copilot-trainer/pull/200) MERGED** `2026-06-16T08:59:16Z` as squash [`ee25118`](https://github.com/agorokh/ac-copilot-trainer/commit/ee25118f86326f9bd68211e8ab8565a621330ef6). The harness now has `tools/ac_harness/entry_launcher.py`: a pluggable `EntryLauncher` that normalizes prior state, launches AC, polls `DrivingEntryDetector`, triggers an actuator while stuck, and falls back to quit+relaunch when the default actuator cannot press Drive.

The conservative default path is `ColdRestartActuator`: resolve `acs.exe` / `race.ini` to absolute paths, kill any existing `acs.exe`, atomically rewrite `[RACE] SPAWN_SET=PIT`, launch with `cwd=acs.exe.parent`, and reapply normalization before every relaunch. The module is exported from `tools.ac_harness` and includes a CLI: `python -m tools.ac_harness.entry_launcher --acs-exe <path> --race-ini <path>` plus timing knobs (`--max-launches`, `--attempt-timeout`, `--poll-interval`, `--trigger-after`, `--trigger-interval`, `--max-drive-triggers-per-launch`, `--required-live-reads`, `--stagnation-seconds`).

**Verification:** local targeted harness checks passed (`44 passed` across `tests/test_ac_harness_entry_launcher.py` and `tests/test_ac_harness_shared_memory.py`); full local `make ci-fast` passed with `911 passed, 71 skipped`, coverage 83.73%; GitHub checks on PR #200 were green (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery/Gemini rate-limited as comments only). GraphQL review-thread audit ended with every Cursor/Gemini thread resolved. Post-merge classification: no migration/env/deps/script/workflow flags.

**Runtime caveat:** this was not live-verified against Windows AC/Content Manager from the macOS worktree. Next rig pass should run the CLI against the real `acs.exe` and `Documents/Assetto Corsa/cfg/race.ini`, observe `SPAWN_SET=PIT` normalization, and confirm the loop gives AC enough time for shared memory creation instead of rapid relaunching. Active focus remains #190; PR #200 supplies the reusable launcher layer that #190/carcsw can compose with.

## What was delivered (2026-06-16 — #79 / PR #207 MoTeC reference-lap import)

**[#79](https://github.com/agorokh/ac-copilot-trainer/issues/79) / PR [#207](https://github.com/agorokh/ac-copilot-trainer/pull/207) MERGED** `2026-06-16T08:55:47Z` as squash [`0c637e3`](https://github.com/agorokh/ac-copilot-trainer/commit/0c637e3bf3f648e75b40e6b760ceff097ac9a241). The repo now has `python -m tools.import_motec <input.csv> --car <car_id> --track <track_id> [--layout <layout>]`, which heuristically maps MoTeC CSV channels, normalizes units, resamples to 2000 schema-v1 samples, and writes `source="imported"`, `import_format="motec_csv"` lap archive JSON under `journal/laps/`.

The CSP app now has an opt-in Settings flag, **Prefer imported reference over local PB** (`useImportedReference=false` by default). On load or toggle it scans `journal/laps/` for imported MoTeC laps matching the active car/track, activates a faster imported lap as the realtime reference, re-derives braking points / segments / corner features from that imported trace, and preserves the user's local PB persistence separately. Imported laps never overwrite local PB files. See [`03_Investigations/pr-207-motec-reference-import`](../03_Investigations/pr-207-motec-reference-import.md).

**Verification:** local `make ci-fast PYTHON=.venv/bin/python` passed (`890 passed, 74 skipped`, coverage 80.58%, CSP API/safety checks green). Artifact CLI smoke produced a schema-v1 imported lap JSON with 2000 samples. GitHub checks for PR #207 were green (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery skipped/rate-limited). GraphQL `reviewThreads` returned no unresolved threads. Post-merge classification: no migration/env/deps/script/workflow flags. **Focus remains #190**.

## What was delivered (2026-06-16 — #118 / PR #203 peripheral telemetry/haptics)

**[#118](https://github.com/agorokh/ac-copilot-trainer/issues/118) / PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) MERGED** `2026-06-16T08:53:54Z` as squash [`e5103be`](https://github.com/agorokh/ac-copilot-trainer/commit/e5103be29965b118efa309ee6f3a97a29cb329af). The sidecar external protocol now includes high-rate physical-peripheral frames: `telemetry_tick` from loopback Lua to physical clients (`screen`, `haptics`, `physical`) and `haptic_event` to haptic-capable clients, with per-type rate limiting and no echo back to Lua. The sidecar also derives bounded haptic cues from telemetry (`pedal_rumble`, `slip_buzz`).

**Review hardening shipped before merge:** generated haptic events omit absent `ts_sim` instead of validating as `null`; signed negative `slip` values are valid and can drive `slip_buzz`; optional tyre maps accept non-empty partial corner sets; legacy firmware clients whose `client` starts with `ac-copilot-screen` route as `screen` even when they omit `client_class`.

**Verification:** targeted local routing tests passed (`tests/test_ai_sidecar_external.py` + `tests/test_ws_topic_allowlist.py`, 31 passed); branch local parity passed (`make ci-fast`, 897 passed, 71 skipped, coverage 83.95%); GitHub PR checks passed (build, canonical docs, conformance, CodeRabbit, Cursor Bugbot; Sourcery skipped by service rate limit); GraphQL audit showed all 6 review threads resolved before merge. Post-merge `main` parity passed again after sync (`make ci-fast`, 911 passed, 71 skipped, coverage 84.16%). Post-merge classification for PR #203: no migration/env/deps/script/workflow flags. Issue #118 was manually closed because GitHub did not auto-link it from the PR title.

**What remains:** no #118 follow-up is required from the protocol/test surface. Hardware/on-rig actuator consumption is still downstream physical-rig work; continue #190 / carcsw productionization as the active next thread.

## What was delivered (2026-06-16 — #179 / PR #198 vault-branch CI policy papercut)

**[#179](https://github.com/agorokh/ac-copilot-trainer/issues/179) / PR [#198](https://github.com/agorokh/ac-copilot-trainer/pull/198) MERGED** `2026-06-16T08:54:58Z` as squash [`4a8ab98`](https://github.com/agorokh/ac-copilot-trainer/commit/4a8ab9888cf0996799160e7c78aa26e38fd8c085). `scripts/ci_policy.py` now allows documented `vault/post-merge-pr<N>` branches via the `vault/` prefix, and `tests/test_ci_policy.py` covers both direct branch validation and pull-request event handling for that branch shape.

**Review-driven hardening included:** `tests/test_repo_knowledge/test_mcp_server_import.py` now skips only when the optional `[knowledge]` MCP package is genuinely absent or shadowed by this repo's local `scripts/mcp` namespace; when `[knowledge]` is installed, it still imports `tools.repo_knowledge.mcp_server` and fails if `mcp.server.fastmcp` is missing. This closed Codex's review thread without letting CI mask an incompatible installed MCP package.

**Verification:** local `make ci-fast PYTHON=.venv/bin/python` passed after the final patch (`882 passed, 74 skipped`, coverage 80.08%, bandit/policy/CSP checks green). GitHub Actions for PR #198 were green on the final SHA (`build`, `conformance`, `Canonical docs exist`, CodeRabbit, Cursor Bugbot; Sourcery review skipped/rate-limited as a completed check). GraphQL `reviewThreads` showed no current blocking unresolved threads; the only unresolved thread was outdated. Post-merge classification: `scripts/` changed, no migration/env/deps work to run. **Focus remains #190**.

## Resume here (2026-06-16 — #183 socket-open epoch follow-up MERGED; focus stays on #190)

**[#183](https://github.com/agorokh/ac-copilot-trainer/issues/183) / PR [#197](https://github.com/agorokh/ac-copilot-trainer/pull/197) MERGED** `2026-06-16T08:43:39Z` as squash [`392a868`](https://github.com/agorokh/ac-copilot-trainer/commit/392a8688d716a33dffad20cbf2a38a0c7ea17b90). The trainer now tracks a monotonic `ws_bridge.openEpoch()` incremented from CSP `web.socket` `onOpen`, ignores stale `onOpen` callbacks from replaced sockets, and re-arms `lifecycle_publisher` when the epoch changes even if `sidecarConnected()` stayed true across an auto-reconnect.

**Verification:** targeted Lupa tests passed (`tests/test_ws_bridge_hello_handshake.py` + `tests/test_lifecycle_publisher.py`, 22 passed); full local parity passed with `make ci-fast PYTHON=/Users/arseny_gorokh/Projects/ac-copilot-trainer/.venv/bin/python` (894 passed, 71 skipped, coverage 83.69%); GitHub PR checks were green for build, canonical docs, conformance, Cursor Bugbot, and CodeRabbit. Review-thread audit left only outdated Gemini threads against pre-fix code. Post-merge classification for PR #197: no migration/env/deps/script/workflow flags.

**Runtime caveat:** this was not re-verified inside Assetto Corsa/CSP from the macOS worktree; the issue acceptance target was the off-sim Lupa reconnect regression. On the next Windows/AC rig pass, a useful smoke is to force a sidecar/CSP auto-reconnect and observe a fresh `session` re-emit without relying on the 1 Hz heartbeat identity backstop.

**What remains:** continue #190 / carcsw productionization from the next block. No #183 follow-up is required unless the in-game reconnect smoke finds a CSP-specific callback ordering edge.

## Resume here (2026-06-16 — EPIC #154 L2 ACHIEVED: agent drove the car autonomously; trainer captured a reference + COACHED it, no human at the wheel)

**The autonomous self-test works end-to-end, verified operator-grade on screen.** Via the CSP
Custom-AI mmap (`carcsw`) + a pure-pursuit controller on Kunos's `fast_lane.ai`, the agent drove
the player car a **full clean lap of Magione** (2,525 m, returned to start, zero crashes) with NO
human input, and **the AC Copilot Trainer captured a reference lap from that drive and coached the
car in real time** (HUD `Best/Last 6:27.316`; coaching widget `T1 — ON PACE`, `TARGET ENTRY 41 ·
CURRENT 43 KMH · DISTANCE TO BRAKING POINT 392 M`). Full detail + all verified facts:
[`03_Investigations/autonomous-drive-live-verified-2026-06-16`](../03_Investigations/autonomous-drive-live-verified-2026-06-16.md).

**Verified live** (promote into the #190 PR): gear encoding **0=R/1=N/2=1st**; launch needs gear≥2
+ `autoclutch_on_start`+`autoclutch_on_change` (never write clutch@8); controls gas@0/brake@4/
steer@12/gear_up@20/gear_dn@21/autoclutch@41,42/**teleport_to@40=1=pits** (the safe reset); Car0
reads pos@88/look@64/gear@28/rpm@32/speed@36 == physics; **`spline@448` is GARBAGE** (drop it);
PurePursuit steer sign already correct (steer>0=right). **`restart_session()` is POISON** (opens
AC's modal menu; OS input into AC menus is dead → needs a CM relaunch). Menu-skip is a CM
timing-race even with "Start race immediately" ON → **retry launches**; minimize the Claude window
so CM is clickable. **Lap detection:** hotlap mode only counts VALID laps in `completedLaps@132`
(curb-clip invalidates) → use position-return / `normalizedCarPosition`.

**Next session (banking):** productionize `carcsw` (`tools/ac_harness/custom_ai.py` + `ai_line.py`)
into the **#190 PR** — mark verified offsets CONFIRMED, drop/fix `spline@448`, add the gear+
autoclutch launch recipe + steer-sign + position-return lap detection + the `auto_lap*.py` driver
logic. Then restore `content/tracks/magione/data/surfaces.ini` (extended-physics +
`[_EXTRA_PERMISSIONS]` edit; backup at `surfaces.ini.bak-precustomai`). Driver/probe artifacts are
in gitignored `.scratch/` (`auto_lap4.py` = clean full lap; `auto_lap5/6.py`; `VERIFIED_FINDINGS.md`).

---

## Resume here (2026-06-15 — #180 Part D step 2 DONE: all 5 WS producers merged (#185, `64a127e`) AND tire_temps VERIFIED operator-grade in-game)

**[#185](https://github.com/agorokh/ac-copilot-trainer/pull/185) MERGED (squash `64a127e`).** The final two declared producers — `delta` + `tire_temps` (`modules/telemetry_publisher.lua`) — plus a real bug fix surfaced by operator-grade live verification. **All 5 KNOWN_TOPICS producers now exist** (connection/session/lap from #182; delta/tire_temps from #185; coaching.snapshot/setup.active pre-existing).

**The rr=0 bug (why this PR grew to 7 review rounds):** live `tire_temps` showed `rr=0` while the AC physics oracle (`acpmf_physics.tyreCoreTemperature[FL,FR,RL,RR]`) read all four non-zero. Root cause: **CSP `car.wheels` is 0-indexed** per `ac.Wheel` (FrontLeft=0..RearRight=3) — `tire_monitor.lua` read `wheels[1..4]`, shifting every corner and reading an out-of-bounds zero for RR. Fixed `Mon:currentTemps` + `Mon:update`. Triangulated against the `ac.Wheel` enum, the shipped CMRT-Essential-HUD (`for i=0,3`), and the physics oracle. See [`03_Investigations/csp-car-wheels-0-indexed-2026-06-15`](../03_Investigations/csp-car-wheels-0-indexed-2026-06-15.md) (reusable CSP gotcha).

**Other hardening (11 review threads, Cursor + CodeRabbit + codex):** delta now publishes **only when the lap clock is start/finish-aligned** ([`01_Decisions/delta-clock-boundary-alignment`](../01_Decisions/delta-clock-boundary-alignment.md)) — no bogus delta across lap boundaries, spline-only resets, teleports (guarded `car.resetCounter` via new `csp_helpers.safeCarField`), or mid-track clock seeds. Lap-boundary finalize gated on `not teleported`. Non-finite (NaN/inf) temps + delta_s/spline filtered. 48 lua tests.

**GATE CLOSED — VERIFIED operator-grade (2026-06-15, live drive).** `.scratch/diag_wheels.py` reconciled the trainer's `tire_temps` against the physics oracle wheel-by-wheel: **FL 48.92 vs 49.0 · FR 42.33 vs 42.4 · RL 57.18 vs 57.2 · RR 48.59 vs 48.7** — all four within ~0.1 °C and **RR non-zero** (was 0 pre-fix). The 0-indexed-wheels fix is correct against reality. A 20 s mid-session tap also confirmed the broader pipeline live: connection=19, lap=1, **delta=198**, tire_temps=99, coaching.snapshot=198. **#180 Part D step 2 is fully operational.** (Operator note: AC was running the whole time — my earlier "AC down" reads were a bad process check (`acs` vs the full set); the only real gate was being on track.)

**Follow-up filed:** [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188) — rolling-state reset on a wrap-shaped same-lap teleport on CSP builds lacking `car.resetCounter` (low-severity; first action: confirm resetCounter is present on the rig, likely mooting it). The delta-leak half is already fixed.

**Next deliverable (Part E) — STARTED:** [#190](https://github.com/agorokh/ac-copilot-trainer/issues/190) filed (carcsw Custom-AI-mmap driver + L1.5 probe, grounded plan).
- **L1.5 sequence probe — MERGED [#191](https://github.com/agorokh/ac-copilot-trainer/pull/191) (`2f092da`, `tools/ac_harness/sequence_probe.py`).** Pure `evaluate_sequence()` checks CONTINUOUS-stream presence (connection/tire_temps/coaching.snapshot) + session-before-lap ordering; session/lap conditional notes (required under `--strict`/`--wait-lap`), delta always a note (reference-lap-dependent). 16 tests, hardened through 11 review threads. **LIVE-VALIDATED** 2026-06-15: clean PASS on a real drive (connection=31, tire_temps=153, coaching.snapshot=305; earlier window caught lap=1, delta=198). **CLI:** `python tools/ac_harness/sequence_probe.py [--wait-lap] [--strict] [--seconds N]` (now sys.path-bootstrapped, so file-path OR `-m` both work; `--wait-lap` waits for + requires a lap; `--strict` requires session+lap from session start). Use it to verify the producer pipeline on any future drive.
- **Remaining Part E (NOT built):** (1) the `carcsw` **Custom AI mmap writer** — the actuation keystone that lets the agent drive car 0 itself (no operator lap). Build-time research needed: `cai_car_data`/`cai_wheel_data` struct layout + mmap name from cup.acstuff.club/docs/csp/other-things/custom-ai. Off-sim-testable like #175's reader; in-sim driving gated. **This is the unblock for self-verification without the operator** — the EPIC #154 throughline. (2) Trainer-side **`session` re-emit to late-attaching taps** (noted on #190) so a mid-session probe gets a deterministic session→lap sequence without restarting the session.
- **Constraint:** the agent CANNOT launch AC (Steam-integrity). L1.5 still needs ONE operator action (launch AC + sit on track), then the agent drives+asserts. Full hands-off (L2) needs the operator-gated control-channel daemon.

---

## Resume here (2026-06-15 — Part D step 2 LIFECYCLE producers (connection/session/lap) MERGED + verified live; delta/tire_temps next)

**[#180](https://github.com/agorokh/ac-copilot-trainer/issues/180) lifecycle subset / PR [#182](https://github.com/agorokh/ac-copilot-trainer/pull/182) MERGED (squash `b14f5c0`).** New `modules/lifecycle_publisher.lua` produces the three lifecycle topics the L1.5 sequence assertions need: `connection` (~1 Hz heartbeat with `{app_version,session_index,car_id,track_id}`), `session` (event on track/car/session change), `lap` (at the `car.lapCount` boundary, stint-scoped `best_lap_ms`). **Verified LIVE** during a real drive (all three flowed with correct payloads — `lap={lap:1,last_lap_ms:108667,...}`), then hardened over **7 adversarial review rounds**. Key design (read before extending):
- `session`/`connection` publish in `script.update` **after `wsBridge.tick()`+`pollInbound()`** and **before the lap boundary** (Cursor HIGH r5: publishing before the tick let a mid-frame-ready WS send `lap` without `session`).
- Reconnect re-arm is **per-frame in the entry script** via `wsBridge.sidecarConnected()` (false→true) → `lifecyclePublisher.rearmSession()` (clears only the session key); **not** coupled to the heartbeat (that spawned duplicate/delay edges r2–r4).
- `session` records its dedup key, and `lap` commits `_stintBest`, **only on a successful publish** (publish-then-record symmetry) so neither reflects an undelivered frame.
- `M.reset()` (stint reset) re-emits `session` + rescopes the stint best; wired into both reset paths in `ac_copilot_trainer.lua` next to `realtimeCoaching.reset()`.

**Next (remaining #180):** `delta` + `tire_temps` producers.
- **`delta`** is easy: reuse `delta.deltaSecondsAtSpline(state.bestSortedTrace, sp, eMs)` — already computed at `ac_copilot_trainer.lua` ~line 1343 (`eMs = (now - tel:lapStartTime())*1000`); only meaningful once a reference lap exists. ~10 Hz, follow the `coaching_publisher`/`lifecycle_publisher` pattern.
- **`tire_temps`** needs the per-wheel CURRENT temps — read from `car.wheels[i]` (the `tire_monitor` instance keeps only lap aggregates, not current); confirm the CSP wheel-temp field. Publish after `tires:update`.
- Verify both **in-game on the next drive** via the patient detector (`.scratch/wait_lifecycle.py`, extend its TARGET set) — anti-false-green: draft until observed.

**Follow-ups filed:** [#183](https://github.com/agorokh/ac-copilot-trainer/issues/183) socket-open-epoch reconnect re-arm in `ws_bridge` (reliable sub-frame reconnect detection; 1 Hz heartbeat is the interim identity backstop). [#177](https://github.com/agorokh/ac-copilot-trainer/issues/177) actuator half (operator decision: ViGEm vs pit-normalization). [#179](https://github.com/agorokh/ac-copilot-trainer/issues/179) `vault/` ci-policy papercut.

---

## Resume here (2026-06-14 latest — #175 VERIFIED LIVE + #170 confirmed during a real drive; Part D step 2 (#180) teed up)

**Operator-grade LIVE verification (captured during the operator's actual drive; evidence in `.scratch/live-verification-2026-06-14.md`):**
- **#175 shared-memory oracle — VERIFIED (gate met).** The armed live-probe captured the real session: `AC_STATUS` OFF(0,stale)→LIVE(2); packets RESET+advanced (gfx 11734→17→209, phys 37311→101→768 = fresh session, real 333 Hz physics); `DrivingEntryDetector` accumulated clear 1/5→5/5 → `driving=True`. The **observed-advancement logic (review finding #8 fix) worked against real frozen-then-advancing packets.** `IsInPit` (offset 160) read `False` on track (decodes sanely). **One residual:** `IsInPit==True` (in pit) not yet captured (operator drove not-in-pit); offset still grounded in 2 sources + correct on-track behavior.
- **#170 — CONFIRMED POSITIVE.** `.scratch/tap_probe.py 25` → 255 frames, **253 × `coaching.snapshot`** received (trainer publishes → sidecar fans out → tap receives), payload advancing (`current_speed_kmh` 14→158→105), state `placeholder/no_reference` (fresh session, no ref lap). Earlier #170 was only confirmed by *absence* of the rejection storm; now confirmed by *receipt*.
- **#173 allow-list working live:** tap got `error: unknown topic: 'coaching'` (non-canonical rejected) while `coaching.snapshot` still arrived (topic-agnostic fan-out).

**Next deliverable — Part D step 2 / [#180](https://github.com/agorokh/ac-copilot-trainer/issues/180) (FILED, branch `feat/issue-180-wire-topic-producers` created):** wire the 5 declared-but-silent topic producers (`connection/session/lap/delta/tire_temps`). Live tap confirmed the gap (only `coaching.snapshot` flows). **Design (from reading the wiring):** model on `modules/coaching_publisher.lua` (rate-limited `publishIfDue` → `wsBridge.publishTopic`); wire into `ac_copilot_trainer.lua` `script.update` next to the `coachingPublisher.publishIfDue` call at **line ~1616** (context: `car`, `sim`, `rtView`, `dt`, `wsBridge`, `state`); the **`lap`** producer hooks the existing lap boundary at **line ~1766** (`lc > state.lastLapCount`; use `car.previousLapTimeMs`); **`delta`** reuses `delta.deltaSecondsAtSpline(state.bestSortedTrace, sp, currentElapsedMs)`; **`tire_temps`** reuses the `tire_monitor.new()` instance temps. **Gate:** headless lupa tests now, but **hold as DRAFT until in-game verification** — re-tap a drive (`.scratch/tap_probe.py`) and confirm all 5 topics flow (needs an operator AC relaunch to pick up the new symlinked producer code, then a drive). Anti-false-green ethos.

**Also filed:** [#177](https://github.com/agorokh/ac-copilot-trainer/issues/177) actuator half (operator decision: ViGEm vs pit-normalization), [#179](https://github.com/agorokh/ac-copilot-trainer/issues/179) `vault/` ci-policy papercut.

---

## Resume here (2026-06-14 late — #175 shared-memory oracle MERGED; menu-skip CRACKED as a race, not a setting)

**This iteration's merge:** **[#175](https://github.com/agorokh/ac-copilot-trainer/issues/175) / PR [#176](https://github.com/agorokh/ac-copilot-trainer/pull/176) MERGED (squash `c13d425`)** — the EPIC #154 L2 **"shared-memory oracle"** (`tools/ac_harness/shared_memory.py`): pure `acpmf_graphics`/`acpmf_physics` parsers + a `DrivingEntryDetector` state machine (CI-tested, any OS) + a Windows `OpenFileMappingW` reader + a stdlib live-probe CLI. 24 tests, module cov 97%. Hardened by a 5-lens adversarial review + a rig smoke test (which caught a 64-bit ctypes `OverflowError` in `close()` CI never could).

**⚠️ SUPERSEDES the prior "the unlock = enable CM 'start session immediately' ONCE" claim below.** Research (workflow `wojtj94jq`, cross-confirmed vs CM open source + CSP changelogs) proved the pre-drive menu-skip is a **timing/state RACE, not a setting** — there is **NO CSP/CM config knob**, and with CSP active CM *delegates* the skip to CSP's new-menu system (so the toggle, already ON, does nothing more). It flips run-to-run on the same car/track and **depends on prior pit state** (operator hunch CONFIRMED). Full write-up: [`03_Investigations/menu-skip-race-and-shared-memory-oracle-2026-06-14`](../03_Investigations/menu-skip-race-and-shared-memory-oracle-2026-06-14.md). **Deterministic fix = detect-and-retry keyed on `acpmf_graphics` (AC_STATUS PAUSE→LIVE + IsInPit=false, packetId advancing)** mirroring CM's `ImmediateStart.SetSharedListener`. #175 is the DETECT half.

**Operator levers / decisions surfaced (non-blocking):**
- **Immediate workaround (no code):** end the prior race by returning to pits / fully quit AC between runs → consistent entry state.
- **Rig verification PENDING (operator-gated):** on the next drive run `python tools/ac_harness/shared_memory.py` while AC sits on the pre-drive menu then drives — confirm `status` flips 3→2 and `is_in_pit` true→false at offset 160. (Agent can't launch AC: elevated-harness/Steam-integrity constraint. Probe already validated open+parse+detect+close against the real stale sections.)
- **[#177](https://github.com/agorokh/ac-copilot-trainer/issues/177) filed — the ACTUATOR half** (detect-and-retry launcher). Decision: ViGEm `__CM_START_SESSION` pulse (vault flags ViGEm "last resort") vs. pit-state normalization + cold restart. Recommend (A) normalization first, add ViGEm only if insufficient. `stuck_in_menu` intentionally NOT shipped in #175 (ambiguous; belongs with the actuator).

**Still open:** Part D step 2 (wire the 5 declared topic producers) — deferred until in-game verification is reliable; the oracle is the enabler. Part E (carcsw in-sim driver + L1.5).

---

## Resume here (2026-06-14 — autonomous run ON the rig AG_PC; #170 handshake fix + Part D step-1 MERGED; EPIC #154 rig-local unlock)

**This run's merges:** #171 (#170 trainer v1 hello handshake), #172 (vault SAVE), #173 (Part D step 1 — WS topic allow-list reconciliation + `publishTopic` drift-guard, squash `c093aa1`). All on `main`, CI-green, bot threads resolved.

**Biggest reframe:** this session ran **Claude Code directly on the rig** (`AG_PC`, Tailscale `100.75.251.87` — the exact host EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) calls "blocked"). The `status:blocked-on-rig` control-channel premise is **obsolete for a locally-running agent**: direct local launch (`acs.exe`) + headless observation (sidecar WS tap, CSP logs, Windows-MCP screenshots). See the [#154 rig-local-unlock comment](https://github.com/agorokh/ac-copilot-trainer/issues/154#issuecomment-4700939387). On-box confirmed: AC user-data = `C:\Users\arsen\OneDrive\Documents\Assetto Corsa` (`cfg\race.ini` present → operator-ask #3 closed); Steam logged in (`agorokh3`); AC+CSP(`dwrite.dll`)+Content Manager installed; `apps\lua\AC_Copilot_Trainer` is a **symlink → repo `src/ac_copilot_trainer`** (edit repo = live in AC after an AC relaunch). Proven: AC launches+renders, CSP loads, trainer reads live car-0 state (`[COPILOT][RT-DIAG] sp=… trackLen=3559`).

**SHIPPED — [#170](https://github.com/agorokh/ac-copilot-trainer/issues/170) / PR [#171](https://github.com/agorokh/ac-copilot-trainer/pull/171) MERGED (squash `7a5b99c`):** a **real production bug found only by running on the rig** — the trainer connected to the sidecar but **never registered as a v1 peer**, so `coaching.snapshot` was silently rejected and never fanned out (rig-screen mirror + any harness tap). Three coupled defects in `ws_bridge.lua`: (1) `publishTopic` published before the hello handshake (guarded only on `sock`); (2) the sidecar's `{v:1,type:error}` reply false-positively set `sidecarProtocolReady`, cancelling the hello retry; (3) the retry was sim-time-paced, frozen in the pre-drive pit menu. Fix: gate `publishTopic`+hello-retry-stop on a **v1-only `externalHelloAcked`** (decoupled from legacy `protocol=1` readiness — chatgpt-codex P1); never flip readiness on error frames; **frame-paced** retry; **re-arm in `onOpen`** for CSP auto-reconnect (CodeRabbit Major). New lupa L0 regression `tests/test_ws_bridge_hello_handshake.py` (6 tests, all green). CI green, both bot threads resolved, full cooldown honored.

**Verification status (honest):** #170 verified by the deterministic lupa suite + observed in-game mechanism (pre-fix rejection storm at the WS layer, post-fix suppressed). The in-game **positive** confirmation (`coaching.snapshot` flowing during real driving) is **blocked on a one-time human action** — see below.

**KEY finding — garage→on-track autonomy (the EPIC's crux):** full investigation in [`03_Investigations/garage-to-track-autonomous-entry-2026-06-13`](../03_Investigations/garage-to-track-autonomous-entry-2026-06-13.md). Two stages: (1) **session entry** is a *launch* problem — `race.ini` Hotlap (`[SESSION_0] TYPE=3 SPAWN_SET=HOTLAP`) + `acs.exe` spawns car 0 **on track** (verified: `sp` advances), BUT does **NOT** skip the pre-drive "Drive" screen — `sim.isInMainMenu` stays true so `wsBridge.tick` never runs. OS input injection into AC's menu is **confirmed dead** (raw input + no background focus). **The single minimal human action that unlocks full in-sim autonomy = enable Content Manager → Settings → Drive → "start session immediately" ONCE**; thereafter launch-into-driving is click-free. (2) **driving** once on track = CSP **Custom AI mmap** (sidecar writes `cai_car_controls` at 333 Hz); the trainer App context can't pilot (APIs `__allow`-gated to newmodes/cphys) — App stays the control plane.

**Next moves (priority):**
1. **Part D step 2 — wire the topic PRODUCERS.** Step 1 (allow-list reconciled to the honest 7-name set incl. `coaching.snapshot`/`setup.active`, + the `publishTopic` drift-guard in `tests/test_ws_topic_allowlist.py`) **SHIPPED in [#173](https://github.com/agorokh/ac-copilot-trainer/pull/173)**. Remaining (next clean deliverable; **headless-verifiable, NOT blocked by driving**): add producers — `connection_publisher.lua` (~1 Hz), `session_publisher.lua` (event), inline `lap` publish at the lap boundary, `delta_publisher.lua` (10 Hz, reuses `delta.deltaSecondsAtSpline`), `tire_temps` (new `Mon:currentTemps()` + publish after `tires:update`); keep `state.subscribe` advisory (fan-out is already topic-agnostic broadcast). The drift-guard from #173 will fail CI if a new producer's topic isn't in `KNOWN_TOPICS` (all 5 already are). Verify via a new lupa test mirroring `test_ws_bridge_hello_handshake.py`. All publishes MUST go through `wsBridge.publishTopic` (the `sock and externalHelloAcked` gate); pcall-guard all sim/car reads. Full per-topic wire-site plan: the 4-agent research workflow output (run `wf_4a24764c-655`).
2. **One attended ~10-min rig pass** to flip the autonomy blocker: enable CM "start session immediately", then confirm (a) click-free on-track entry and (b) Custom AI drives player car 0 (`new_behaviour.ini [CUSTOM_AI] ENABLED=1` + track `surfaces.ini ALLOW_CUSTOM_AI_MANIPULATION=1`). After that, Part E (carcsw driver + L1.5 probe) + the full L2 loop become human-free.

**Housekeeping:** 8 unit tests fail locally on this minimal public spoke (agentic-memory wrapper, governance-hub shims, memory-contract parent-relative links, session-debrief) — **confirmed pre-existing on `main`**, CI `build` green (local-env only). SessionStart prefetch resolves the placeholder `example_kb_workspace` not `ac_copilot` (a gitignored `ops/memory_manifest.local.yml` row would fix the gate stamp) — I queried `ac_copilot` directly, which post-stamps the gate.

## Resume here (2026-06-13 — PR #165 fleet drift-guard merged; active focus UNCHANGED)

**Post-merge steward sync only.** PR [#165](https://github.com/agorokh/ac-copilot-trainer/pull/165) **MERGED** `2026-06-14T01:26:41Z` as squash [`1a08d45`](https://github.com/agorokh/ac-copilot-trainer/commit/1a08d45787e96e16cc660b1b5dd9fb3e4f27e598) (branch `chore/dg309-invariant-section-guard`, deleted on sync). Single test file `tests/test_invariants_present.py` (+94 / −0): fleet-propagates the [`secrets-from-doppler`](invariants/secrets-from-doppler.md) **Scope-clause drift-guard** ([template-repo#308](https://github.com/agorokh/template-repo/issues/308) / [#309](https://github.com/agorokh/template-repo/issues/309); pilot precedent workstation-ops#510) so this repo's own CI now fails on Scope-clause drift in its vault. **No linked issues.** Post-merge classification (`post_merge_classify.py --pr 165`): **no migration / env / deps / workflow flags** — nothing to run. Local `main` fast-forwarded `b7caa5d → 1a08d45`; 7 stale gone-branches pruned.

**This does NOT move the active focus.** The strategic blocker is still EPIC #154 (operator-gated) — see the resume block immediately below.

## Resume here (2026-06-13 — EPIC #154 Parts C + A delivered + merged)

**Two Mac-side foundation parts of EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) are MERGED, verified, on `main`:**

| Part | PR | What it delivers |
|------|----|------------------|
| **C — L1 sidecar WS-tap harness** | [#157](https://github.com/agorokh/ac-copilot-trainer/pull/157) (`b4f9716`) | Headless `HarnessClient` drives a running `ai_sidecar` and asserts the deterministic coaching contract (golden == wire == pure fn). `make ci-drive` + `tools/ai_sidecar/harness_client.py`. |
| **A — L0 off-sim lupa trace-replay** | [#158](https://github.com/agorokh/ac-copilot-trainer/pull/158) (`c435024`) | Real coaching modules under `lupa` vs synthetic traces; clean-lap false-positive guard; **schema-gated** mock (anti-hallucination); `tools/ac_harness/{trace_replay.py,dump_schema.lua,ac_schema.json}` + `tests/test_lua_trace_replay.py`. |

Both layers were proven able to FAIL (planted bugs caught: atan2-shim removal, injected brake). Vault planning PR [#155](https://github.com/agorokh/ac-copilot-trainer/pull/155) (ADR + lupa-testability investigation) also merged. **~90% of the coaching-LOGIC surface is now agent-verifiable with NO game / NO human** (CI + `make ci-drive` on a Mac).

**Remaining Parts D/E/F/G are OPERATOR-GATED** — their real acceptance needs the running game, which needs a control channel onto the AC PC the agent CANNOT open (Tailscale SSH is unsupported on Windows; the agent key is rejected by `pc`). Shipping the in-game Lua (Part D `publishTopic` producers, Parts E–G) without in-sim verification would violate this EPIC's own anti-false-green ethos, so it is deferred until the channel exists. **To unblock the in-game pain reduction, the operator must:**
1. **Open an agent→`pc` (100.75.251.87) control channel** — the in-session "AC harness daemon" (#154 Part F) or an equivalent working channel.
2. **Configure `pc` as a dedicated rig** — auto-login, lock/screensaver OFF, no RDP-disconnect, Steam stays logged in (DRM).
3. **Confirm the OneDrive-redirected AC user-data path** + capture one ground-truth `cfg/race.ini`.
4. **Record ~10 varied human laps** → deterministic L0/L1 fixtures (ties #115/#79).

Once (1) lands, resume: Part E replay-probe → carcsw in-sim driver + **L1.5 sequence probe** (where the operator's pain actually drops) → Part D live topics → Part F daemon → Part G full loop. Open follow-up: [#156](https://github.com/agorokh/ac-copilot-trainer/issues/156) (pre-existing local-only test-isolation; CI-green).

## Resume here (2026-06-12 — EPIC #154 filed: autonomous self-test harness)

**New strategic EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154)** — let the agent test-drive the trainer with **no human in the loop** (the manual "drive a lap to validate" loop is the repo's #1 cost). Researched via 12-direction fan-out + 7 adversarial verdicts + council (Gemini/Kimi/Perplexity). ADR: [`01_Decisions/autonomous-self-test-harness.md`](../01_Decisions/autonomous-self-test-harness.md). Evidence: `.scratch/ac-selftest-grounding.md`.

**Key results:** trainer is input-source-agnostic (`ac.getCar(0)`); the `ai_sidecar` WS is already a headless tap; **CSP "Custom AI" mmap** drives car 0 at 333 Hz (the in-sim driver); AC **replay ≠ re-simulation** (byte-exact stays off-sim); the 5 declared WS topics have **no producers** (false-green trap); **Tailscale SSH unsupported on Windows** → control channel must be an in-session daemon. Council pulled an **in-sim L1.5 probe + Schema Reflection forward** ("pain drops at L1.5, not L1"). Pyramid: L0 lupa → L1 WS-tap → L1.5 in-sim sequence probe → L2 daemon+CSP-Custom-AI+vision-oracle → L3 human smoke. **Operator-gated:** open a control channel onto `pc` (100.75.251.87), set it auto-login/unlocked/Steam-logged-in, confirm OneDrive AC user-data path, record ~10 human laps as fixtures. **Next:** Parts A+B+C (`phase-1`, no AC PC needed) ship the human-free logic regression first; then Part E pre-req replay probe + carcsw. Vault changes (ADR + index + this handoff) are uncommitted in the working tree — land via a `vault-only` PR.

## Resume here (2026-05-31 — PR #129 on `main`)

Continue from **`main`** @ [`9454235`](https://github.com/agorokh/ac-copilot-trainer/commit/945423580ef4f5de2df4c4ad908cabb4724beab3) or newer. Local `main` fast-forwarded by post-merge steward; PR head branch deleted.

**Latest merges:**

| PR | Merged | Squash | Issue / note |
|----|--------|--------|----------------|
| [#129](https://github.com/agorokh/ac-copilot-trainer/pull/129) | `2026-05-31T03:06:48Z` | [`9454235`](https://github.com/agorokh/ac-copilot-trainer/commit/945423580ef4f5de2df4c4ad908cabb4724beab3) | Memory prefetch fix — `hook_session_start_memory_prefetch.py` now queries LightRAG in `naive` mode with a 30s timeout (was `hybrid` @ 6s, which falsely reported the substrate unreachable and hard-blocked edits). Force-propagated from [`template-repo#159`](https://github.com/agorokh/template-repo/issues/159) (PR #160). No linked issue. |
| [#111](https://github.com/agorokh/ac-copilot-trainer/pull/111) | `2026-05-20T04:58:54Z` | [`8d34073`](https://github.com/agorokh/ac-copilot-trainer/commit/8d3407301f825cad7ca205b69160ab87d190780a) | [#108](https://github.com/agorokh/ac-copilot-trainer/issues/108) closeout doc (non-vault); supersedes closed [#110](https://github.com/agorokh/ac-copilot-trainer/pull/110) |
| [#109](https://github.com/agorokh/ac-copilot-trainer/pull/109) | `2026-05-20T02:43:31Z` | (squash on `main`) | #108 partial — `.cursor/rules/memory-contract.mdc` only |
| [#99](https://github.com/agorokh/ac-copilot-trainer/pull/99) | `2026-05-17T00:33:44Z` | [`ebdef7e`](https://github.com/agorokh/ac-copilot-trainer/commit/ebdef7e8d3a1ed388e914f217fc393b600162e31) | [#97](https://github.com/agorokh/ac-copilot-trainer/issues/97) session-journal loader hardening |
| [#100](https://github.com/agorokh/ac-copilot-trainer/pull/100) | `2026-05-17T00:34:09Z` | [`ac810c0`](https://github.com/agorokh/ac-copilot-trainer/commit/ac810c0fcf51352895c66f81cc1a75d3cb0d660a) | [#93](https://github.com/agorokh/ac-copilot-trainer/issues/93) PT row BB chip stale on setup switch |

Post-merge classification (#129): **`post_merge_classify.py --pr 129`** flagged only **`scripts/`** — the single change is the prefetch hook itself (`hook_session_start_memory_prefetch.py`: `hybrid`→`naive`, `6s`→`30s`). No migration / env / deps / workflow flags; no manual run required. The next SessionStart prefetch will use the new mode/timeout automatically.

Post-merge classification: **`post_merge_classify.py --pr 111`** (and #99/#100) — no migration / env / deps / script flags.

**Agent-surface campaign (#108):** Issue **closed**. Closeout: [`docs/10_Development/issue-108-agent-alignment-closeout.md`](../../../10_Development/issue-108-agent-alignment-closeout.md). Five drifted agent bodies (`dependency-review`, `issue-driven-coding-orchestrator`, `learner`, `post-merge-steward`, `pr-resolution-follow-up`) **deferred** until Steward re-dispatch — do not revert PR #109 memory-contract paths.

**What remains (rig screen EPIC #86):** Parts E–F, `start_sidecar.bat` external-bind + token, Part A4 `lv_font_conv` fonts, on-device confirmation of PT chip refresh after list batches. BB chip staleness fix is **shipped** in #100 (LVGL clear-then-set + invalidate, Lua `chipInt`, firmware `phase2_json_try_int32`); optional human rig smoke still valuable.

**Prior infra (still on `main`):** PR [#96](https://github.com/agorokh/ac-copilot-trainer/pull/96) template-2026.05 deterministic hooks (`5d3019e`). Operator notes: regenerate `.claude/settings.json` via `python scripts/merge_settings.py --no-local` when `settings.base.json` changes; commit-time pre-commit only (no PostToolUse ruff hooks).

---

## What was delivered (PR #203 — 2026-06-16)

| Area | Artefact |
|------|----------|
| Physical peripheral protocol | PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) merged at [`e5103be`](https://github.com/agorokh/ac-copilot-trainer/commit/e5103be29965b118efa309ee6f3a97a29cb329af) — adds `telemetry_tick` + `haptic_event` validation/routing, derived haptic cues, physical-client rate limiting, legacy `ac-copilot-screen-*` routing, signed slip, partial tyre maps, and protocol docs. Closes [#118](https://github.com/agorokh/ac-copilot-trainer/issues/118). |

## What was delivered (PR #197 — 2026-06-16)

| Area | Artefact |
|------|----------|
| WS lifecycle reconnect | PR [#197](https://github.com/agorokh/ac-copilot-trainer/pull/197) merged at [`392a868`](https://github.com/agorokh/ac-copilot-trainer/commit/392a8688d716a33dffad20cbf2a38a0c7ea17b90) — `ws_bridge.openEpoch()` exposes CSP socket-open epochs, stale `onOpen` callbacks are ignored, and `ac_copilot_trainer.lua` re-arms lifecycle `session` emission on epoch changes even when the connected boolean remains true. Closes [#183](https://github.com/agorokh/ac-copilot-trainer/issues/183). |

## What was delivered (PR #165 — 2026-06-13)

| Area | Artefact |
|------|----------|
| Invariant CI guard | PR [#165](https://github.com/agorokh/ac-copilot-trainer/pull/165) merged at [`1a08d45`](https://github.com/agorokh/ac-copilot-trainer/commit/1a08d45787e96e16cc660b1b5dd9fb3e4f27e598) — `tests/test_invariants_present.py` now asserts the [`secrets-from-doppler`](invariants/secrets-from-doppler.md) **Scope clause** is present, so CI reds on Scope-clause drift in this repo's own vault. Fleet-propagated from template-repo#308/#309 (pilot workstation-ops#510). Test-only; no source/runtime change. |

## What was delivered (PR #91 — 2026-04-29)

PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** `2026-04-29T17:02:22Z` as squash [`35d770c`](https://github.com/agorokh/ac-copilot-trainer/commit/35d770c7e51da021133488809d4c5dbd254e0195). **Issue #86 Parts A–D** (LVGL launcher, AC Copilot mirror, Pocket Technician + trainer/sidecar) are on `main`. Post-merge steward: `scripts/post_merge_classify.py --pr 91` reported **no** migration/env/deps/script flags.

**Still the best single read for device reality:** [screen-end-to-end-bringup-2026-04-26.md](../03_Investigations/screen-end-to-end-bringup-2026-04-26.md) (eight root causes fixed between CI-green and on-device green).

**Open follow-ups** (next PRs / issue #86 E–F):

1. **`start_sidecar.bat` loopback-only** — rig screen needs `--external-bind 0.0.0.0` + token path (see bring-up doc).
2. **Part A4 fonts** — run `lv_font_conv` for bundled TTFs; until then Montserrat 14 ASCII only.
3. **Part E / Part F** per EPIC #86 (Setup Exchange, polish/SPIFFS/debug).

**Delivered 2026-05-17 — PR #100 / issue #93:** PT row BB chips refresh after `setup.list` via `refresh_chip_label()` (clear-then-set + `lv_obj_invalidate`), integer chip JSON from Lua, shared firmware JSON int parser; tests in `tests/test_setup_library_summary.py`.

**Hotspot pitfall:** disable Windows Mobile Hotspot power-saving when AC runs (see [`wifi-hotspot-single-radio-2026-04-26`](../03_Investigations/wifi-hotspot-single-radio-2026-04-26.md)).

### Branch + PR state (PR #91)

Feature branch `feat/issue-86-rig-screen-phase2-launcher-and-apps` was deleted locally after merge. Superseded by **`main`** @ `ac810c0` (includes PRs #96–#100).

---

## Resume context (carried over from 2026-04-25 post-PR #89)

**Same-day follow-up PR [#89](https://github.com/agorokh/ac-copilot-trainer/pull/89) MERGED 2026-04-25T05:08:27Z** as squash commit `a55a0ed` on `main`. Two-line `.gitattributes` patch pinning `*.sh` and `*.bash` to `eol=lf` — fixes the Windows-checkout regression introduced by PR #87 where Git checked out shell hooks with CRLF and Bash failed `bash: root=...: No such file or directory` on `PreToolUse:Bash`. The hook fix is now live at the repo level. Same item is queued upstream as part of [`agorokh/template-repo#97`](https://github.com/agorokh/template-repo/issues/97) so the next downstream sync inherits the fix.

**Template-sync PR [#87](https://github.com/agorokh/ac-copilot-trainer/pull/87) MERGED 2026-04-24T22:12:09Z** as squash commit `ab13a71` on `main`. Synced canonical template from `template-repo@76e62d2` to `template-repo@061d9ab` (template-2026.04, 52 upstream commits) and unblocked the `issue-driven-coding-orchestrator` hook-drift bug (template-repo PR #92). The merge bundled three template-sync commits plus two unrelated vault-SAVE commits (`8353a0c`, `325983b`) that landed on the same branch in the resolution loop — those are now on `main` as well.

**Active focus has not moved.** The hot path remains rig screen Phase-2 LVGL bring-up (Stream A, EPIC #59). PR #87 was meta/infra and PR #89 is its hotfix; neither shifts the feature stream — see `Current Focus.md` Stream A for the next concrete moves.

### Upstream tracker (READ THIS BEFORE NEXT TEMPLATE SYNC)

[`agorokh/template-repo#97`](https://github.com/agorokh/template-repo/issues/97) catalogs **17+ items across 9 template files (3× P1, 2× P2)** that were *deferred* to upstream rather than fixed in this child repo to keep the sync diff template-only. Three P1s are real risks worth landing in template-repo before the next downstream sync:

1. **`scripts/post_merge_sync.sh:125`** — `gh pr merge` is not a merge guarantee (returns 0 even on auto-merge defer). The steward currently trusts the exit code; if a vault PR ever fails to actually land, this is why.
2. **`scripts/post_merge_sync.sh:170`** — force-deletes unrelated local branches when stale tracking is pruned. Could nuke a dev's WIP branch in edge cases.
3. **`scripts/check_vault_follow_up.sh`** — runs as a pre-commit hook against `--cached`, so if the staged tree is empty (no `git add`) the guard passes silently and unstaged vault edits slip through.

### Items fixed in PR #87 (not deferred)

These three fixes live in `main` now and should NOT be re-flagged on the next sync:

- `tools/process_miner/github_client.py:327` — `base64.b64decode(validate=True)` so the "text or None" contract holds for Git LFS and other non-base64 payloads (commit `53bf74f`).
- `.pre-commit-config.yaml:21` — ruff-pre-commit bumped to `v0.15.12` to match `pyproject.toml ruff>=0.15.11` (commit `2e4943c`).
- `.claude/agents/post-merge-steward.md:42-43` — canonical `ProjectTemplate` paths rewritten to `AcCopilotTrainer` (commit `2e4943c`; `copier_post_copy.py _rewrite_tree` didn't run because the sync came in as a merge PR rather than a `copier update`).

### Post-merge classification (human attention)

`scripts/post_merge_classify.py` flagged 5 areas. None block the rig screen work, but worth knowing:

- **`pyproject.toml` deps drift** — new floors / added extras: `detect-secrets>=1.5.0`, `pyyaml>=6.0.3`, `pygments>=2.20.0`, `ruff>=0.15.11`. Two new opt-in extras: `[mining-semantic]` (sentence-transformers, ~80 MB model on first run) and `[training]` (torch/transformers/trl/peft/datasets — Tier 3 Phase 2+, NOT installed in CI). Run `pip install -e ".[dev]"` in the active venv to pick up the new dev floors.
- **`.env.example` drift** — Doppler doc-block + `DISTILL_*` + `PROCESS_MINER_BOT_ALIASES_JSON` added; the AC-Copilot-specific Ollama vars (`AC_COPILOT_OLLAMA_*`) were *removed* from the example. Local `.env` files are unaffected, but if the team relies on `.env.example` as documentation, the Ollama section needs to be re-added (template doesn't know about our sidecar). **Action: consider re-adding the AC_COPILOT_OLLAMA_* block to `.env.example` as a project-specific override**, or document them in `AGENTS.md § Local development`.
- **`Makefile`** — new targets: `ci-conventional`, `ci-secrets`, `init-knowledge`, `bootstrap-knowledge`, `merge-settings`. `ci-fast` now includes `ci-conventional` + `ci-secrets`. `ci-security` narrowed from `src tools` to just `src` (template asserts `tools/` and `scripts/` produce too much bandit noise).
- **`scripts/`** — large surface added (hook_protect_main, hook_sensitive_file_guard, hook_bash_pre_tool, ci_policy, merge_settings, init_knowledge_db, bootstrap_knowledge, fleet_inventory_refresh, session_debrief, etc.). All template infrastructure; no manual run required, but the new Claude Code hooks WILL fire on the next bash/edit (deterministic flow control replacing the old "PASS" prompt hook).
- **`.github/workflows/`** — added: `codeql.yml`, `pr-pain-detection.yml`, `qodo-review.yml`, `cross-repo-mining.yml`. Modified: `ci.yml`, `post-merge-notify.yml`, `process-miner.yml`, `security.yml`, `vault-automerge.yml`. Review for permissions/secrets usage on the next PR.

### Prior streams (preserved from previous handoff)

**PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) is MERGED** at head `caa8a9ad` (2026-04-22T17:20Z). Vault post-merge handoff PR [#84](https://github.com/agorokh/ac-copilot-trainer/pull/84) also merged (17:34Z). End-to-end rig screen ↔ sidecar path confirmed working pre-merge; device emits `{v:1,type:"action",name:"toggleFocusPractice"}` every 10 s over the hotspot.

User then asked for **vault enrichment** as prep for the next phase (physical device screen development). The Stream A pre-reads (rig network, install paths, ESP32 firmware, EPIC #59, Figma) remain the right pre-load for the next screen session.

## Pre-read before starting work

Cold-start agents: read these 6 nodes first, in order. They give you 80% of the context in ~3000 words.

1. [`Current Focus`](Current%20Focus.md) — which streams are hot, what's blocked.
2. [`glossary/rig-network`](glossary/rig-network.md) — every address, token, SSID, port.
3. [`glossary/install-paths`](glossary/install-paths.md) — where AC, PT, SX, our app, factory backup live.
4. [`10_Rig/esp32-jc3248w535-screen-v1`](../10_Rig/esp32-jc3248w535-screen-v1.md) — firmware state, change log.
5. [`10_Rig/physical-rig-integration-epic-59`](../10_Rig/physical-rig-integration-epic-59.md) — the full EPIC this is one slice of.
6. [`01_Decisions/dashboard-visual-design-figma`](../01_Decisions/dashboard-visual-design-figma.md) — Figma URL + design tokens.

If you're working on screen firmware specifically, also:
- [`01_Decisions/screen-ui-stack-lvgl-touch`](../01_Decisions/screen-ui-stack-lvgl-touch.md) — LVGL 8.3 + touch bring-up plan with ready-to-paste snippets.
- [`03_Investigations/screen-debugging-journey-2026-04-21`](../03_Investigations/screen-debugging-journey-2026-04-21.md) — **dead-ends already tried. DO NOT REPEAT.**

## Concrete next moves

1. **Close issue [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81)** via `gh issue close 81 -c "Implementation landed in PR #83, merged 2026-04-22 at head caa8a9ad"`. (Leftover housekeeping from the PR #83 merge — still open per `Current Focus.md`.)

2. **(Optional) `pip install -e ".[dev]"`** in the active venv to pick up new template dev floors (`detect-secrets`, `pyyaml`, `pygments>=2.20.0`, `ruff>=0.15.11`). The next time pre-commit or `make ci-fast` runs locally, it will need these.

3. **Start the sidecar + hotspot** before any device test. PR [#78](https://github.com/agorokh/ac-copilot-trainer/pull/78) added **auto-launch** so the sidecar spawns when the trainer Lua loads; see [`pr-78-sidecar-autolaunch-lap-archive`](../03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md). For rig testing outside of AC (firmware smoke):
   ```bash
   py -m tools.ai_sidecar --external-bind 0.0.0.0 --token <T>
   ```
   **Hotspot SSID is now `AG_RIG`** (no space) on **2.4 GHz forced** + the AHOME5G profile is set to `connectionmode=manual` so it doesn't snap back and steal the radio. **Disconnect Wi-Fi from AHOME5G** (`netsh wlan disconnect`) before starting the hotspot — the Intel 7260 is single-radio so it cannot host 2.4 GHz while connected to a 5 GHz network. Full diagnosis + recovery commands: [`wifi-hotspot-single-radio-2026-04-26`](../03_Investigations/wifi-hotspot-single-radio-2026-04-26.md).

4. **Phase-2 firmware: bring up LVGL 8.3 + touch.** Follow [`screen-ui-stack-lvgl-touch`](../01_Decisions/screen-ui-stack-lvgl-touch.md):
   - `lib_deps += lvgl/lvgl @ ~8.3.11` in `firmware/screen/platformio.ini`.
   - Add `firmware/screen/include/board/JC3248W535_Touch.h` (40-line I²C reader — full snippet in the ADR).
   - Wire `lv_disp_drv_t.flush_cb` → `gfx->draw16bitBeRGBBitmap()` → `((Arduino_Canvas*)gfx)->flush()` once per ~16 ms.
   - Drop a one-screen "tap → toggle focusPractice" button — that's the end-to-end proof.

5. **Port the Figma design** screen-by-screen to LVGL. Re-use the bundled fonts from `src/ac_copilot_trainer/content/fonts/` — convert to LVGL binaries via `lv_font_conv` (Michroma 20pt for numbers, Montserrat Reg/Bold for body, Syncopate Bold for brand footer). Tokens are in [`dashboard-visual-design-figma`](../01_Decisions/dashboard-visual-design-figma.md).

6. **Add the PT/SX setup tiles.** Per [`screen-and-csp-apps-integration`](../01_Decisions/screen-and-csp-apps-integration.md): implement `src/ac_copilot_trainer/modules/setup_control.lua` that wraps `ac.getSetupSpinners()` / `ac.setSetupSpinnerValue()`, expose via WS types `setup.spinner.list/set/ack`. Rig tile renders top-3 spinners (TC, ABS, brake bias) as ± buttons.

7. **In-game verification** (once LVGL + setup tiles are in): AC running + trainer loaded + device on; tap a tile; confirm trainer state changes (focusPractice / spinner / etc.) — and watch the HUD re-render.

8. **Later phases** (out of scope this week, tracked in EPIC #59): tyre-heatmap tile, coaching-summary tile reading from per-lap archive (schema v1, see [`pr-78-sidecar-autolaunch-lap-archive`](../03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md)), real-time `corner_advice` passthrough (see [`pr-75-ollama-corner-coaching-protocol`](../03_Investigations/pr-75-ollama-corner-coaching-protocol.md)).

## Key learnings carried over

From [`screen-debugging-journey-2026-04-21`](../03_Investigations/screen-debugging-journey-2026-04-21.md) and prior investigations:

1. **AXS15231B QSPI** panels need `Arduino_Canvas` + `flush()` — per-pixel writes garble the controller. Use `ips=false` for the 320×480 LCD variant.
2. **JC3248W535 touch IS the AXS15231B** at I²C 0x3B — no separate touch IC. 40-line reader in the ADR.
3. **moononournation init table** is for the 1.91" AMOLED, not our LCD.
4. **AHOME5G mesh** segregates per-AP subnets; TCP dropped cross-AP. Hotspot is the dev path.
5. **Factory backup restore** is the proof-of-life test when display looks dead. Binary at `firmware/screen/_factory-backup/jc3248w535_v0.9.1_factory.bin`.
6. **CSP API quirks**: `type(vec2/rgbm)` returns `"cdata"` not `"function"` (use nil-checks); `web.socket` is callback-based (`reconnect:true` mandatory); `ac.storage` table-form silently fails (use per-key form).
7. **Sim-time not os.clock** for staleness — see `ac-storage-persistence.md` and the `corner_advice` TTL in PR #75.

## What was delivered (2026-04-29)

| Area | Artefact |
|------|----------|
| Rig screen Phase-2 (EPIC #86 A–D) | PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) merged at [`35d770c`](https://github.com/agorokh/ac-copilot-trainer/commit/35d770c7e51da021133488809d4c5dbd254e0195) — LVGL 8.3 portrait UI, launcher, AC Copilot + `coaching.snapshot`, Pocket Technician + `setup.list`/`setup.load`, `setup_library` / `ws_bridge` / `lap_archive` / `ac_content_meta`, sidecar protocol + `long_cmd_fix_post` Windows `ar` batching, vault bring-up + glossary nodes bundled in the same squash. |

## What was delivered (2026-04-25)

| Area | Artefact |
|------|----------|
| Hook hotfix | PR [#89](https://github.com/agorokh/ac-copilot-trainer/pull/89) merged at `a55a0ed` — `.gitattributes` pins `*.sh` / `*.bash` to `eol=lf`, fixing the Windows CRLF hook misfire from PR #87. Same item tracked upstream in [`agorokh/template-repo#97`](https://github.com/agorokh/template-repo/issues/97). |

## What was delivered (2026-04-24)

| Area | Artefact |
|------|----------|
| Template sync | PR [#87](https://github.com/agorokh/ac-copilot-trainer/pull/87) merged at `ab13a71` — 52 upstream commits incl. orchestrator hook-drift root-cause fix (template-repo PR #92). |
| Hooks (deterministic flow) | New `scripts/hook_protect_main*.sh|.py`, `scripts/hook_sensitive_file_guard.sh`, `scripts/hook_bash_pre_tool.sh`. Old `PostToolUse:Bash "PASS"` prompt hook gone; only 2 advisory prompt hooks remain (LOAD reminder, SQL DDL guard). |
| Skills delivered | `orchestrate`, `resolve-pr`, `post-merge`, `dependency-review`, `learner`, `ci-check`, `new-project-setup`, `release-notes`, `github-issue-creator` (Claude Code + Cursor). |
| Steward automation | `.claude/agents/post-merge-steward.md` + `scripts/post_merge_sync.sh` (sync/vault phases) + `.github/workflows/vault-automerge.yml`. |
| In-PR fixes | `tools/process_miner/github_client.py` `validate=True`; `.pre-commit-config.yaml` ruff bump to v0.15.12; steward path rewrite to `AcCopilotTrainer`. |
| Upstream tracker | `agorokh/template-repo#97` filed (17+ deferred items, 3× P1, 2× P2). |
| Post-merge handoff | This handoff updated (PR #87 → MERGED), `Current Focus.md` retired Stream T. |

## What was delivered (2026-04-22)

| Area | Artefact |
|------|----------|
| MCP infra | TurboVault + 6 MCP servers installed, Doppler wired (`~/Projects/mcp-work/mcp-servers`) |
| Vault enrichment | 7 new nodes: EPIC #59 expansion, Figma ADR, debugging-journey, Cowork retrospective, PR #78 & PR #75 coverage, glossary rig-network + install-paths |
| Vault updates | Current Focus (PR #83 MERGED state), both `_index.md`s, esp32 change log, glossary `_index`, this handoff |
| PR reviews | PR #83 closure audit (0 unresolved); PR #84 vault handoff merged |

## Blockers / dependencies

- Hotspot must be on for any live device test.
- AC user-data folder path still TBD (probably under `OneDrive\Documents\Assetto Corsa\` or `%APPDATA%\Assetto Corsa\`) — tagged in [`install-paths`](glossary/install-paths.md). Verify before the sidecar file-watch work.
- No router admin access to remove cross-AP block, so hotspot is the long-term dev path.
