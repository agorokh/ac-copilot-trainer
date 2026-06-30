---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-06-30T22:23:39Z
relates_to:
  - AcCopilotTrainer/03_Investigations/pr-410-racing-atelier-design-package-2026-06-30.md
  - AcCopilotTrainer/03_Investigations/pr-394-voice-reliability-2026-06-30.md
  - AcCopilotTrainer/03_Investigations/voice-368-merge-contention-2026-06-29.md
  - AcCopilotTrainer/03_Investigations/tt-services-sigv4-crack-2026-06-29.md
  - AcCopilotTrainer/03_Investigations/issue-86-rig-screen-hotspot-autostart-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-365-game-point-launcher-2026-06-29.md
  - AcCopilotTrainer/03_Investigations/pr-359-tt-ingest-mtt0-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-355-m0-merge-collision-and-350-reconciliation-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/duckdb-over-clickhouse-storage-2026-06-29.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/issue-327-vault-automerge-already-resolved-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-multitrack-generality-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/issue-277-rig-verify-prepped-blocked-concurrency-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/issue-308-worktree-memory-gate-resolved-2026-06-25.md
  - AcCopilotTrainer/03_Investigations/pr-309-lap-archive-finalization.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/03_Investigations/frontier-controller-ggv-2026-06-19.md
  - AcCopilotTrainer/03_Investigations/stanley-steering-live-verified-2026-06-19.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/03_Investigations/racing-driver-and-controller-2026-06-17.md
  - AcCopilotTrainer/03_Investigations/cm-url-deelevated-launch-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/autonomous-drive-live-verified-2026-06-16.md
  - AcCopilotTrainer/03_Investigations/issue-188-wrap-skew-rig-verification.md
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
  - AcCopilotTrainer/03_Investigations/pr-310-trail-brake-attribution-handoff.md
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
  - AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md
  - AcCopilotTrainer/03_Investigations/pr-338-coaching-hardening-handoff.md
  - AcCopilotTrainer/01_Decisions/curated-setup-as-data-platform-entity-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/setup-intelligence-platform-2026-06-29.md
  - AcCopilotTrainer/03_Investigations/curated-setup-hash-bridge-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-399-coach-v2-review-loop-2026-06-30.md
  - AcCopilotTrainer/03_Investigations/porsche-911-gt3r-magione-balanced-setup-2026-06-28.md
---

# Next session handoff

## Delivered (2026-06-30) - PR #419 MERGED: driver progression profile (#403)

PR [#419](https://github.com/agorokh/ac-copilot-trainer/pull/419) squash-merged to `main` as
[`14f6257`](https://github.com/agorokh/ac-copilot-trainer/commit/14f625775863f44f03cf7685b7e8918f53492321)
at 2026-06-30T22:21:09Z. Issue [#403](https://github.com/agorokh/ac-copilot-trainer/issues/403)
is **CLOSED**.

**Shipped:** Coach v2 now has a longitudinal driver progression layer on top of the compacted
profile ledger from #402. `tools.ai_sidecar.driver_progression` classifies skills and selects
foundation/intermediate/advanced cue policies and drills. The live runtime scopes profile history
to the active reference car/track/layout before deriving cue density, and falls back to the baseline
policy when reference combo metadata is missing. `AC_COPILOT_DRIVER_PROFILE` is documented as the
override for the persisted `journal/driver/profile.json` runtime state.

**Review hardening:** Bot review drove fail-closed profile path containment, imported/reference lap
skips, idempotent rebuilds, same-session incremental merges, corner sample de-dupe, median sample
gating, exact per-lap corner medians, active-combo filtering, chronological endpoint ordering, and
UUID normalization across overlapping lap corpora. Qodo's remaining summary-only notes on corner
derived stats and sample gating were stale against current code/tests; its tiers note was answered
as a runtime telemetry-state false positive, not agent memory.

**Verification:** GitHub checks on head `9149930` passed (`build`, `Canonical docs exist`,
`conformance`; vault automerge skipped). GraphQL review threads were resolved; Gemini and Codex
review reruns were quota-limited after earlier passes, so current thread state plus Qodo's updated
summary were used as the final gate. Local focused regression passed (`82 passed`) across driver
profile/progression, Coach v2 runtime, observer wiring, and retention. Ruff check/format, policy,
diff whitespace, Bandit, secret scan, policy docs, agent-forbidden, CSP API, and CSP UI checks were
clean, with only existing root-file allowlist warnings for `.copier-answers.yml` and `doppler.yaml`.
Local `make ci-fast` could not be used as a single command in the Windows checkout because the
repo-wide formatter target wants to reformat unrelated baseline files; the changed-file formatter
and all runnable component gates passed. Post-merge classification: `.env.example` changed for the
new documented `AC_COPILOT_DRIVER_PROFILE`; no migration/dependency/workflow action required.

## Delivered (2026-06-30) - PR #418 MERGED: sector benchmarks + SuperLap targets (#408)

PR [#418](https://github.com/agorokh/ac-copilot-trainer/pull/418) squash-merged to `main` as
[`17aa36b`](https://github.com/agorokh/ac-copilot-trainer/commit/17aa36b3db0284068cf4cb6ca8cae42f0b5b8190)
at 2026-06-30T21:42:47Z. Epic [#408](https://github.com/agorokh/ac-copilot-trainer/issues/408)
stays **OPEN**: this PR delivers the sector/micro-sector and SuperLap benchmark slices; Track Titan
M-TT3 (#353) and fuller reference-library management remain epic work.

**Shipped:** Added `tools.ai_sidecar.sector_benchmark` for deterministic sector/micro-sector
windows, complete-only sector delta reports, and complete-only stitched SuperLap targets. The
post-lap debrief now emits sector deltas and SuperLap structures, `protocol.py` forwards them as
`sectorDeltas` / `superLap`, and Lua HUD/delta modules surface sector-loss/gain toasts using
stable segment windows. Benchmark payload indices are 1-based to match labels and Lua helpers.

**Review hardening:** The benchmark path now refuses partial SuperLaps and partial sector totals,
does not invent unsampled interior segment edges, uses explicit `lap_ms` only for true 0/1 archive
boundaries, filters invalid current/reference laps out of benchmarks, scopes reference/corpus laps
by car, track, and raw `track.layout`, and keeps Windows CLI help ASCII-safe.

**Verification:** GitHub checks on head `1d4405b` passed (`build`, `Canonical docs exist`,
`conformance`; vault automerge skipped). Required review cooldowns were observed after each push;
all GraphQL review threads are resolved. Local full parity in
`C:\Users\arsen\Projects\ac-copilot-trainer-issue408-ci` passed with
`make ci-fast PYTHON=python` (`2001 passed, 77 skipped`, coverage 85.47%, `ci-fast: OK`; root-file
allowlist warnings only for existing `.copier-answers.yml` and `doppler.yaml`). Focused sidecar/HUD
regression slice passed (`94 passed`). Post-merge classification: no migration/env/deps/script/workflow
flags.

## Delivered (2026-06-30) - PR #415 MERGED: telemetry data platform (#402)

PR [#415](https://github.com/agorokh/ac-copilot-trainer/pull/415) squash-merged to `main` as
[`c407d46`](https://github.com/agorokh/ac-copilot-trainer/commit/c407d46820974e37554b1b3c29317cc8459d7f76)
at 2026-06-30T20:46:36Z. Issue [#402](https://github.com/agorokh/ac-copilot-trainer/issues/402)
is **CLOSED**.

**Shipped:** The coaching lake now materializes first-class `sessions` and `stints` rollups in
DuckDB, with `sessions` / `stints` reports. `tools.ai_sidecar.driver_profile` maintains a compacted
`journal/driver/profile.json` ledger with preferences, focus corners, session rollups, PBs, and
consistency summaries so driver history survives raw-lap pruning. `tools.coaching_lake.retention`
adds dry-run-first lifecycle planning/apply for `journal/laps` and `journal/tt`, preserving PB,
reference, profile-ledger, pinned, and unreadable evidence. `tools.lap_archive_export --output -`
streams CSV to stdout for live export bridges. Docs landed in
`docs/10_Development/16_Telemetry_Data_Platform.md` plus the lap-archive export docs.

**Review hardening:** Retention/profile safety now fails closed on invalid existing profile ledgers,
merges partial session rebuilds without discarding older compacted bests, rejects negative retention
caps, and invalidates TT derived indexes after TT raw deletions. `scripts/mcp/agentic-memory.sh`
also normalizes Windows drive-letter paths under Git Bash, fixing local `ci-fast` parity when Bash is
present on Windows.

**Verification:** GitHub checks on head `63ba78d` passed (`build`, `Canonical docs exist`,
`conformance`; vault automerge skipped). Required review cooldowns were observed; GraphQL review
threads are resolved; no current-SHA self-hosted reviewer body was present after the final cooldown.
Local full parity in the clean LF checkout
`C:\Users\arsen\Projects\ac-copilot-trainer-ci-402-lf` passed with
`make ci-fast PYTHON=python` (`1977 passed, 76 skipped`, coverage 85.59%, `ci-fast: OK`; root-file
allowlist warnings only for existing `.copier-answers.yml` and `doppler.yaml`). Focused slice passed
(`47 passed`) across coaching lake, driver profile, retention, lap export, and agentic-memory wrapper
tests. Scratch CLI smoke built a synthetic lake with `laps=3`, `sessions=2`, `stints=2`, wrote a
driver profile with 2 session rollups / 1 PB, selected only the old non-PB lap for retention, and
streamed 9 CSV rows to stdout.

**Post-merge classification:** `scripts/` changed due the agentic-memory wrapper hardening; no
migration/env/deps/workflow action required.

## Delivered (2026-06-30) - PR #416 MERGED: race management cues (#406)

PR [#416](https://github.com/agorokh/ac-copilot-trainer/pull/416) squash-merged to `main` as
[`9832004`](https://github.com/agorokh/ac-copilot-trainer/commit/983200453d06ff5469165d5bcc9cc115feb0d7cc)
at 2026-06-30T20:44:26Z. Issue [#406](https://github.com/agorokh/ac-copilot-trainer/issues/406)
is **CLOSED**.

**Shipped:** Added `tools.ai_sidecar.race_management.RaceManagementObserver` for stint-level
`fuel_status` / `fuel_save`, `tyre_manage`, `brake_manage`, and `conditions_strategy` advisories.
The observer rides alongside Coach v2 or the legacy realtime observer in `server.py`, reuses the
existing tyre and conditions models, and emits through the existing `coaching.cue` / voice pipeline.
Lua `telemetry_tick` payloads now carry fuel level/capacity and per-corner tyre core temps when
available, and `external_protocol.py` validates the new race-management channels. Voice vocabulary
and cue mapping include short action phrases for fuel saving, tyre saving, brake cooling, and
conditions strategy. A Windows help-output CI failure was also fixed by changing the
`car_schema.py --help` description to ASCII-safe `->`.

**Review hardening:** Qodo found two real edge cases and both were fixed before merge:
critical tyre escalation no longer reuses the firm-overheat dedupe classification, and fuel samples
reset/reseed on lap-counter rollback so a new stint cannot inherit stale burn-rate estimates.

**Verification:** GitHub checks on head `fe95758` passed (`build`, `Canonical docs exist`,
`conformance`; vault automerge skipped). GraphQL review threads are resolved; resolve-gate reports
`No substantive findings hanging`; no current-SHA self-hosted reviewer body was present after the
required cooldowns. Local focused verification passed (`105 passed`) across race management,
protocol validation, server fan-out, voice phrasing, Lua telemetry publishing, and the Windows
`car_schema.py --help` smoke. Local Windows CI parity required an LF checkout plus
`FLEET_GOVERNANCE_ROOT=C:\Users\arsen\Projects\governance-hub`; full pytest reached
`1929 passed, 117 skipped`, coverage 85.51%, and the bash-backed secret/policy wrappers were run by
equivalent PowerShell checks because `bash` is not on PATH. Post-merge classifier: no migration /
env / deps / script / workflow flags.

## Delivered (2026-06-30) - PR #410 MERGED: Racing Atelier design package (#400)

PR [#410](https://github.com/agorokh/ac-copilot-trainer/pull/410) squash-merged to `main` as
[`d669b19`](https://github.com/agorokh/ac-copilot-trainer/commit/d669b19c001e79b751ad625599a82c32e9ce38f8)
at 2026-06-30T19:19:18Z. Issue [#400](https://github.com/agorokh/ac-copilot-trainer/issues/400)
is **CLOSED**.

**Shipped:** Preserved the Racing Atelier handoff package under
`docs/10_Development/design/racing-atelier/`, added the rendered target gate under
`docs/10_Development/design/racing-atelier-renders/`, removed the retired AG Porsche Academy
design components, and documented the new design source of truth. Review fixes added offline
reliability / third-party JS/font warnings and narrowed prototype `postMessage` target origin
from unconditional `"*"` to the referrer origin when available. Post-merge classification found no
migration/env/deps/script/workflow flags.

**Verification:** GitHub checks passed (`build`, `Canonical docs exist`, `conformance`,
`classify`, `score`; vault automerge skipped). Local `python -m pytest
tests/test_design_conformance.py` passed (`21 passed`). ZIP reconciliation against
`C:\Users\arsen\Downloads\Racing Atelier-handoff (1).zip`: all 95 expected package files are
present in repo; 80 hash differences are newline-only from `core.autocrlf=true`; the remaining
drift is the intentional PR hardening above (`fonts.css`, `readme.md`, four `support.js` files)
plus the reviewed Track Atlas thumbnail. Browser verification loaded the committed Game Point,
in-game HUD, and ESP32 rig kits via a temporary `127.0.0.1` static server; all rendered with the
Racing Atelier carbon/brass/brake/lift/clear palette, square instrument geometry, segment bars /
delta blocks, and no console errors beyond the known Babel CDN warning documented by the PR.
Detail: [[pr-410-racing-atelier-design-package-2026-06-30]].

## Delivered (2026-06-30) — PR #399 MERGED: Coach v2 (#396)

PR [#399](https://github.com/agorokh/ac-copilot-trainer/pull/399) squash-merged to `main` as
[`e41383e`](https://github.com/agorokh/ac-copilot-trainer/commit/e41383ebc600649ea429bbf72f641dd4a7072b28).
Issue [#396](https://github.com/agorokh/ac-copilot-trainer/issues/396) is **CLOSED**.

**Shipped:** Coach v2: real-time diagnosed, anticipatory in-ear coaching (replace post-hoc delta reporter).
Detail: [[pr-399-coach-v2-review-loop-2026-06-30]].

## 2026-06-30 — PLAN BRUSH-UP: product roadmap + themed backlog filed

Restructured the repo plan from the ad-hoc "Stream A–D + residuals" changelog into a
forward-looking roadmap. New durable node: [Roadmap.md](Roadmap.md). New GitHub backlog:
umbrella [#401](https://github.com/agorokh/ac-copilot-trainer/issues/401) + themed epics
[#402](https://github.com/agorokh/ac-copilot-trainer/issues/402)–[#408](https://github.com/agorokh/ac-copilot-trainer/issues/408)
(data platform · driver model/curriculum · session review · diagnosis depth · tyre/brake/fuel
mgmt · setup↔feedback · reference depth). Existing #86/#117/#154/#353/#381/#396/#400 reconciled
under their verticals; `Project State.md` refreshed off its template stub. Key finding:
real-time + per-lap coaching is deep/shipped; the **longitudinal** layer (driver model,
progression, review, retention) is the frontier. #396 (Coach v2 anticipatory) is **largely
already shipped** — reconcile via #405 Part 0. Design-language #400 restructured so rig
firmware stays owned by #86. **Vault files (`Roadmap.md`, `Project State.md`, this handoff)
written locally on branch `claude/nice-hamilton-bf6228`; not yet PR'd** — ship via a
`vault-only` PR when ready.

## Delivered (2026-06-30) — PR #394 MERGED: voice reliability for packaged Game Point (#392)

PR [#394](https://github.com/agorokh/ac-copilot-trainer/pull/394) squash-merged to `main` as
[`b14c984`](https://github.com/agorokh/ac-copilot-trainer/commit/b14c9842c9c9fcea5bae0b17d6ad5f221e9b02dc)
at 2026-06-30T08:33:34Z. Issue [#392](https://github.com/agorokh/ac-copilot-trainer/issues/392) is
**CLOSED**.

**Shipped:** sidecar `/health` now includes path-safe `voice` runtime state; Game Point launcher
uses that health payload as the source of truth for voice status instead of treating configured paths
as proof that the coach initialized. Launcher status now catches disabled/stale schema-v1 banks,
adopted sidecars that were started without voice config, missing old `voice` health payloads, and
observer-only sidecars when playback was requested. PyInstaller packaging collects the installable
voice runtime floor (`numpy`, `sounddevice`, `pyttsx3`) and opportunistically collects opt-in
`rtmixer`/`pa_ringbuffer` only when installed. The pyttsx3 fallback waits for worker startup before
reporting `tts` enabled.

**Verification:** local `make ci-fast PYTHON=/Users/arseny_gorokh/Projects/ac-copilot-trainer/.venv/bin/python`
passed on the final head (`1893 passed, 75 skipped`, coverage 85.43%, `ci-fast: OK`). Focused
launcher/sidecar/voice tests passed (`96 passed`). GitHub checks on `be2fb50` passed (`build`,
`Canonical docs exist`, `conformance`; vault automerge skipped). Required review cooldowns were
observed through 2026-06-30T08:24:15Z; current non-outdated review threads were resolved; no
current-SHA review body landed after the final cooldown.

**Runtime proof:** Windows `pc` packaged proof was captured before the later review-fix commits:
`C:\Users\arsen\Projects\ac-copilot-trainer-issue392` built
`dist\AC-Copilot-Game-Point.exe` with PyInstaller 6.21.0 at head `4d5a610`; the frozen exe loaded a
schema-v2 tone bank with `/health.voice.state=enabled` using `sounddevice`, and a stale schema-v1 bank
reported `DISABLED` through both frozen sidecar and frozen launcher with no module import errors.
After the final review-fix commits, `pc` was offline in Tailscale (`100.75.251.87`, last seen ~31m
before closeout) and SSH timed out, so final Windows rerun was not available. Final-head local runtime
smoke with real sidecar processes + launcher CLI covered the changed logic: stale schema-v1 bank
surfaces `DISABLED`, no-voice sidecar adoption is `DISABLED`, and missing-reference health does not
leak local paths. Details: [[pr-394-voice-reliability-2026-06-30]].

## Delivered (2026-06-30) — PR #395 MERGED: M-TT2 Track Titan reference archive builder (#353)

PR [#395](https://github.com/agorokh/ac-copilot-trainer/pull/395) squash-merged to `main` as
[`b122e1b`](https://github.com/agorokh/ac-copilot-trainer/commit/b122e1becbfaaa9d028c01b924a4a6b8db50614d)
at 2026-06-30T08:29:43Z. This delivers the #353 **M-TT2** local bridge from retained Track Titan
services telemetry into schema-v1 `lap_archive` references for the M0 voice-coaching observer.

**Shipped:** `tools.tt_ingest.tt_normalize.build_reference_archive` maps TT frames into archive trace
fields (`dist` -> `spline`, `Kmh` -> `speed`, `lTime` -> `eMs`, pedals clamped to `[0,1]`, TT `X/Y`
preserved as `px/pz` with `py=0`), deterministically merges multiple retained windows, validates one
source session/lap plus reference-lap identity, rejects large spatial gaps, and treats reference-lap
time mismatches as partial. `python -m tools.tt_ingest reference` now builds archives from explicit
retained inputs or scoped lake discovery (`--discover-lake --session-key ... --lap ...`). Same-lap
`/last-session` captures are retained as deterministic `last_session_lapN_window_<fingerprint>.json`
files after the first canonical file, so repeated segment-window captures are discoverable without
overwriting write-once evidence. Debug partial archives carry `generator.tt_reference.partial=true`,
coverage/timing diagnostics, and are rejected by `build_observer_from_reference`.

**Review hardening:** addressed Codex/Gemini/Qodo findings for dict-shaped car IDs, start/finish wrap
coverage, disjoint windows, malformed services envelopes, referenceLap lap metadata, scoped lake
discovery, segment-window discovery, partial-runtime guard, output write errors, and `--overwrite`
attempts that would corrupt retained TT input files. GitHub checks on `b6fcbaf` passed (`build`,
`Canonical docs exist`, `conformance`; vault automerge skipped), `ci_resolve_gate.py` reported
`No substantive findings hanging`, and all current review threads were resolved after the required
cooldowns.

**Verification:** clean worktree
`make ci-fast PYTHON=/Users/arseny_gorokh/Projects/ac-copilot-trainer/.venv/bin/python` passed on
`b6fcbaf` (`1907 passed, 75 skipped`, coverage 85.47%, `ci-fast: OK`). Focused tests:
`tests/test_tt_normalize.py`, `tests/test_tt_ingest_cli.py`, `tests/test_tt_reference_runtime_guard.py`,
and `tests/test_realtime_observer.py` passed (`79 passed`). Manual CLI trap: the one-segment TT
fixture is rejected in strict mode; `--allow-partial` emits a schema-valid debug archive marked
partial and the live observer refuses to install it.

**What remains on #353:** issue [#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)
stays **OPEN**. M-TT0/M-TT1/M-TT2 are now merged, but M-TT3 still needs the per-corner analysis ->
harness curriculum/oracle work. Production M-TT2 use also still depends on collecting enough real TT
segment windows (or finding a full-lap endpoint) for strict mode to produce a non-partial reference;
the code intentionally refuses to fake a full lap from one `/last-session` segment window.

## Resolved (2026-06-30T00:53:41Z) — PR #389 setup-schema review loop

PR [#389](https://github.com/agorokh/ac-copilot-trainer/pull/389) is OPEN and review-resolved on head
`8e8011b` (`feat/issue-388-setup-schema-foundation`). CI is green on the head SHA (`build`,
`Canonical docs exist`, and `conformance` passed; `guard-and-automerge` skipped as expected). Local
`make ci-fast PYTHON=/Users/arseny_gorokh/Projects/ac-copilot-trainer/.venv/bin/python` passed after
the review fixes (`1871 passed, 75 skipped`, coverage 85.27%).

Review fixes shipped in two commits: `f0b45c9` covered decode-affecting `schema_hash` fields, direct
script execution, enum decode misses, step-grid clamp bounds, unchanged read-only optimizer fields,
and the new SIP ADR index link; `8e8011b` covered live `unit` propagation through
`setup_model.from_spinners`, enum `itemValues` validation as raw values, `.VALUE` schema lookup
normalization, boundary candidate clamping before optimizer filtering, and car/track id threading for
live spinner captures. GraphQL review threads were resolved after those fixes; `ci_resolve_gate.py`
reported `No substantive findings hanging` for PR #389. No current-SHA
`ws-ops-cursor-reviewer[bot]` review body was present after the required cooldown, so the self-hosted
reviewer gate is vacuously satisfied.

## In flight (2026-06-29T18:42:58Z) — PR #371 voice-intensity resolution for #368

PR [#371](https://github.com/agorokh/ac-copilot-trainer/pull/371) is still OPEN. The branch has been
merged with `origin/main` (`669eba7`) and has local review-resolution commits after that merge. It
preserves the #368 voice-intensity work, the PR #372 batch-bake/48 kHz defaults, and the parallel
process-miner/vault updates from `main`.

Codex findings addressed after the merge: pyttsx3 register rate/volume now uses configured base
knobs as the center; the standalone WS voice client no longer requires fallback-only
`AC_COPILOT_VOICE_TTS=1`; legacy `act` advisories without an explicit register resolve to the
playable firm clip instead of going silent; and post-apex brake-release cues can escalate from calm
to firm if the driver stays heavy on the brake. Later timing/bake findings are also fixed locally:
timing reports require the critical brake alarm clip to be spoken, long-track injected frames scale
from speed/frame-rate/track length, Piper batch bakes preserve register `--length_scale`, and
`voice-bake` keeps `kokoro-onnx` behind a Python `<3.14` marker so the extra remains installable on
this repo's advertised 3.14 runtime. Latest local fixes also reset first-corner previous-lap cue
state before a wrapped lead window, defer post-apex release cues until a still-playing brake alarm
finishes, drive timing reports one frame past corner exit so LOW verbosity proves info suppression
non-vacuously, require anticipatory assertions to be based on spoken cues, and make the prosody chain
resample backend-native Piper/Kokoro WAVs to the requested bank rate before applying critical
tempo/pitch shaping.

Focused verification after these fixes: voice client/resolver/observer/scheduler/engine suite
passed (`66 passed`); voice bake/timing/resolver/observer suite passed (`58 passed`); synthetic
timing-report CLI exits 0 and asserts `critical_brake_alarm_spoken: true`; latest
observer/scheduler/timing/bake focused suite passed (`82 passed`) and timing-report CLI now emits
real `apex_deficit` info advisories while keeping them unspoken under LOW; after the Piper
source-rate fix, `tests/test_voice_bake.py` passed (`17 passed`) and ruff is clean on the touched
bake files. Full local `make ci-fast PYTHON=.venv/bin/python` passed at head `06153a3` before this
latest Qodo fix; rerun full CI after committing it, push, trigger reviewers, observe the 10-minute
cooldown, then inspect GitHub checks plus current-head review threads. Detailed merge-contention
notes: [[voice-368-merge-contention-2026-06-29]].

## Delivered (2026-06-29) — PR #372 MERGED: #350 Part B voice-bake (batch Piper + 48 kHz default)

PR [#372](https://github.com/agorokh/ac-copilot-trainer/pull/372) squash-merged to `main` as
[`e0c93fd`](https://github.com/agorokh/ac-copilot-trainer/commit/e0c93fd09d6f36ac4574c5f843aa07a85a47060e)
at 2026-06-29T17:10:35Z via `/autonomous-deliver 350`. **#350 is now CLOSED** — the rig-gated audible
smoke was verified live on the rig (see VERIFIED below); follow-up voice work → #381.

**Reconciliation (issue body was stale).** #350 **Part A** (Lua `telemetry_tick` producer with
`spline`) ALREADY SHIPPED in `telemetry_publisher.lua` (commit `84b5698`, #341/#342) — the issue's
"`git grep telemetry_tick src/` → empty" premise is no longer true. **Part B** draft PR #372 was
~80% **subsumed by #363** (Game Point launcher), which independently landed the `server.py` voice
device/host-api/verbosity wiring, the `playback.py` rtmixer duration-completion fix, and `bake.py`
`_normalize_wav` resampling. Council (4/4) + an adversarial review workflow agreed: salvage PR #372 to
its genuine net-new and **keep main's shipped rtmixer fix** (dropped #372's actions-membership variant).

**Shipped (`bake.py` only):** batch Piper baking (`PiperBackend.synthesize_many` — one process;
**falls back to per-clip** on any failure with stdin closed; **numeric** timestamp sort, not lexical;
`shutil.move` cross-device); default bake samplerate **22050→48000** (WASAPI shared-mode); codepage-safe
`->` in CLI. Bot review converged: Codex 3×P2 (MIT-piper hang, silent lexical-sort mis-map, cross-volume
move) + 1 test-env P2 + Qodo numpy-reliability — **all fixed**; Qodo `--out` "rule violation" **rebutted +
resolved** (operator-run offline CLI, no untrusted input, pre-existing & unchanged by the diff).
Classification: no migration/env/deps/script/workflow flags.

During this PR #371 merge, the #372 bake path was reconciled with #371's register/prosody model:
batch items carry `(text, register, target)`, Piper batch output is shaped per register, and the
Kokoro/say-expressive/manifest validation work remains intact.

**Local verification (m5):** real 48 kHz bake (126 clips, all 48000 Hz, codepage-safe CLI); full
`telemetry_tick` → `RealtimeObserver` → `coaching.cue` advisory → `VoiceCoach` chain dispatches the
correct clip (`apex_deficit.info.t01`) from the real bank; voice-bake suite is **stdlib-only** (7
passed / 2 numpy-skipped with numpy absent, mirroring `.[dev]`).

**VERIFIED — on-rig audible smoke (2026-06-29, operator confirmed hearing the cues → #350 CLOSED).**
SSH works as **`ssh arsen@100.75.251.87`** (the Windows user is **`arsen`**, not `arseny`; the
`mac-to-ag-pc` / `id_ed25519` key is authorized for that user — earlier "Rig SSH unavailable" notes
were just the wrong username). **Root cause of the prior failing smoke (found + fixed):** a separate
`C:\Users\arsen\Projects\ac-copilot-trainer-issue350-smoke` checkout ran an **old sidecar with the
`rtmixer.done` bug** (`AttributeError: cdata 'struct action *' has no field 'done'` in
`playback.py`) that **crashed on every voice dispatch**, and its configured bank was
**vocabulary-drifted** (126-clip, hash mismatch → coach disabled). **Fix:** ran the sidecar from
current `main` (duration-based playback, no `.done`) + a freshly-baked vocabulary-matched 48 kHz
Piper bank (`C:\Users\arsen\.scratch\onrig-bank48k`, 46 clips, `piper:en_US-lessac-medium+ff8+prosody1`,
baked on-rig in **16 s** via the new batch path; **installed ffmpeg** (Gyan.FFmpeg) for the prosody
shaper). Stood it up as a **persistent interactive scheduled task `AcVoiceSidecar`** on 8765 — log
confirms `realtime observer wired from reference` (Magione / 911 GT3 R, 1:17.8), `rtmixer stream open
on device index 18 @ 48000 Hz` (WASAPI USB), `in-process voice coach wired`, no drift/crash. Replayed
a slower Magione lap's `telemetry_tick` (note: **clamp `steer` to [-1,1]** — the autonomous-artifact
lap had out-of-range steer that `validate_inbound` rejects) → observer published `coaching.cue`
(tapped) and the VoiceCoach **spoke** them through the WASAPI device: `apex_deficit` T1/T2/T3 +
`late_brake "Brake point for T4 coming up — brake."`. Also: a baked cue played 3× through WASAPI @
48 kHz; the standalone telemetry→observer→VoiceCoach→rtmixer chain spoke a computed cue.

**Rig state left running:** ffmpeg installed; the main repo (`C:\Users\arsen\Projects\ac-copilot-trainer`)
pulled to current `main`; the **`AcVoiceSidecar` scheduled task runs the voice-enabled sidecar on 8765**
(it replaced the prior no-voice `-m tools.ai_sidecar` PID 25984 — an improvement for coaching; revert
by stopping the task + relaunching the launcher's sidecar if the no-voice setup is wanted).

**Follow-up → [#381](https://github.com/agorokh/ac-copilot-trainer/issues/381):** operator heard the
cues but wants (a) a more expressive race-engineer **persona** (the "Verstappen/Hamilton" reference is
style, not a literal — legally-inadvisable — clone) and (b) **importance-scaled intensity** (urgency in
*tone*, not just speed). Builds on #368/#371's register/prosody foundation. Feasibility researched
(web-grounded) in the #381 body.

## Delivered (2026-06-29) — PR #370 MERGED: M-TT1 Track Titan services crack (#353)

PR [#370](https://github.com/agorokh/ac-copilot-trainer/pull/370) merged to `main` as squash
commit [`26e9a09`](https://github.com/agorokh/ac-copilot-trainer/commit/26e9a09eb943fca8bae3e65e80b79945ac5c421c)
at 2026-06-29T16:15:20Z (milestone **M-TT1** of #353).

**The crack (corrects the prior SigV4 hypothesis):** TT `services.tracktitan.io` `/api/v2/*`,
`/dynamic-reference-laps/*`, `/advice/*` authenticate with the **raw Cognito access token** (no
`Bearer`) — the same token vulcan uses; **no SigV4 / Identity-Pool flow needed**. The research
node's 403s were the **idToken** on **old cached paths**. Verified live from our own mint path
(accessToken→200, idToken→403) via CDP capture of the running renderer. Full detail +
reusable method + the M-TT2 telemetry schema in [[tt-services-sigv4-crack-2026-06-29]].

**Shipped:** `tools/tt_ingest/tt_services.py` (services client — pure builders/parsers, network
no-cover) + `coaching` CLI that retains per-lap raw evidence (`last_session_lap{N}.json` +
`coaching_lap{N}.json`: full raw `/last-session`, `dynamic-reference-laps`, and per-segment
`/advice` responses) to the write-once lake, reindexed; sanitized fixtures + 55 unit tests.
Reviewed by codex + qodo across 5 rounds (qodo's SigV4 finding rebutted with live evidence;
Gemini at quota). Verified live E2E: `python -m tools.tt_ingest coaching` returned real
per-corner diagnoses for the last session (Magione, Porsche 911 GT3 R — c3 "You messed up your
exit", c4 "line too wide") and retained them to the lake.

**M-TT2 follow-up:** PR #395 now ships the `reference` CLI + M0 bridge, with strict partial guards.
The real data constraint still stands: `/last-session` carries only one segment's telemetry window
(~9% of the lap in the retained fixture), so production use requires enough retained segment windows
or a newly found full-lap endpoint before strict mode emits a non-partial archive. Next #353 slice is
**M-TT3** (per-corner analysis -> harness drive-to-reference curriculum). Arbitrary-lap/older-session
coaching is also a deferred follow-up (M-TT1 scopes to the last session's own lap).

## Delivered (2026-06-29) — PR #365 MERGED: Game Point launcher supervisor (#363 CLOSED)

PR [#365](https://github.com/agorokh/ac-copilot-trainer/pull/365) merged to
`main` as squash commit
[`854f822`](https://github.com/agorokh/ac-copilot-trainer/commit/854f822bdd868397e99bfd56c08ade2f87277139)
at 2026-06-29T09:15:25Z and closed
[#363](https://github.com/agorokh/ac-copilot-trainer/issues/363).

Delivered: Windows Game Point launcher package (`python -m tools.rig_launcher`),
Desktop shortcut installer/build path, per-user launcher settings, supervised
sidecar start/status/logging, environment-only sidecar token/voice routing,
Setup Exchange proxy/install path, rig-screen Setup Exchange screen, Pocket
Technician spinner list/set protocol, and Game Point launcher docs.
Review-resolution and install notes live in
[[pr-365-game-point-launcher-2026-06-29]].

Verification before merge: local `make ci-fast PYTHON=.venv/bin/python` passed on
current head `27e7dbd` (`1753 passed, 75 skipped`, coverage 84.93%); GitHub
`build`, `pip-audit`, `Canonical docs exist`, and `conformance` passed on the
same head; `scripts/ci_resolve_gate.py agorokh/ac-copilot-trainer 365` reported
`No substantive findings hanging`; GraphQL `reviewThreads` returned 60 threads,
`hasNext=false`, `unresolved_total=0`; no current-SHA self-hosted reviewer body
was present after the required cooldown.

Post-merge classification: `.env.example` changed, so review/update operator
environment on the rig as needed; `pyproject.toml` changed, so refresh the local
dev install with `pip install -e '.[dev]'` or the equivalent lockfile workflow.
No migrations were detected or run.

Honest remaining #86 scope: [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86)
is still OPEN as the broader rig-screen epic. After #361 and #365, its remaining
closure gates are not the Game Point code path itself; they are LVGL font
conversion outputs, SPIFFS/persistence/backpressure/debug-screen polish if still
desired, and final on-device smoke evidence
`launcher -> AC Copilot live hints -> Pocket Technician setup load -> Setup Exchange browse/download/install`.
Packaged-launcher proof should be rerun on the Windows rig when available.

## Claude Design UI package for launcher + rig screens (2026-06-29)

Created `docs/10_Development/15_Claude_Design_UI_Package.md` as the handoff
package for Claude Design or any future UI implementation agent. It explains the
current screen technologies and implemented functions across the ESP32 LVGL
portrait screen, Windows Tkinter Game Point launcher, CSP Lua in-game HUD, and
sidecar protocol, then lays out future scope for launcher expansion, Setup
Exchange, voice, haptics, diagnostics, and post-lap coaching screens. Use it as
the copy-paste design prompt before asking Claude Design for a full UI pass.

Also linked it from `docs/10_Development/14_Game_Point_Launcher.md` so new
driver-facing launcher work discovers the UI contract. Tier-3 MCP was not
exposed in this Codex session; the package was grounded from the vault and live
source files listed inside the package.

## Track Titan #353 (parallel track) — M-TT0 shipped; M-TT1 services auth CRACKED, path-pinning remains

PR [#359](https://github.com/agorokh/ac-copilot-trainer/pull/359) (M-TT0 vulcan retention) MERGED.
M-TT1 services research (2026-06-29): the Cognito Identity-Pool → SigV4 auth flow now **works**
(GetId/GetCredentials 200, SigV4 signing accepted), and **`data-analysis` accepts SigV4/IAM** (404 =
exact path/params still to pin — the operator's primary want is auth-cracked). `dynamic-reference-laps`
/`advice` paths pinned but return 403 (IAM-scoping or apiKey). Full findings + precise next steps:
[[tt-services-sigv4-crack-2026-06-29]]. **Resume:** pin the exact `data-analysis` path (CDP capture of
the running TT app, or fetch the session-review page chunk) → build `tt_services.py` → M-TT2 (reference
→ `lap_archive` → M0 `--voice-reference`) → M-TT3. Personal-use guardrail scope applies.

## Historical (2026-06-28 evening) — #86 rig screen connectivity restored; PR #361 merged

User reported the #86 rig screen was powered on but not connecting. Live cause:
PC was on a home 5 GHz Wi-Fi network, Mobile Hotspot was not presenting the
rig-screen hotspot gateway, and no sidecar was listening on `8765`. Recovered
the live rig by starting an externally-bound sidecar, switching the Intel 7260
Wi-Fi profile to manual, disconnecting from 5 GHz, and starting Mobile Hotspot.
Evidence at SAVE: Mobile Hotspot `On` with one client, ESP32 DHCP lease present,
sidecar `/health` OK with an established hotspot-gateway-to-screen socket, and
protocol counters moving (`state.snapshot`, `state.subscribe`, `corner_query`,
setup experiment frames).

PR [#361](https://github.com/agorokh/ac-copilot-trainer/pull/361) merged as
[`210c2a1`](https://github.com/agorokh/ac-copilot-trainer/commit/210c2a14f9e3e4993c22aa22ec56767922375296).
It patched the recurring gap:
`start_sidecar.bat` now stays loopback-only by default, but if
`AC_COPILOT_SIDECAR_TOKEN` is set it launches with `--external-bind 0.0.0.0`
(or `AC_COPILOT_SIDECAR_EXTERNAL_BIND`) and keeps the token in the process
environment rather than the command line; `tools.ai_sidecar.server` reads that
env token; firmware README documents the user-env setup. This PC's user env now
has `AC_COPILOT_SIDECAR_TOKEN` set and `AC_COPILOT_SIDECAR_PORT=8765` (value not
recorded). Follow-up hardening in the same PR makes `/health` report current
`screen_peers`, adds `ac_sidecar_screen_peers`, keeps
`ac_sidecar_screen_connected` true when a screen socket is actually present, and
lets the Lua telemetry publisher read CSP userdata/cdata car state defensively.
Artifact proof: `start_sidecar.bat` launched on temporary port `9876`
with log `AI sidecar listening host=0.0.0.0 port=9876 ... token=set`, `/health`
OK, and no `--token` in the process command line.

Verification: focused tests `8 passed`; `ruff check` on the repo passed; Bandit,
policy docs, tracked-file secret policy, agent-forbidden, CSP API, and CSP UI
checks passed. Broad pytest with only
`tests/test_process_miner/test_distill.py` ignored: `1548 passed, 114 skipped`,
coverage `83.33%`. Full pytest collection without that ignore is blocked because
`~/.fleet-governance` exists but lacks `runtime/inference_egress`. `make` is not
installed in this PowerShell; repo-wide ruff format check in this Windows
checkout still wants to rewrite hundreds of unrelated CRLF/LF files, while
changed files pass targeted `ruff format --check`.

Detail: [[issue-86-rig-screen-hotspot-autostart-2026-06-28]]. Successor issue
[#363](https://github.com/agorokh/ac-copilot-trainer/issues/363) now owns the
broader human-playable Game Point launcher, Pocket Technician completion, and
Setup Exchange completion scope; #363 closed with PR #365.

## Resume here (2026-06-28) — Track Titan #353 M-TT1 next, then #345 P0 capture

**[#353](https://github.com/agorokh/ac-copilot-trainer/issues/353) — Track Titan ingest. M-TT0
(vulcan retention) MERGED in [PR #359](https://github.com/agorokh/ac-copilot-trainer/pull/359)
(`bd69cab`); see [[pr-359-tt-ingest-mtt0-2026-06-28]].** Issue stays OPEN. **Next = M-TT1 services
SigV4 crack** (`data-analysis` / `dynamic-reference-laps` / `advice`): idToken → `GetId` →
`GetCredentialsForIdentity` → SigV4-sign `services.tracktitan.io` (`execute-api`, us-east-1); pin the
`data-analysis` API path from the Electron Code Cache JS bundle (also check the alternate `X-Api-Key`
path before committing to full IAM). Pure SigV4 canonical-request helpers go in `tt_auth` (reuse
`TTConfig.identity_url` / `user_pool_provider`). **Operator decision 2026-06-28:** personal own-account
TT export is permitted (guardrail scoped to redistribution/at-scale — see
[[track-titan-coaching-oracle-strategy-2026-06-27]]); same scope applies to M-TT1/M-TT2/M-TT3.

**#345 P0 capture half** (rig-gated Lua): car-id fn-bug (`cars=1` collapse), setup snapshot, weather/conditions, #305 flush, provenance, widen TRACE_FIELDS. **Drift note:** `check_vault_follow_up.sh` hardcodes `02_Investigations/` but this spoke uses `03_Investigations/` — file a fix.

**[#350](https://github.com/agorokh/ac-copilot-trainer/issues/350) — voice coach LIVE-FIRE: now RIG-SMOKE ONLY.**
⚠️ The old "no Lua producer / `git grep telemetry_tick src/` empty" note is **STALE** — the **Lua
`telemetry_tick` producer (Part A) shipped in PR #342** (`M.publishTelemetryTickIfDue`,
`telemetry_publisher.lua:158`, 20 Hz spline+lap, wired at `ac_copilot_trainer.lua:2274`), merged 39 min
*after* #350 was filed. Part A is **DONE and green on `main`** (reconciled on the issue with pasted evidence;
the M0 pipeline was briefly red from a #342×#349 merge collision, **fixed in PR #355** — see below). **All
that remains is Part B (operator/rig-gated):** bake a Piper bank (`python -m tools.ai_sidecar.voice.bake
--backend piper`), launch the sidecar with `--voice-reference <archive> --voice-bank <dir>`, drive Magione vs
a faster reference, tap `coaching.cue`, confirm the operator **hears** ≥1 spline-anchored cue. Remaining
producer follow-up on #350: real `lat_g`/`long_g` (rig-gated; inert for the observer). The double `spline`/lap
validation dedup is **DONE** (#357 / PR #358, `4e70131`).

**#345 P0 capture half** (rig-gated Lua) also still pending — see the line above.

---

## Delivered (2026-06-28) — PR #359 MERGED: Track Titan ingest M-TT0 (vulcan retention)
`/autonomous-deliver 353` (ultracode). `tools/tt_ingest/` retains the operator's **own** TT sessions
immutably (auth → mint → paginate → write-once lake + reindex-from-disk + lossless conditions index);
CLI `python -m tools.tt_ingest {auth-check, export}`. 97 tests, 96% cov. **Live-verified** on the real
account: 149 sessions, write-once + index-holds-on-partial-export confirmed. **Policy:** token cloud-API
automation conflicted with the canonical TT guardrail; reconciliation gate paused the merge, **operator
approved** proceeding and the guardrail was **scoped** to redistribution/at-scale (personal own-account
export = self data-portability). Hardened via a 5-lens adversarial self-review (ReDoS, lake-path
collision, NaN-batch-abort, raw write-once, full-lake reindex). Full node: [[pr-359-tt-ingest-mtt0-2026-06-28]].
M-TT1/M-TT2/M-TT3 remain on #353. Merge `bd69cab`.

---

## Delivered (2026-06-28) — curated setups as first-class data-platform entities (PR #369)
`/start-task` (ultracode). Operator asked for a **balanced fast-race setup for the 911 GT3 R at
Magione**, visible on the rig, plus "put it properly in our data platform" + preserve the knowledge.
Shipped: (1) **`assets/setups/ks_porsche_911_gt3_r_2016/magione/Copilot_Balanced_Fast.ini`** — verified
values (FRONT_BIAS 63, ARB f6/r1, DIFF_COAST 60, rear TOE 9, **WING_2 16**), grounded in the operator's
own `Realistic_BB_v3` and adversarially verified (4 vehicle-dynamics lenses → red-team, high
confidence). **Deployed** to `%AC_USERDATA%\setups\...\magione\` (the rig `setup.list` lists it on
Magione). (2) **`tools/setup_catalog`** registrar — rig-faithful **djb2 `canonical_hash`** bridges the
curated catalog to the DuckDB lake + experiments store; robust name/path-fallback join; 17 tests incl. an
end-to-end "simulated driven lap joins the catalog" proof; module 100% cov; ruff clean. (3) Vault: decision
[[curated-setup-as-data-platform-entity-2026-06-28]], investigations [[curated-setup-hash-bridge-2026-06-28]]
+ [[porsche-911-gt3r-magione-balanced-setup-2026-06-28]]; **resolved** the long-open AC user-data path
(`%USERPROFILE%\OneDrive\Documents\Assetto Corsa`) in `glossary/install-paths.md`. **Note:** Tier-3
agentic-memory MCP query tool was absent this session (degraded-mode bypass logged in
`.scratch/.memory_bypass_rationale`). PR [#369](https://github.com/agorokh/ac-copilot-trainer/pull/369)
(supersedes #367 — `claude/` branch prefix is rejected by ci-conventional) **MERGED**
2026-06-29 as squash [`6705bc7`](https://github.com/agorokh/ac-copilot-trainer/commit/6705bc7b206fada67310c5be8134202e68f6ecc6);
[#366](https://github.com/agorokh/ac-copilot-trainer/issues/366) closed. Autonomous-deliver
closeout verified PR head `a9015d8`: GitHub `build`, `conformance`, and `Canonical docs exist` green;
GraphQL reviewThreads had no current unresolved thread after the full cooldown; Qodo updated to the
head SHA, Gemini/Codex review capacity was quota-limited with no substantive current finding, and no
current-SHA self-hosted reviewer review was present after cooldown. Local verification:
`tests/test_setup_catalog_registrar.py` = 29 passed; temp catalog register/list + DuckDB join returned
`driven_laps=1`, `best_ms=82500` for `canonical_hash=054245cb`; `make ci-fast` passed with the
local venv Python (`1656 passed, 76 skipped`, coverage 85.19%, ruff/Bandit/policy/CSP checks green).
Post-merge classification: `scripts/` changed (`scripts/check_agent_forbidden.py` allowlist for
`assets/`); no migration/env/deps/workflow action required.

---

## Delivered (2026-06-28) — PR #355 MERGED: green main + #350 reconciliation (#354 CLOSED)
`/autonomous-deliver 350` (ultracode). Reconciling #350 surfaced that its premise was **stale** (Part A
producer already shipped in PR #342, merged 39 min after #350 was filed) **and** that `main` was **RED**
(`build: failure @ 84b5698`) from a **#342×#349 merge collision**. PR
[#355](https://github.com/agorokh/ac-copilot-trainer/pull/355) (`27cb7100`, **#354 CLOSED**) greens main:
`tests/test_server_observer_wiring.py` referenced the renamed `_publish_coaching_cues` (as
`_publish_observer_cues`) + an abandoned `_load_observer`/`SystemExit` contract; and `_reset_external_state()`
didn't clear the single-producer globals `_observer_feed_peer`/`_observer_feed_warned`, leaking observer-feed
ownership across the voice-wiring tests (AssertionError reproduced on the **Linux CI runner**). Fix: reset the
feed globals on external-state reset (correct on server (re)start/teardown); drop the duplicate `_observer`
decl; target `_publish_coaching_cues`; replace the stale loader tests with best-effort `_wire_voice` tests
(non-vacuous sentinels). **`build` green on `27cb7100`**; full suite `1513 passed, 0 failed` (Py 3.11);
3-agent adversarial pre-merge review (all approve). **#350 reconciled** → Part A done, only rig-gated Part B
remains. **Post-merge:** no classification flags. Detail: [[pr-355-m0-merge-collision-and-350-reconciliation-2026-06-28]].

---

## Delivered (2026-06-28) — PR #358 MERGED: telemetry_tick validation dedup (#357 CLOSED)
Same `/autonomous-deliver 350` run, next debt item. A skeptic review of the #355 work surfaced that
`_validate_telemetry_tick` validated `spline`/lap **twice** (`external_protocol.py:332-338` & `:349-355`) —
#341/#342/#349 merge debris. PR [#358](https://github.com/agorokh/ac-copilot-trainer/pull/358)
(`4e70131`, **#357 CLOSED**) consolidates to one `spline` check + one loop over the **union** of lap-key
spellings (`lap`/`lap_count`/`completed_laps`/`lapCount`/`completedLaps`) — behavior-preserving — and adds
`test_voice_wiring` assertions locking the snake_case variants. `build` green on `4e70131`; full suite
`1513 passed, 0 failed`. **Post-merge:** no classification flags.

---

## Delivered (2026-06-28) — PR #348 MERGED: Coaching lakehouse DuckDB (#344 P1)
**PR [#348](https://github.com/agorokh/ac-copilot-trainer/pull/348)** (`feat/345-coaching-lake-duckdb`) squash-merged to `main` as `226bc97`. Delivers the EPIC #344 "query the whole data plane" engine: `tools/coaching_lake` — embedded **DuckDB** star schema. Rebuilt idempotently from the immutable lap-archive JSON. Bot review addressed (Gemini + Qodo): `math.isfinite`, journal-scoped temp CSV, atomic transaction through samples COPY, explicit ROLLBACK. Detail: [[coaching-lakehouse-duckdb-2026-06-28]]. **Post-merge classification:** `pyproject.toml` changed (run `pip install -e '.[dev]'`), `.github/workflows/` changed.

---

## Delivered (2026-06-28) — PR #349 MERGED: live voice wiring (#341 M0 CLOSED)
`/autonomous-deliver` continued from #340 into #341 Part A. [#349](https://github.com/agorokh/ac-copilot-trainer/pull/349)
squash-merged to `main` as `c477aee`; **#341 CLOSED**. The sidecar now turns the live `telemetry_tick`
stream into spoken cues: `external_protocol` adds `CLIENT_CLASS_VOICE`, the sidecar-originated
`coaching.cue` topic, optional `spline`/`lap` validation, and `make_coaching_cue`; `server.py` gains
optional `_observer`/`_voice_coach` state (OFF by default → byte-identical when unset) + `_publish_coaching_cues`
(feeds the `RealtimeObserver` per tick → speaks via the in-process #340 `VoiceCoach` **and** publishes
`coaching.cue` to WS peers) + `--voice-reference`/`--voice-bank` startup flags (audio deps lazy). A **parallel
autonomous session** (running as `agorokh`) advanced this PR to green — adding a `process_pending` tie-break
by `(rank, enqueued_at, batch_index)` (fixing a latent freshest-tie bug in #340 + act-cue advisory→dispatch
latency logging vs the 150 ms budget), a test-isolation autouse fixture, and a `lapCount` case. 9 new wiring
tests incl. an end-to-end `telemetry_tick → voice-client coaching.cue` round-trip; `make ci-fast` re-verified
green locally on the merged head. **Reconciliation:** #341 closed COMPLETED but 2 ACs (Lua spline emit;
rig smoke) were unmet → filed **#350** for the live producer + on-rig audible verification so the work isn't
lost (cross-linked on #341). **Post-merge:** no classification flags.


---

## Delivered (2026-06-28) — PR #338 MERGED: CoachingOracle Qodo round-6 hardening (#333)
[#338](https://github.com/agorokh/ac-copilot-trainer/pull/338) squash-merged to `main` as `f8d010e` (2026-06-28T07:32:32Z).
Post-merge hardening for round-6 Qodo findings that missed the #334 squash: `get_coaching()` None-on-failure
(`AssertionError` + early return in `debrief_to_advisories`), spaced debrief OCR marker, nested-None coercion,
WinRT `Await` budget (10s/op + cancel on timeout) aligned with Python `_DEFAULT_HELPER_TIMEOUT_S=110`,
parse/helper failure logging, 19 coaching-oracle tests. Detail: [[pr-338-coaching-hardening-handoff]].
**Classification:** no post-merge flags.

---

## Delivered (2026-06-28) — PR #343 MERGED: in-the-ear voice coach (#340)
`/autonomous-deliver 340` shipped the **voice output layer** for the realtime coaching pipeline.
[#343](https://github.com/agorokh/ac-copilot-trainer/pull/343) (issue #340) squash-merged to `main` as
`f50719c`; **#340 CLOSED**. New `tools/ai_sidecar/voice/` module speaks the *same* `Advisory` stream the
text HUD renders (`realtime_observer.py`), via a **pre-rendered phrase bank** (not live TTS) + an
**urgency scheduler** (act>prepare>info; barge-in, per-pass dedup, TTL drop, per-kind cooldown):
`vocabulary` (bounded, content-addressed) · `manifest` (the only advisory→audio map; sha256-enforced at
load) · `resolver` · `scheduler` · `playback` (pure device resolver pins the headset **off** the haptic
USB-DAC; lazy rtmixer/sounddevice) · `config` (verbosity) · `bake` (Tone/Piper/macOS-say) · `engine`.
Stdlib core stays **dep-free** (audio deps behind a new `voice` extra). 51 unit tests via injectable
playback+clock; `make ci-fast` green. **Operator-grade off-rig verification:** baked a real-speech bank
(macOS `say`), ran the real resolver→scheduler→playback pipeline, measured **emit→dispatch latency
1.27 ms** (budget ≤150 ms), rendered 9.19 s of real speech to a WAV (delivered to operator). Qodo round-1
flagged 2 reliability issues (Bank sha not enforced at load; sounddevice channel stuck-busy) — both fixed
(commit `3c96229`), tested, threads resolved; Qodo re-review clean. Decision dossier:
[[voice-coach-architecture-2026-06-28]] — **also extinguished the dangling reference the #340 body cited**
(that dossier was never committed; `git log --all` empty). **Post-merge:** `pyproject.toml` changed → run
`pip install -e '.[dev]'` (or `.[voice]` on the rig to play the bank). **Deferred (rig-gated follow-up):**
final on-rig audible verification with the operator at the wheel; v1.1 number-splicing / live-TTS OOV
fallback; cloud debrief; per-track corner names.

---

## Delivered (2026-06-28) — #327 CLOSED (no code): vault-automerge already fixed
`/autonomous-deliver 327` reconciled the stale issue body against live state and **closed
[#327](https://github.com/agorokh/ac-copilot-trainer/issues/327) COMPLETED with zero code**. Both
symptoms were already gone: (1) the `guard-and-automerge` / `governance-hub`-not-found regression is a
**duplicate of #329**, fixed by **PR #330** (fleet-bot app-token + checkout, present at `HEAD`); (2) the
`build`/`ci-conventional` failure was a **branch-name artifact** of PR #326's `claude/...` branch, not a
defect — every proper `vault/...` PR (#331/#332/#337) is green on both checks. Detail +
live-evidence table: [[issue-327-vault-automerge-already-resolved-2026-06-28]]. **Lesson:** parallel
autonomous sessions can file+fix the same root cause under different numbers — reconcile before re-doing.

---

## Delivered (2026-06-28) — PR #334 MERGED: Track Titan CoachingOracle
[#334](https://github.com/agorokh/ac-copilot-trainer/pull/334) (issue #333) squash-merged to `main` as
`32c86e9`. Productionized the screen-OCR `CoachingOracle`: `tools/ai_sidecar/coaching_oracle.py` +
`tools/ai_sidecar/tt_overlay_ocr.ps1` (native `Windows.Media.Ocr`) + `tests/test_coaching_oracle.py`
(14 tests, 98% module cov) + pyproject `package-data`. Bot review converged over 6 rounds (Codex/Qodo);
hardening learnings recorded in [[track-titan-coaching-oracle-strategy-2026-06-27]] (now `active`).
**Post-merge note:** `pyproject.toml` changed → run `pip install -e '.[dev]'`. The research/feasibility
block below is superseded by this delivered entry.

---

## Side research (2026-06-27) — Track Titan as a coaching angle (PR #334)
Active code resume is still **#305 / Track Titan-independent** (below). Separately, a `/start-task`
research pass investigated the locally-installed **Track Titan** as an external coaching angle.
Findings + strategy: [[track-titan-telemetry-extraction-feasibility-2026-06-27]] +
[[track-titan-coaching-oracle-strategy-2026-06-27]] (full report `.scratch/tt-research-report.md`).
**TL;DR:** TT reads the same AC shared memory we do and uploads our `.acreplay`; analysis is cloud-only;
no API/export. For AC it adds **no new raw signal** — only pro ghost laps + an AI opinion. Recommended:
treat TT as a swappable "coaching oracle"; cheap wins first (pro ghost → #207 faster-than-PB importer;
TT per-corner time-loss as an external referee for the autonomous harness); time-box a `ws://localhost:9121`
tap spike; **never** automate the user's plaintext Cognito token. No runtime coupling proposed.
**Update (fully autonomous live-verify on AG_PC):** ws:9121 tap PROVEN (11,497 frames) but **live-telemetry only** — TT's coaching (post-lap AI debrief) renders in the overlay and does NOT cross the ws (also unreliable as a 2nd consumer beside the real overlay). **Screen-capture/OCR is the extraction path** — POC built + verified: `.scratch/ocr_extract_tt.ps1` (native Windows.Media.Ocr, zero deps) emits coaching JSON (`.scratch/tt_coaching.json`). Next: productionize a `CoachingOracle` Python module via `/orchestrate`. Rig restored to stock. **Update:** productionization shipped in
[PR #334](https://github.com/agorokh/ac-copilot-trainer/pull/334) (implements
[#333](https://github.com/agorokh/ac-copilot-trainer/issues/333)) —
`tools/ai_sidecar/coaching_oracle.py` + `tt_overlay_ocr.ps1` + tests; bot review resolved.

---

## Resume here (2026-06-27 — #277 CLOSED: brain debrief LIVE-VERIFIED on the rig)

**`/autonomous-deliver 277` — DONE.** [#277](https://github.com/agorokh/ac-copilot-trainer/issues/277)
**CLOSED**: the archive-backed brain debrief (#321) is live-verified end-to-end on AG_PC. Autonomous
carcsw/Stanley drive of **`ks_audi_r8_lms` @ magione** (3 valid laps, best 1:46.9, 207.8 km/h) →
**5 live `debriefSource:"brain"` `coaching_response` frames** captured on the WS wire
(sidecar→`ws_bridge.lua`), each a 5-corner `cornerAnalysis` with **CONFIRMED per-wheel attribution**
(e.g. "Rear wheelspin on exit (confirmed) — raise TC / open diff", "No wheelspin (confirmed)") plus
`trailBraking`/`tyres`/`balance`. `build_brain_followup` on the real archive reproduces it offline.
Detail + learnings: [[issue-277-rig-verify-prepped-blocked-concurrency-2026-06-27]].

**Key learnings (durable):**
- Brain debrief is gated by **`AC_COPILOT_OLLAMA_ENABLE`** (deterministic brain, but shares the Ollama
  flag). `start_sidecar.bat` sets it `=1` by default → the CSP-auto-launched sidecar enables it; a
  sidecar started with it `=0` silently disables the brain debrief (`build_brain_followup` → None).
- **carcsw hijack is incompatible with extended-physics cars**: `911 GT3 R 2016` triggers CSP
  "extended physics for car" → no `Car0` mmap → hijack fails. Use a non-extended car (`ks_audi_r8_lms`).
  **No `surfaces.ini` custom-AI edit is needed** (stock + AC-install `new_behaviour.ini [CUSTOM_AI]
  ENABLED=1` suffices; the `WAV_PITCH=extended-0` edit actively BREAKS the hijack).
- Launch reliably via `ContentManagerActuator` (`Content Manager.exe acmanager://…`), **not**
  `explorer.exe` (opens CM without applying the preset).
- **Residual (separable → EPIC #154 Part-G):** the HUD coaching-summary *tile* gates on an AC-**valid**
  lap; the autonomous Stanley line clips curbs → AC-invalid → tile placeholder. The brain frame is
  delivered live regardless; on-screen tile pixels confirm on a clean valid (human) lap.

**Rig left:** surfaces stock, `new_behaviour.ini` restored; AC + a brain-enabled sidecar left running.
The "PREPPED/paused" block below is superseded by this.

## Resume here (2026-06-27 LATE — CI: vault-automerge guard fixed (#329 / PR #330))

**Infra fix.** Every `vault-only` PR's `guard-and-automerge` check was failing in ~3s — `Unable to
resolve action agorokh/governance-hub, not found` — because the #863 refactor pointed it at a
**private** cross-repo action, which the default `GITHUB_TOKEN` cannot resolve (the hub's
`access_level=user` + the action existing at the pinned SHA were both confirmed and still insufficient).
PR [#330](https://github.com/agorokh/ac-copilot-trainer/pull/330) (`52ecbf5`, closes
[#329](https://github.com/agorokh/ac-copilot-trainer/issues/329)) mints the **FLEET_BOT app token**,
checks the governance-hub action out at its pinned SHA, and runs it via a local path —
**reference-not-vendor preserved**, mirroring the fleet's existing `create-github-app-token` pattern.
This vault PR is itself the live test of the fix: if its guard goes green and auto-merges, #329 is
verified. **Fleet note:** the #863 refactor is fleet-wide → every child repo has the same broken guard;
propose the same app-token wrapper upstream (agent-factory / governance-hub).

---

## Resume here (2026-06-27 LATE — EPIC #154 auto_drive composed loop + flat-out racing MERGED)

**`/autonomous-deliver 154` on AG_PC (this session, `flamboyant-poincare-b469d9`).** Shipped PR
[#325](https://github.com/agorokh/ac-copilot-trainer/pull/325) (`0fb721f`, closes
[#324](https://github.com/agorokh/ac-copilot-trainer/issues/324)): new `tools/ac_harness/auto_drive.py`
— the genuinely-composed one-command L2 loop (launch → carcsw hijack w/ retry → autonomous drive in a
thread → WS producer assert), **parametrized by car/track/preset**, with **sim-death anti-false-green**
(Car0 packet stagnation). Driver modes: `cruise` (LapDriver) / `racing` (AI-line) / **`ggv`
(flat-out friction-circle min-time)**. 21 off-sim tests; post-merge classification clean.

**Operator question answered LIVE (generality beyond Magione/Porsche, racing not theater):**
- **Imola + Audi R8 LMS** — autonomous **full lap** (5200 m), trainer registered the lap + reference coaching.
- **Mugello + Corvette C7R** — 2.5 km autonomous; coaching `current_speed_kmh` matched the AI-driven car.
- **Spa + BMW Z4 GT3** — `ggv` **flat-out top gear 6 / 211 km/h**, reference coaching (`T2 · target entry 241 km/h`).
- The first composed run "wasn't racing" (1st gear, 49 km/h) → now shifts 1→6 and sends straights.

**Load-bearing finding:** the generic GGV's `k_aero_lat` MUST be 0 — an aero-lateral grip term spins the
GT3 out (matches the #259 red-team; a multi-agent verification workflow caught it pre-ship). Verified
plant fit lives in `auto_drive.generic_gt3_ggv()`.

**What remains (Part-G residual; #154 stays OPEN):** clean flat-out line (~83 s) needs curvature-ff
steering with per-car `ff_c1/c2` calibration from a human CSV (#244); the formal false-green-rate <5%
KPI; and #154 children #277/#278/#305. AC rig was crash-prone this session (4 fresh-launch crashes — the
sim-death guard caught all, reporting honest FAIL). Full write-up:
[[autonomous-drive-multitrack-generality-2026-06-27]].

---

## Resume here (2026-06-27 EVENING — #277 brain-debrief rig-verify PREPPED, paused on rig contention)

**`/autonomous-deliver 277` on AG_PC.** #277 *code* is merged (PR #321, `8d9eb97`; post-merge
classification clean — no migration/env/deps/workflow flags). The only remaining acceptance is the
**rig-verify**: a live `debriefSource==brain` `coaching_response` with `cornerAnalysis` on a driven lap.

**Fully prepped for a ~5-min resume** — see
[[issue-277-rig-verify-prepped-blocked-concurrency-2026-06-27]]: custom-AI surfaces rebuilt
(`.scratch/part-g/surfaces_customai.ini`), `new_behaviour.ini [CUSTOM_AI] ENABLED=1` added, vetted drive
script `.scratch/issue277_drive_laps.py` (PR #248 `RacingDriver.from_human_profile` Stanley path),
capture harness `.scratch/issue277_live_verify.py` wired (its `_analyze` asserts the `brainOnly`
lap_complete + `debriefSource==brain` round-trip; daemon-free launch).

**Paused — NOT done (single-rig contention):** AG_PC has one AC instance; the concurrent session
**"Autonomous delivery testing in Assetto Corsa"** (`flamboyant-poincare-b469d9`) was actively driving
the rig (imola/mugello captures, Audi R8 / Corvette). I **yielded** — killed **no** peer process and
restored magione `surfaces.ini` to stock. **To finish #277:** when the rig is exclusively free, re-run
`/autonomous-deliver 277` (one step). Serializing the two concurrent rig sessions is an operator call.

---

## Resume here (2026-06-27 LIVE RIG CONFIRMATION — #305 CLOSED)

**Closed COMPLETED** ([#305](https://github.com/agorokh/ac-copilot-trainer/issues/305)) on AG_PC with
AC + CSP running from the repo symlink. This was the post-PR #309 live proof for the final-lap archive
bug.

Observed run:
- Launched AC through Content Manager `race/config` from the live `race.ini`: `ks_porsche_911_gt3_r_2016`
  at `magione`; shared memory confirmed `LIVE` / not-in-pit and the HUD screenshot rendered.
- Temporarily applied Magione Custom-AI permissions, drove two completed laps with the Custom-AI
  controller, then restored stock `surfaces.ini` afterward.
- Final target lap was **lap 2, valid PB, 81.841 s**, with no third completed lap before cleanup.
- New archive:
  `lap_20260627-055835_87fc4736_2_81841_6a3f668b9bbd.json` — **670,811 bytes / 655.1 KB**,
  `trace.samples_count=2000`, `len(trace.samples)=2000`, 22 trace fields including
  `wheelAngularSpeed_*` and `wheelSlip_*`. This is a full trace, not the former 923-byte stub.
- CSP log also showed the defensive guard working: empty trace refused instead of written as a stub,
  then `queued async write samples=2000` and wrote the final-lap archive.

Evidence is local/ignored at `.scratch/issue305-live-20260626-225318/`:
`drive.stdout.log`, `drive-visual.png`, `csp-archive-tail.log`, copied final archive JSON, and cleanup
metadata. The public closeout comment is
[#305#issuecomment-4815490402](https://github.com/agorokh/ac-copilot-trainer/issues/305#issuecomment-4815490402).

Note: the session began while the active `feat/issue-277-live-brain-debrief` WIP branch already held
source/test/docs changes for the brain-debrief delivery. The #305 rig-confirmation SAVE only added
this vault handoff.

---

## Resume here (2026-06-25 LATEST — #308 Tier-3 worktree memory-gate false-block CLOSED)

**Closed COMPLETED** ([#308](https://github.com/agorokh/ac-copilot-trainer/issues/308)) — autonomous
triage, no source change. Both acceptance criteria verified by running the **real** SessionStart
prefetch from inside a linked git worktree (operator-grade, observed):

- **Part A** (gitignored overlay non-propagation → `example_kb_workspace` block): already fixed by
  [PR #316](https://github.com/agorokh/ac-copilot-trainer/pull/316). Prefetch in a linked worktree
  resolves `workspace: ac_copilot`, **no** `.last_memory_query.missing` block marker.
- **Part B** (prefetch SSRF guard on `:8045`): **functional criterion met** — prefetch exits 0,
  substrate answers, `prefetch_ok: true` stamp written. The `untrusted port 8045` SSRF WARN is
  **cosmetic / by-design** on a non-central host (grounding succeeds via the registry's non-loopback
  Tailscale endpoint; the manifest loopback is correctly rejected). The original "permanent SSRF
  block" was a **transient substrate outage**, not the guard.
- **Residual** (genuinely upstream — governance-hub owns the resolver; this repo carries only shims):
  cosmetic-WARN downgrade filed as
  [governance-hub#111](https://github.com/agorokh/governance-hub/issues/111).
- Detail: [issue-308-worktree-memory-gate-resolved-2026-06-25.md](../03_Investigations/issue-308-worktree-memory-gate-resolved-2026-06-25.md).

**CORRECTION to the older note below:** the earlier *"Tier-3 `ac_copilot` substrate remains DOWN"* is
now **stale** — the substrate is **UP** as of 2026-06-25 (`verify_server_health reachable=true`; the
prefetch grounds with a real answer).

---

## Resume here (2026-06-23 LATEST — #278 lupa per-wheel test fidelity SHIPPED via PR #315)

**Delivered (squash-merged [`f35d2fe`](https://github.com/agorokh/ac-copilot-trainer/commit/f35d2fe), closes [#278](https://github.com/agorokh/ac-copilot-trainer/issues/278)):**
Follow-up to #266. The lupa trace-replay harness ran the real `telemetry.lua`, but the schema-gated
mock `car` never exposed `car.wheels`, so the per-wheel capture path (`wheel_read.readPerWheel` → lp
sample) read nil → 0 and was **never exercised off-sim**. Fix:
- `tools/ac_harness/ac_schema.json` — declare `car.wheels` (0-indexed `ac.Wheel`, FL=0..RR=3) so the
  schema gate allows the read.
- `tools/ac_harness/trace_replay.py` — `make_car(wheels=[...])` synthesizes 0-indexed `car.wheels[0..3]`
  (defensive: `None`→nil, non-sequence/non-dict passthrough like `_make_vec3`); new
  `wheels_from_frame(frame)` maps the flat per-wheel frame columns (#266) into wheel specs.
- `tests/test_lua_trace_replay.py` — L0-18..L0-23: `telemetry.lua` emits the
  `wheelAngularSpeed_/wheelSlip_/tyreCoreTemp_ {fl,fr,rl,rr}` columns from the mock wheels in correct
  corner order; a **contrast** test (no wheels → nil columns, proving non-vacuity); the
  `synthesize_trace` path end-to-end; the 0-index `wheel_read` mapping; and the None/passthrough paths.

**Verified (operator-grade, observed):** merged tree == tested tree (empty diff vs `origin/main`);
`pytest tests/test_lua_trace_replay.py` → **24 passed**; `make ci-fast` → OK (1335 passed, CSP API/UI
clean, coverage ≥80%). **Mutation check:** flipping `_make_wheels` to **1-based** made 3 corner-mapping
tests FAIL (catches the #180 `rr=0` shift class); restored → 24 pass. Review: Gemini raised 4 *medium*
robustness findings (defensive `_make_wheels`/`_ingest_lap`) — all fixed in `a0fb739`, threads resolved;
CodeRabbit clean; Sourcery rate-limited (non-blocking); Cursor Bugbot skipped; **self-hosted reviewer
daemon does not review this repo** (no head-SHA review → anti-hang vacuous).

**Memory-gate note (resolved):** the committed `ops/memory_manifest.yml` placeholder hard-block was
**already fixed by PR #316** (`c3590ec`, `repo.tier3_workspace_id: ac_copilot`) — so the follow-up I'd
have filed is moot. This session also wrote a **gitignored** `ops/memory_manifest.local.yml` overlay
(operator-local, redundant now that #316 fixed the tracked manifest — harmless, local-wins same value).
**Tier-3 `ac_copilot` substrate remains DOWN** (verified `verify_server_health` reachable=false / HTTP
502); grounding was vault-Tier-2 per the MEMORY_CONTRACT recovery path. Provisioning/ingest of
`ac_copilot` is the standing follow-on (tracked environmental, see the #316 handoff note below).

**No remaining work for #278** — issue CLOSED (COMPLETED), no migration/env/deps classification flags.

## Resume here (2026-06-23 LATER — Tier-3 manifest placeholder FIXED via PR #316)

**Delivered (squash-merged [`c3590ec`](https://github.com/agorokh/ac-copilot-trainer/commit/c3590ec), closes [#314](https://github.com/agorokh/ac-copilot-trainer/issues/314)):**
`ops/memory_manifest.yml` still carried the template placeholder `example_kb_workspace` (whose
relative `vault_root` resolved inside every checkout → `resolve_workspace` picked it via the
vault_root fallback → SessionStart prefetch failed bridge visibility → memory gate never stamped).
Fix: `repo.tier3_workspace_id: "ac_copilot"` (authoritative, wins over the `ac_copilot_trainer`
alias) + the real `ac_copilot` row (host `mac-mini-dev`, `http://localhost:8045`, `lightrag`).

**Verified:** `resolve_workspace` → `ac_copilot` (env-independent); the prefetch resolves
`ac_copilot` with **no mismatch error**; `test_hook_memory_manifest.py` + `make ci-fast` green.
**Still environmental (separate from this fix):** standalone prefetch on a *non-central* host reports
"substrate unreachable/empty" because the MCP wrapper's bridge env (TLS server name for the Tailscale
HTTPS registry endpoint) isn't set when invoking the script bare, and the `ac_copilot` workspace is
currently **sparse/unprovisioned** (a bridge query returns empty). Provisioning/ingest is the
follow-on; the manifest now targets the right, reachable workspace so that ingest can fill it.

## Resume here (2026-06-23 — #305 capture bug SHIPPED via PR #309; rig confirmation remains)

**Delivered (squash-merged [`86c5f60`](https://github.com/agorokh/ac-copilot-trainer/commit/86c5f60), 2026-06-23):**
issue [#305](https://github.com/agorokh/ac-copilot-trainer/issues/305) — a clean flying lap's trace
archive was lost (≈923-byte stub) when **not followed by another lap** (hot-lap-then-pit, or an
automated capture run ending). Pure Lua **capture/flush** bug, not an analysis gap.

**Root cause:** the async lap-archive job is queued at the S/F crossing that *completes* a lap and
pumped a few rows/frame by `pumpLapArchiveJobs()`. On session end, `script.update()` enters the
`if sim.isInMainMenu then` branch and **returns before reaching the per-frame pump**, so the last
lap's job is abandoned mid-stream as a partial `.tmp`. The outlap survived only because ~82 s of
flying-lap frames pumped it; `resetRuntimeAfterLeavingTrack` never drains the queue. Full write-up:
[[pr-309-lap-archive-finalization]].

**Fix (3 parts):** `flushPendingLapArchiveJobs()` synchronously drains all pending jobs, wired into
the session-end branch (gated on `state.wasDriving` per Gemini review) before the early return;
`createWriteJob` refuses an empty trace (never stage a traceless stub); 3 lupa tests + a
lupa-independent source-structure guard (`tests/test_lap_archive_source_structure.py`).

**Verified offline only** (macOS — the rig is AG_PC/Windows): 1334 tests + `make ci-fast` green;
proved the stub-guard test fails on pre-fix `origin/main`; a 5-lens adversarial-review workflow
(19→3 findings, all test-hygiene) addressed. PR review: Gemini *medium* + CodeRabbit *trivial*
resolved; Cursor Bugbot clean; the self-hosted reviewer daemon does not review this repo (no
head-SHA review across 3 cooldowns → anti-hang vacuous).

**REMAINING — live rig confirmation (why #305 stays OPEN):** drive ≥1 flying lap, return to the
menu / end the session **without** another lap, then confirm `…/journal/laps/` holds a **full-trace**
`lap_*.json` (not a stub) for that lap. Needs AG_PC + AC; could not be done from macOS. Same class as
the #277 rig-gated step.

**Side bug — RESOLVED (#314 / PR #316, `c3590ec`):** `ops/memory_manifest.yml` had the template
placeholder workspace `example_kb_workspace`, so every SessionStart's Tier-3 prefetch errored
("workspace not visible") and never stamped the memory gate. Now points at the real `ac_copilot`
workspace (see the manifest-fix section above).

**Housekeeping:** primary worktree `main` was 1 behind `origin/main` after the merge (protect-main
guard blocks a manual ff from a linked worktree; `post_merge_sync.sh` can't `checkout main` when it's
held by the primary worktree) — the next primary-worktree session's `git pull --ff-only` (or
SessionStart) reconciles it.

## Prior (2026-06-23 — #301 trail-braking SHIPPED via PR #310)

**Delivered (squash-merged `2755eb7`, 2026-06-23):** issue #301 — the two trail-braking follow-ups.
Part 1 ([`coach_handoff.py`](../../../../tools/ai_sidecar/coach_handoff.py)) joins the
`trail_braking` block onto each handoff corner as a compact `trail_brake` field; Part 2
([`corner_attribution.py`](../../../../tools/ai_sidecar/corner_attribution.py)) folds trail-braking
into the attribution layer as a low-confidence (`0.26–0.29`) **technique** rule that never displaces
existing setup/time-loss attributions. Additive (`COACH_HANDOFF_VERSION` unchanged); strict
`coaching_response` golden unchanged; `make ci-fast` OK (1337 passed); adversarial review 0 confirmed
findings; verified end-to-end on `main` (handoff `trail_brake` field + `cause_class='technique'`
attribution + live `coaching_response` wire path). Full record:
[`pr-310-trail-brake-attribution-handoff.md`](../03_Investigations/pr-310-trail-brake-attribution-handoff.md).
This closes the **frontier coaching program / EPIC #154** trail-braking reach.

Tier-3 substrate `ac_copilot` was **down (502)** this session → grounded vault-only; the worktree
memory-gate false-block is already tracked as **#308** (gate sat in its sanctioned outage soft-allow).

## Resume here (2026-06-23 — #303 Windows path-guard SHIPPED via PR #304)

**Delivered (merged `5210973`, 2026-06-23):** issue #303 — `normalize_path_list` in
[`tools/process_miner/session_debrief_schema.py`](../../../../tools/process_miner/session_debrief_schema.py)
now detects absolute paths cross-platform (`PurePosixPath | PureWindowsPath`), closing the Windows
`/etc/passwd` traversal-guard bypass. During PR resolution I addressed a **gemini-code-assist HIGH**:
the guard now resolves/relativizes **only host-absolute** paths and skips foreign-platform-absolute
paths outright (`if root is None or not Path(normalized).is_absolute(): continue`) — previously such a
path was anchored to the CWD and could be admitted via `relative_to(root)` when the CWD lay under
`root`. Added regression test `test_normalize_path_list_foreign_absolute_with_repo_root_skipped`.
CI green on the head SHA, review thread resolved, merged after a full 600 s post-push cooldown.

**Filed — separable infra (issue #308):** Tier-3 memory grounding falsely hard-blocked this session
in the linked worktree. Two root causes: (A) gitignored `ops/memory_manifest.local.yml` does **not**
propagate into linked git worktrees, so SessionStart's prefetch fell back to the committed template
placeholder `example_kb_workspace` (not bridge-visible → `gate_policy=block`); (B) the prefetch SSRF
guard rejects the **canonical** `http://localhost:8045` substrate endpoint (port "not registry-known").
**Workaround this session (per MEMORY_CONTRACT bypass protocol):** grounded via the working MCP query
against `ac_copilot` (substrate reachable; empty — brand-new narrow code), recorded an honest
`.scratch/.last_memory_query` stamp, cleared the false block-marker, mirrored the overlay into the
linked worktree, and wrote the rationale to `.scratch/.memory_bypass_rationale`. The committed-manifest
fix (#308 Part A option 3: put `tier3_workspace_id: ac_copilot` in the tracked `ops/memory_manifest.yml`)
would durably stop the per-session recurrence.

**Next pick-ups (off-rig first):** **#305** (flying-lap 0 KB trace — highest-impact bug, CI-able) →
**#277** (close the live loop, rig-gated). #303 is now done; #308 is the new infra debt item.

## Housekeeping addendum — backlog steward sweep (2026-06-22)

`/backlog-steward` reconciled all 8 open issues against merged delivery (read-only; substrate
`ac_copilot` returned empty → Tier-2 + code grounding). Verdicts: **5 live, 2 partially-delivered,
0 stale/drifted**. Ledger: `.scratch/backlog-steward/ledger.json`. Two actions shipped:
- **#154 EPIC body reconciled** (Parts A–G checked off w/ PR evidence; L2-achieved milestone #196
  recorded; scope narrowed to open children #277/#278/#305 + a Part-G KPI residual) — see the
  reconciliation comment on the issue.
- **New pitfall node** [`pitfalls/epic-body-delivery-drift.md`](../pitfalls/epic-body-delivery-drift.md)
  — captures the "long-lived EPIC body never reconciled → re-rake" pattern; candidate for upstream
  propagation to the template-repo hub.

Recommended next pick-ups (off-rig first): **#303** (Windows path-guard, CI-able on Mac) → **#305**
(flying-lap 0 KB trace, highest-impact bug) → **#277** (close the live loop, rig-gated).

## Resume here (2026-06-22 LIVE-VERIFIED — coaching pipeline RUN IN-GAME on real schema-v2 telemetry)

**Tested in the game, not just in code.** Launched AC at Magione (911 GT3 R) via the CM
`acmanager://race/quick` URL + `autodrive_magione.cmpreset`, applied the custom-AI surfaces edit,
and the autonomous curvature-FF controller (`.scratch/part-g/race_drive_diag.py`) hijacked car 0 and
drove **real valid laps (best 1:22.55)** — verified on-screen at 193 km/h with the in-sim realtime
coaching HUD tracking it ("B5 · ON PACE · DISTANCE TO BRAKING POINT").

The in-sim trainer captured a **fresh schema-v2 lap archive** (2000 samples, 22 fields incl.
`wheelAngularSpeed_*`/`wheelSlip_*`/`tyreCoreTemp_*`; saved at
`.scratch/real-lap-evidence/real_v2_lap_magione_2026-06-22.json`). Running the FULL coaching pipeline
(`coach_report.build_debrief` / `build_structured_debrief`) on that **real telemetry** produced
grounded, honest output:
- **Tyre model on REAL core temps:** "Tyres warming (mean core 72°C) — build heat before pushing";
  per-wheel fl/fr/rr=warming, rl=in_window, front−rear=−5.2°C, below the 75-105°C slick window;
  honest "surface temp not measurable, approximate."
- **Trail-braking** on real brake/steer (abrupt-release corners), **per-corner attribution**
  (sluggish turn-in, *suspected*), **conditions** (honest "grip unknown" — archive had only ambient
  temp), and the **realtime observer** emitted a real late-brake advisory vs a faster reference lap.

**Findings from the live run (filed):**
- [#305](https://github.com/agorokh/ac-copilot-trainer/issues/305) — a **clean flying lap's trace is
  lost (0 KB stub)** when not followed by another lap (the async archive seems to finalize on the
  next lap's S/F crossing). The coached lap above was the full-trace *outlap*; the 1:22.55 flying
  lap left a stub. Capture-side bug, not an analysis gap. Fix before relying on single-hot-lap coaching.
- Controller tuning is the known rig-fragility trap: the 1.5g config spins on lap 2+, an over-gentle
  config sticks in gear 1 — so chaining ≥2 clean laps (needed to flush a flying-lap archive per #305)
  needs the tuned config, not ad-hoc knobs. computer-use `request_access` timed out and Windows-MCP
  `Click` has a loc-serialization bug, so clicking CM's "Go!" by UI wasn't possible this run;
  `acmanager://` URL launch + shared-memory hijack is the reliable path.

**Rig left clean:** `surfaces.ini` restored to stock (`ALLOW_CUSTOM_AI_MANIPULATION` removed); AC/CM
left running. Re-drive recipe: apply `.scratch/part-g/surfaces_customai.ini` → launch via the CM URL
preset → `python .scratch/part-g/race_drive_diag.py <dur>` → coach with
`python .scratch/real_coach.py <driven.json> [reference.json]`.

---

## Prior (2026-06-22 FINAL — OFFLINE FRONTIER-COACHING PROGRAM COMPLETE; only the RIG step (#277) remains)

**Every north-star coaching capability the operator named is now built + merged.** The lone remaining
step toward the in-the-ear coach is the rig-gated live activation
[#277](https://github.com/agorokh/ac-copilot-trainer/issues/277) — it needs the physical rig (AG_PC +
AC), so it could not be done/verified this autonomous run.

Capability → module (all merged): **mechanics** `setup_model` · **setup→symptom** `setup_knowledge` +
`corner_attribution` · **tyres/compounds** `tyre_model` · **weather/track condition** `conditions_model`
· **track nuances** `track_reference` · **brake-bias effect** `corner_attribution`/`coach_handoff` ·
**trail-braking methodics** `trail_brake` (#296/PR #297) · **machine handoff** `coach_handoff` (#289) ·
**live observer core** `realtime_observer` (#293) · **debrief integration + live forwarding**
`coach_report`/`protocol` (#291).

**Newest merge — #296 / PR #297 — trail-braking analyzer** (`tools/ai_sidecar/trail_brake.py`): per
corner scores trail overlap (brake∩steer), brake-off-vs-apex (corner-fraction), and release smoothness
→ classifies `good_trail_brake`/`brakes_early_then_coasts`/`trails_too_deep`/`abrupt_release`/
`straight_braking`/`no_braking` with coaching. Honest: inferred from brake+steer overlap + decel, no
direct load-transfer measurement. 8 tests; verified on real demo laps.

**Trail-braking wired into the coaching output — #299 / PR #300 MERGED:** `build_structured_debrief`
now emits a per-corner `trail_braking` block (text + JSON), `format_debrief` renders a
"Trail braking (N corner(s) to work on)" section, and `protocol.build_brain_followup` forwards it to
live clients as `trailBraking` — mirroring the #291 tyre/conditions/track integration. So **every
named capability is now both built AND flowing into the coaching output.** Verified on real demo laps
(T2/T4/T5 abrupt-release surfaced).

**Open follow-ups (all tracked, none blocking):**
[#277](https://github.com/agorokh/ac-copilot-trainer/issues/277) — RIG live activation (the one
remaining north-star step; needs AG_PC + AC) ·
[#301](https://github.com/agorokh/ac-copilot-trainer/issues/301) — optionally fold trail-braking into
`coach_handoff`/`corner_attribution` (enhancement; data already consumable via `trail_braking`) ·
[#278](https://github.com/agorokh/ac-copilot-trainer/issues/278) — lupa replay-wheels test fidelity ·
a Windows path-guard bug in `process_miner.normalize_path_list` (filed as a spawn-task chip) ·
process-miner still mining bot boilerplate into `.claude/rules/learned/local/*.md` (noise filter).
**Housekeeping:** local `main` carries a stray prior-session chore (`b620a06`) not on `origin` —
branch all work from `origin/main`.

---

## Prior (2026-06-22 LATER — REAL-TIME COACHING PATH: 3 deliverables MERGED)

**The offline real-time-coaching upgrade is DONE — all three offline-buildable pieces merged this run**
(each through multi-bot review **+ a 12-agent adversarial pre-merge workflow**; every real finding fixed-forward):

- **#289 / PR #290 MERGED — structured coach-handoff protocol** (`tools/ai_sidecar/coach_handoff.py`):
  versioned per-corner verdict envelope `{v, lap, car_id, track_id, total_time_lost_s,
  top_focus_corner, balance, corners[corner, time_loss_s, cause_class, confidence, advisory, symptom,
  coaching, suggested_setup_delta]}` for a downstream RL/agentic coach. `suggested_setup_delta` is
  cause- AND car- AND confidence-gated: technique corners → no change; braking/exit deltas fire only
  while SUSPECTED and defer to the confirmed per-wheel verdict; 911-bias advice gated to the
  rear-engine 911. Full `cause_class` enum documented (incl. `setup+technique`); the delta
  self-describes its `advisory`/`confidence`.
- **#291 / PR #292 MERGED — tyre/conditions/track-reference integrated into the debrief**
  (`coach_report.py` + `protocol.py`): `build_structured_debrief` now emits `tyres`/`conditions`/
  `corner_reference` (text + JSON), forwarded to live clients by `build_brain_followup`
  (`tyres`/`conditions`/`cornerReference`). Honest by construction — tyre block suppressed in the wet
  (slick model invalid); conditions surfaced from temps alone; a slower reference is never published
  as a target; reference labeled corpus-best, never a fabricated GGV optimum; inline lap_complete
  lap-number normalized into `lap.lap_n` for tyre warm-up classification.
- **#293 / PR #294 MERGED — real-time observer core** (`tools/ai_sidecar/realtime_observer.py`):
  `RealtimeObserver` streams live frames → grounded `late_brake` + `apex_deficit` advisories vs the
  per-corner reference. Lap detection matches in-sim `delta.lua` (true wrap vs pit/teleport vs
  **deferred-lapCount**); trail-brake-aware (no false "brake!" when the driver braked early); brake
  eval spans **upstream** of turn-in; honest corpus-vs-GGV source label; 1-based turn labels.
  Pure-stdlib, replay-tested; verified on real demo laps. Live wiring is **#277** (rig-gated).

**Discipline that held (again):** every output honest about its data limits — confirmed-axle
deference, GGV-vs-corpus labeling, wet-tyre suppression, lap-count gating. ~20 bot threads across 4–6
rounds per PR, **plus** a 12-agent adversarial workflow that caught the GGV-vs-corpus mislabel the bots
missed. Filed a spawn-task chip for a real Windows path-guard bug in `tools/process_miner/`
(`normalize_path_list` uses `Path.is_absolute()`, which misses `/etc/passwd` on Windows).

**THE remaining north-star step — [#277](https://github.com/agorokh/ac-copilot-trainer/issues/277) (RIG):**
wire `RealtimeObserver` into the sidecar's live `telemetry_tick` stream (the observer already
normalizes that payload shape; the high-rate contract must add `spline`), deliver `archivePath` on
lap_complete, render `debriefSource==brain` + the live advisories in `ws_bridge.lua`, and drive a real
lap to confirm the in-the-ear coach end-to-end. THE in-the-ear coach.

**Housekeeping:** local `main` still carries one stray prior-session chore (`b620a06`,
`.cursor/hooks.json` untrack) not on `origin` — branch all work from `origin/main`; a post-merge
steward should reconcile it. The process-miner is still mining bot BOILERPLATE into
`.claude/rules/learned/local/*.md` (noise filter needed).

---

## Prior (2026-06-22 — FRONTIER COACHING PROGRAM: 6 deliverables shipped; real-time path is next)

**Five offline pillars MERGED + a 6th in PR. Remaining: the real-time path (the north star).**
Shipped this run (each through full multi-bot review, every real finding fixed):
- **#266 telemetry capture** (per-wheel omega/slip/tyre-temp, schema v2) ·
  **#275 brain wired into the live lap_complete path** (`build_structured_debrief` +
  `build_brain_followup` + `_send_brain_followup`) ·
  **#280 tyre thermal model** (`tyre_model.py`: window/warm-up/degradation/imbalance/hot-pressure,
  compound-aware) · **#282 conditions→grip model** (`conditions_model.py`: trackGripLevel
  normalization + regime gating + qualitative temp) · **#286 per-corner track reference**
  (`track_reference.py`: GGV optimal + corpus best, PR open).
- Verified-knowledge nodes banked: `tyre-thermal-knowledge-2026-06-21.md`,
  `conditions-grip-knowledge-2026-06-21.md`, `setup-aware-coaching-2026-06-20.md`.
- **Discipline that held:** Understand-first (found the brain orphaned → wired not rebuilt); every
  physics layer adversarially red-teamed (killed an impossible gas-law coupling, fabricated °C→grip%,
  archive over-claims); ~30 bot threads resolved; every model ships its honest data-limits.

**REMAINING program (dependency-ordered — the real-time coach is the north star):**
1. **Structured coach-handoff protocol** — a versioned per-corner verdict message
   `{corner, time_loss_s, cause_class (setup|technique|grip), confidence, suggested_setup_delta}`
   for an RL/agentic coach. `cornerAnalysis` (from #275) already emits the shape; formalize + wire
   `setup_optimizer.suggest_next_setup` into the delta.
2. **Real-time observer** (`realtime_observer.py`) — streaming grip/tyre-fade observer in the sidecar
   consuming the high-rate telemetry; updates the grip envelope + flags fade/lockup/cold-tyre live.
3. **Live brain-grounded advisories (RIG):** [#277](https://github.com/agorokh/ac-copilot-trainer/issues/277) —
   deliver `archivePath` on lap_complete + render `debriefSource==brain` in `ws_bridge.lua`; drive a
   real lap to confirm CONFIRMED per-wheel attribution end-to-end. THE in-the-ear coach.
4. **Integrate tyre/conditions/track models into the debrief** — add their sections to
   `build_structured_debrief` (thin wiring; the models exist + are tested).

**Open follow-ups:** [#277](https://github.com/agorokh/ac-copilot-trainer/issues/277) (live activation, rig),
[#278](https://github.com/agorokh/ac-copilot-trainer/issues/278) (lupa replay-wheels test fidelity).
**Process-miner noise (file an issue):** the learned-rules miner is mining bot BOILERPLATE
(rate-limit/quota/"Persistent review updated"/"Action performed" comments) into
`.claude/rules/learned/local/*.md` — its noise filter should drop non-substantive bot comments.

---

## Prior (2026-06-21 — foundation + brain-wiring shipped)

**Autonomous program toward the north star (real-time AI coach > human at mechanics/tyres/conditions/
technique).** An Understand workflow mapped the platform and found the decisive fact: the full
setup-vs-technique attribution **brain already existed + was tested but ORPHANED** — the live path
used only shallow min/apex-speed ranking. So the high-leverage moves were *capture* + *wiring*, not
reinvention. Both shipped tonight:

- **#266 / PR #274 MERGED — telemetry capture (schema v2 foundation):** per-wheel
  `wheelAngularSpeed`/`wheelSlip`/`tyreCoreTemp` persisted to the lap trace via a shared
  `wheel_read.lua`; TRACE_FIELDS 10→22 (byte-identical Lua/Python); old 10-field archives still
  validate + convert; all-zero + partial-wheel-read guards prevent false lockups. Survived 3 bot
  passes (6 real fixes).
- **#275 / PR #276 MERGED — brain wired into the live path:** `coach_report.build_structured_debrief`
  (machine-readable {text, corners[cause_class/confidence/advisory/coaching], balance}) +
  `protocol.build_brain_followup` (resolves inline trace OR safe `archivePath` + optional
  `referenceArchivePath`; traversal-hardened) + `server._send_brain_followup` (non-blocking
  follow-up). Live debriefs now use full setup-vs-technique attribution, not min/apex ranking.

**Remaining program (dependency-ordered, from the gap analysis — all offline-testable except where noted):**
1. **`tyre_model.py` (NEXT, build-ready):** optimal-window/warm-up/degradation/imbalance + modelled
   hot pressure. Verified physics already banked:
   [`tyre-thermal-knowledge-2026-06-21.md`](../03_Investigations/tyre-thermal-knowledge-2026-06-21.md)
   (compound windows, gas-law-correct ~+1 psi/10°C coupling, imbalance thresholds, honest core-only
   limits). Mirror `setup_knowledge.py` data + the Tier-A/Tier-B honesty split. Consumes #266 temps.
2. **`conditions_model.py`** — `conditions{ambient/track temp, trackGripLevel, weather}` (already
   archived) → grip modifier + cross-session delta normalization.
3. **`track_reference.py`** — per-corner optimal entry/apex/exit-g envelope from GGV QSS + the human
   corpus.
4. **Structured coach-handoff protocol** — versioned per-corner verdict message for an RL/agentic
   coach (cornerAnalysis already emits the shape).
5. **Real-time observer** — streaming grip/tyre-fade observer in the sidecar.
6. **Live brain-grounded advisories (RIG):** [#277](https://github.com/agorokh/ac-copilot-trainer/issues/277)
   — deliver `archivePath` on lap_complete + render `debriefSource==brain` in `ws_bridge.lua`; drive
   a real lap to confirm CONFIRMED per-wheel attribution end-to-end.

**Other open follow-ups:** [#278](https://github.com/agorokh/ac-copilot-trainer/issues/278) (lupa
replay-wheels test fidelity). Branch hygiene: a `wip/prior-session-leftovers` branch holds older
uncommitted vault/architecture drafts. Local `main` had 1 stray unpushed chore (b620a06) — left
alone (protect-main); branch all work from `origin/main`.

---

## Prior (2026-06-20 — CONFIRMED setup attribution shipped (#268); coaching brain complete)

**#268 MERGED — confirmed axle/wheelspin attribution.** The coaching engine now CONSUMES optional
per-wheel channels (`wheelAngularSpeed_{fl,fr,rl,rr}` / `wheelSlip_{...}` in the trace) and upgrades
brake-bias / exit-traction from a *suspicion* to a **confirmed verdict** naming the cause: e.g.
"FRONT axle locks first (slip −0.18) → bias 66% too forward (911 wants ~50-56%); move it rearward"
and "rear wheelspin (slip 0.22) → raise TC / reduce DIFF_POWER". Keyed on the COMPUTED signal
(`lock_axle`/`wheelspin`), so confirmation never outruns the data; with no per-wheel data it stays an
honest archive suspicion. `tools/ai_sidecar/corner_attribution.py::corner_live_signals` + `coach_lap`
auto-inject. 62 coaching tests.

**ONLY remaining piece — [#266](https://github.com/agorokh/ac-copilot-trainer/issues/266) capture half (RIG-VERIFIED):** write `wheelAngularSpeed`/`wheelSlip`
per-frame into the Lua trace (`src/ac_copilot_trainer/modules/lap_archive.lua` + the per-frame sample
build in `ac_copilot_trainer.lua` ~L2555 region) + bump the DUAL `TRACE_FIELDS` (Lua `lap_archive.lua`
L58 **and** Python `tools/ac_harness/reference_lap.py` — `test_reference_lap` asserts they match) +
drive ONE live lap to verify captured values. Offsets are known (live drivers already read
`wheelAngularSpeed` via `slip_ratio`). Then run `python -m tools.ai_sidecar.coach_report LAP.json`
on the real lap → a CONFIRMED debrief = the operator's "cleanly distinguish why a turn was fast."

---

## Prior (2026-06-20 — SETUP-AWARE PRO COACHING shipped; #259 merged; #244 closed)

**New capability (#264 → PR [#265](https://github.com/agorokh/ac-copilot-trainer/pull/265)):** the
harness can now comprehend a car setup and attribute a corner's pace to **setup vs technique** — the
pro-race-engineer brain. Four stdlib-only modules under `tools/ai_sidecar/`:
- `setup_model.py` — typed semantic `CarSetup` (brake bias %, ABS/TC, pressures+splits, ARB balance,
  wings, diff, compound) from `.ini` / `setup.snapshot` / live `ac.getSetupSpinners()`.
- `setup_knowledge.py` — **adversarially-verified** GT3 knowledge (17 params; `speed_dependence`
  AERO/MECHANICAL/NEUTRAL + `car_dependent` flags; Tier-B live-channel map).
- `lap_dynamics.py` — lat g = v²·κ, long g = dv/dt from the trace; corner segmentation; signatures.
- `corner_attribution.py` — `compare_laps`, `analyze_balance` (the #1 discriminator: speed-bin a grip
  limitation → aero vs mechanical lever class), diagnostic engine (setup vs technique). `coach_report.py`
  renders the debrief + CLI.

**Verified physics (red-team-corrected, do NOT simplify away):** aero is speed-gated (∝v²),
mechanical is speed-flat → grip *saturation* in high-speed corners=aero, low-speed=mechanical; rake
direction is car-dependent (prefer wings); the rear-engine 911 GT3 R wants LOWER front bias (~50-56%).
**Honest data split:** archive trace (`spline/speed/throttle/brake/steer/gear/position`) localizes a
loss to a phase+speed band; axle-lockup (brake bias) / pressure / TC attributions are *suspicions*
until live channels are supplied — then verdicts. Built on adversarially-verified research:
[`03_Investigations/setup-aware-coaching-2026-06-20.md`](../03_Investigations/setup-aware-coaching-2026-06-20.md).

**Verified on real Magione geometry** (fast_lane.ai 1754 pts, GGV 77.84s): student-vs-optimal debrief
correctly split "carried too little apex speed → TECHNIQUE" from "at the grip limit → SETUP". 51 tests.

**Next:** (a) **#266 — persist `wheelSlip[4]` + `wheelAngularSpeed[4]`** to lap archives (research's #1
lever: promotes 8/14 rules suspicion→verdict; the live harness already reads them). (b) close the loop
to `setup_optimizer.suggest_next_setup` + live `ac.setSetupSpinnerValue` (auto-apply a suggested change
and re-test — EPIC #86 surface). (c) coach a REAL captured lap on the rig once #266 lands the channels.

**Merge state:** #259 (Stage-4 line + ceiling analysis) MERGED (squash `8cd3112`); integrity caveat
#263 MERGED (aero knob live-disproven, AiPointExtra version-fragile). PR #265 (setup coaching) open,
51 tests, ruff-format clean — merge when CI/bots green. Rig left clean (surfaces stock, AC stopped).

---

## Prior (2026-06-20 FINAL — #244 FRONTIER closed: verified ceiling 82.7s (human +8s); ~70s grip-bound-unreachable, aero LIVE-DISPROVEN)

**Investigation CLOSED with the empirical ceiling found.** After unblocking the rig (Steam
elevation-mismatch fix + **minimize windows so CM auto-start clicks land** — the foreground-steal
gotcha), I live-tested the remaining ~70s hypotheses to conclusion:
- **optimized line + 1.5g = 82.7s** (confirmed ~0.8s vs 83.5s stock — the min-curvature line works).
- **aero lateral grip = LIVE-DISPROVEN**: k=0.0003 → 96s (regressed), k=0.0001 → spins out (5 teleports).
  The GT3 R cannot hold >~1.5g in Magione's corners in AC, so the offline ~70-73s QSS is NOT
  realizable — the model was over-optimistic about *realizable* grip.
- **Verdict: ~82.5s is the CAR'S PHYSICAL FLOOR (TC off), not a controller gap.** Instrumented a clean
  lap: the 5.6s QSS-gap is ~5.9s **longitudinal** (under 95% of v_target 66% of the lap); **lateral is
  already near-perfect (0.43 m mean cross-track)**. Pushing exit throttle to close it **spins the car**
  (TC-off traction limit). So an LQR/MPC controller would gain ~nothing — there is no slack; the binding
  constraints are mechanical grip (1.5g; 1.6g spins) + TC-off traction. **Do NOT build a learned/MPC
  controller to chase pace — proven it won't help.** Only paths past ~82.5s change the *problem*: enable
  TC, a higher-grip/power car, or a faster track. Diagnostic conclusion:
  [#244#issuecomment-4756727418](https://github.com/agorokh/ac-copilot-trainer/issues/244#issuecomment-4756727418).
  Live-relaunch recipe that works: minimize all windows (foreground-steal) before `/session/start`.

**Merge state:** human-beating controller MERGED (#256). Stage-4 optimized line + CSV-free builder +
ceiling analysis = PR [#259](https://github.com/agorokh/ac-copilot-trainer/pull/259) (open, 25 tests,
ruff clean) — merge when CI/bots green. `lat_aero_k` stays an off-by-default experimental knob
(live-disproven, documented). Do NOT re-chase aero grip-scaling — it spins. Rig left clean (surfaces
stock, daemon/AC stopped). Launch recipe that works: minimize windows before /session/start.

## Resume here (2026-06-20 — #244 FRONTIER: human beaten 83.5s (merged); ~70s path offline-proven; live aero blocked by rig state) [SUPERSEDED — aero live-disproven above]

**Headline (MERGED to main, PR #256, squash `158a796`):** the autonomous controller beats the human —
**106.8s → 95.3 (GGV) → 91.8 (curvature-FF) → 90.28 → 86.4 → 83.5s (1.5g)**; human relaxed = 90.7s.
Repeatable, AC-valid (lap.valid=true + delta telemetry). Curvature-FF lateral (`ff_sign=-1` from
corr(human_steer, line_κ)=+0.93) holds the line so Stanley only trims; grip self-play ceiling = 1.5g
(1.6g spins).

**Stage 4 (PR [#259](https://github.com/agorokh/ac-copilot-trainer/pull/259), open, 25 tests, ruff
clean):** `load_track_widths` + `min_curvature_line` (TUMFTM) + `optimize_fast_line` (line is already
near-optimal → only ~1s). **The real ~70s lever = speed-dependent AERO lateral grip** (`lat_aero_k`,
`ggv_speed_profile_from_model` is CSV-free): on the optimized line, QSS **72.96s @k=0.0003**, **70.91s
@k=0.0005** (physically ~2.4-3g lateral @200km/h, which the GT3 R has). Only 22% of Magione is
aero-irrelevant slow corners → the ceiling genuinely reaches ~70-73s QSS → live ~76-79s.

**LIVE aero verification = BLOCKED by rig state this session (not the method):**
1. **Steam elevation mismatch** ("Steam API failed to initialize") — FIXED per runbook (`steam
   -shutdown` + non-elevated relaunch via `explorer.exe`).
2. Then the **menu-skip race stuck** (acs frozen at pre-drive menu every attempt; CM auto-start clicks
   not landing — the agent-window foreground-steal gotcha); Windows GUI MCP went unresponsive.
3. **`.scratch/part-g/` was WIPED mid-session** (raw `human_laps.csv` + live drivers lost). Recovered
   by making the GGV path CSV-free + hardcoding the verified fits.

**NEXT SESSION — to land ~70s live (clean rig):**
- Reconstruct/launch: re-apply `surfaces.ini` (`[SURFACE_0] WAV_PITCH=extended-0` + `[_EXTRA_PERMISSIONS]
  ALLOW_CUSTOM_AI_MANIPULATION=1`); ensure Steam is **non-elevated** (explorer launch); **minimize the
  agent window** so CM auto-start clicks land (foreground-steal fix); daemon `--launch-mode cm`.
- Run `.scratch/part-g/race_drive_aero.py <dur> <k_aero> <accel_peak> 1 <cff_ay_cap_g>` (self-contained,
  curvature-FF + ax-FF + slip limiter + optimized line + aero grip). Self-play k_aero 0.0003 → up until
  validity breaks (tap lap.valid). Constants baked: FF c1=-5.1 c2=-0.0033 ff_sign=-1, r_eff=0.347, GGV
  brake 0.955+0.0214v, ellipse 1.55.
- Physics note: at 1.5g (flat, no aero) the lap is grip-bound ~82-83s live; aero grip in fast/medium
  corners is the only lever left to ~70-78s. The line is near-optimal (~1s).

## Resume here (2026-06-20 — #244 FRONTIER: HUMAN BEATEN 90.7s→83.5s; Stage 4 line is the path to ~70s)

**The autonomous controller now beats the human and is repeatable + AC-valid.** Live on AG_PC, GT3 R,
carcsw: **106.8s (old) → 95.3 (GGV) → 91.8 (curvature-FF) → 90.28 (Stage 2, 1.2g) → 86.4 (1.35g) →
83.5s (1.5g, real-GT3 grip)**; human relaxed = 90.7s. Every lap `lap.valid=true` with `delta`
telemetry (sidecar tap). Branch `feat/issue-244-frontier-racing-controller`, draft PR
[#256](https://github.com/agorokh/ac-copilot-trainer/pull/256) (Stages 1–3 + grip self-play, 25
tests, ruff clean). Evidence: [#244#issuecomment-4754911396](https://github.com/agorokh/ac-copilot-trainer/issues/244#issuecomment-4754911396).
Full write-up: [[frontier-controller-ggv-2026-06-19]] (UPDATE section).

**Winning live config** (`.scratch/part-g/race_drive_ff.py`): `steering_mode="curvature_ff"`,
`ff_sign=-1` (Magione; from `corr(human_steer, line_kappa)=+0.93`), `ax_feedforward=True`,
`accel_peak_g≈1.1`, `lat_grip_g=1.5`, slip limiter `r_eff=0.347`. Curvature-FF holds the line so
Stanley only trims (Stanley alone saturated); that unlocked Stage 2; grip self-play found 1.5g is the
ceiling (1.6g fails — keep-last-valid).

**Next → Stage 4 (toward ~70s):** at 1.5g the apexes are LINE-limited (stock `fast_lane` tighter than
optimal). Build an offline min-curvature optimized line (TUMFTM-style QP, corridor bounded by the
human no-cut envelope), re-run the GGV profiler on it, bake `(x,y,kappa,v_target)`. QSS ceiling on the
current line is ~78s at 1.5g; a better line + speed-dependent aero lateral grip push toward ~70s.
**Rig left clean** (surfaces stock, daemon/AC stopped). Merge PR #256 when CI/bots green.

## Resume here (2026-06-19 NIGHT — #244 FRONTIER controller: GGV profiler LIVE 95.3s; Stage 3 lateral is the wall to beat human 90.7s)

**Operator asked for RESEARCHER-grade frontier (beat human, toward ~70s).** Drove a 15-agent
deep-research workflow + multi-model council (Gemini) + empirical plant-ID, then built + live-verified
a GGV friction-circle controller on `AG_PC`. Full write-up: [[frontier-controller-ggv-2026-06-19]].
Branch `feat/issue-244-frontier-racing-controller`, draft PR
[#256](https://github.com/agorokh/ac-copilot-trainer/pull/256).

**Delivered + LIVE-VERIFIED — Stage 1 (`tools/ac_harness/ggv_profile.py` + `RacingDriver.from_ggv_profile`):**
forward-backward QSS min-time speed profile vs a de-contaminated GGV fitted from `human_laps.csv`
(aero-rising braking `0.95+0.0215·v_ms` g; lateral 1.2g mech peak; fitted ellipse n), arc-length
Menger curvature, baked `v_target` tracked verbatim. **old Stanley 106.8s → GGV 95.3s** flying lap,
AC-valid, 0 stuck, 216 km/h. QSS ceiling 86.2s. 17 unit tests, ruff clean.

**Built but OFF by default — Stage 2 (FF + slip limiter):** `_profile_ax` feedforward (max-not-sum,
gated) + pure `slip_ratio`/`slip_limited_controls` (from `acpmf_physics wheelAngularSpeed@104`, not AC
`wheelSlip`) + `accel_peak_g`. **LIVE FINDING: enabling FF+aggressive accel on Stanley REGRESSES
95.3s→104-110s** — Stanley can't hold the line at the higher corner speeds (steer saturates →
overshoot). So `ax_feedforward` defaults OFF; shipped controller = verified 95.3s. r_eff≈0.347.

**THE WALL → Stage 3 (next session, to beat human 90.7s):** Stanley is the binding constraint.
Implement **curvature feedforward + velocity-scheduled feedback lateral** (Kapania/Gerdes:
`δ = wheelbase·κ + K_ug·v²κ + k·e_lookahead`); fit steer-per-radian + `K_ug` from `human_laps.csv`
(steer vs v²κ). THEN re-enable Stage 2 FF (longitudinal gains unlock once the line holds), then
Stage 4 min-curvature optimized line (stock fast_lane is tighter than the human line → apex-limited).
Rig recipe + drivers in `.scratch/part-g/` (`race_drive_ggv.py`, `race_drive_ggv2.py`), surfaces edit
saved at `.scratch/part-g/surfaces_customai.ini`. Rig left clean (surfaces stock, daemon/AC stopped).

## Resume here (2026-06-19 LATER — #244 PR #248 MERGED + LIVE-VERIFIED on the rig: steering wall broken; pace residual remains)

**Ran `/autonomous-deliver 244` ON the rig (`AG_PC`)** — the prior "Mac can't reach the rig" blocker
was moot. PR [#248](https://github.com/agorokh/ac-copilot-trainer/pull/248) **MERGED** (`88249bf`).
Full write-up: [[stanley-steering-live-verified-2026-06-19]]. Evidence comment:
[#244#issuecomment-4754057626](https://github.com/agorokh/ac-copilot-trainer/issues/244#issuecomment-4754057626).

**PROVEN live (the wall is broken).** Merged `RacingDriver.from_human_profile(...)` Stanley controller
drove car 0 around Magione via carcsw, no human → **3 AC VALID laps** (`completedLaps` 0→3, trainer
`lap` frames `valid:true`), best flying lap **106.8 s**, max **207.6 km/h**, gears 1–6, 0 stuck. Sidecar
tap: **`delta=2935`** live delta-to-reference + `coaching.snapshot=3797` — the lap/delta telemetry that
was missing now flows. The trainer captured the agent's lap as its coaching reference
(`journal/laps/lap_*_106813_*.json` + persisted `ks_porsche_911_gt3_r_2016__magione.json`). Screenshots
inspected (`.scratch/part-g/stanley_*.png`).

**Residual (why #244/#154 stay OPEN).** Best clean lap 106.8 s / avg ~83.5 km/h = ~85% of the human's
relaxed laps (90.7 s / 98.7 km/h, `.scratch/part-g/human_laps.csv`). The literal `avg ≳100 km/h` bar is
**not met**; an aggressive-throttle tuning pass REGRESSED to 124.6 s (TC-off wheelspin) → merged defaults
are near the controller's stable optimum. Closing the last ~15% is separable controller-sophistication
(use human gas/brake trace directly, or MPC) and touches `racing_driver.py` (#244's file group), so it
stays as remaining Part-G scope on #244 — **not** a new overlapping issue. Operator decision: accept the
wall-break + telemetry milestone as Part-G-core-done (pace tracked), or hold #244 for the pace bar.

**Rig state left:** `surfaces.ini` Custom-AI edit (`[SURFACE_0] WAV_PITCH=extended-0` +
`[_EXTRA_PERMISSIONS] ALLOW_CUSTOM_AI_MANIPULATION=1`) was **restored to stock** from
`surfaces.ini.bak-precustomai`; AC/sidecar/daemon stopped. Live driver: `.scratch/part-g/race_drive_stanley.py`.

**#246 (lap-freeze) — CLOSED this session (LIVE-VERIFIED).** Timestamped tap of the script-frame
`coaching.snapshot` stream (`.scratch/part-g/freeze_probe.py`) over a 250 s drive: median gap 103 ms,
max **255 ms**; at both S/F crossings the max stall was **217 ms / 255 ms** (not ~2 s). Archives still
land off-frame (`lap_*_1_128111_*.json`, `lap_*_2_106859_*.json`, both `valid=True`). PR #249 (`4e2a310`)
confirmed; closed with evidence ([#246#issuecomment-4754133099](https://github.com/agorokh/ac-copilot-trainer/issues/246#issuecomment-4754133099)).
`setup.experiment.record` is a trainer→sidecar internal frame (not tap-visible); its retry path stays
covered by `tests/test_lap_archive_async.py`.

## Resume here (2026-06-19 — #244 / PR #248 [SUPERSEDED — now MERGED + live-verified above]: Stanley steering built; rig daemon blocks live proof)

**Read [#244](https://github.com/agorokh/ac-copilot-trainer/issues/244) and draft PR
[#248](https://github.com/agorokh/ac-copilot-trainer/pull/248) first.** This is EPIC
[#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) Part G continuation after the
human-lap fixture landed.

**Delivered in PR #248.** `tools/ac_harness/ai_line.py` now has cyclic path projection plus a
`StanleySteering` controller that preserves the harness sign convention (`steer > 0` turns right).
`tools/ac_harness/racing_driver.py` defaults to Stanley steering, keeps
`steering_mode="pure_pursuit"` for comparison, loads/resamples the committed
`tests/fixtures/racing_human_profile_magione.csv`, and exposes
`RacingDriver.from_human_profile(...)` so the captured human speed profile can drive the controller.
Exports were added from `tools.ac_harness`.

**Verification completed off-sim.** Targeted tests passed (`60 passed`), ruff format/check passed, and
`uv run --extra dev make ci-fast` passed (`1131 passed, 75 skipped`, coverage `82.67%`). Gemini/Codex
review threads were addressed and resolved: Stanley projection now computes segment geometry once for
the final nearest segment, human-profile interpolation precomputes `norms`, and
`RacingDriver.from_human_profile(...)` samples by fast-line lap-distance fraction instead of ordinal
point index. GitHub build, conformance, canonical-docs, and CodeRabbit checks passed on the draft PR;
Cursor Bugbot was still pending when this handoff was written.

**Runtime gate still open.** Mac-side rig probes reached Tailscale node `pc` / `100.75.251.87` by ping,
but harness daemon health/TCP probes on ports `9876` and `8765` timed out, and SSH denied access
(`Permission denied (publickey,keyboard-interactive)`). Do **not** close #244 or the #154 epic until
the Windows rig daemon is reachable and this branch proves a VALID Magione lap at human-comparable
pace with `lap`/`delta` telemetry/HUD evidence captured.

## Resume here (2026-06-19 — #246 / PR #249 MERGED: lap archive writes moved off the S/F frame; live freeze proof pending)

**[#246](https://github.com/agorokh/ac-copilot-trainer/issues/246) remains OPEN pending live
Windows/AC proof.** PR [#249](https://github.com/agorokh/ac-copilot-trainer/pull/249) **MERGED**
`2026-06-19T08:05:01Z` as squash
[`4e2a310`](https://github.com/agorokh/ac-copilot-trainer/commit/4e2a310232beb19ae6c261ca024411512185379a).
The PR title used `#246` rather than a closing keyword, so GitHub did not auto-close it. Leave it
open until a rig run proves the freeze is gone, then close with evidence.

**What changed.** The lap-complete boundary no longer builds and writes the full lap archive on the
render/CSP script frame. It now queues `lapArchive.createWriteJob(...)`; the app pumps a bounded
`LAP_ARCHIVE_ROWS_PER_FRAME = 64` slice after `wsBridge.tick()` / `wsBridge.pollInbound()`. Archive
records stream schema-v1 JSON to `*.tmp`, flush/close, atomically rename to final `*.json`, rotate the
archive, and then queue setup-experiment notification. `setup.experiment.record` paths are retained
and retried until `sendSetupExperimentRecord()` returns true, covering sidecar startup/reconnect.

**Verification completed off-rig.** Local `make ci-fast PYTHON=.scratch/venv-test/bin/python` passed
(`1117 passed, 75 skipped`, coverage 82.51%). Focused archive regression
`tests/test_lap_archive_async.py` proves multi-step temp-file streaming and asserts the lap boundary
queues work instead of calling `lapArchive.write` / `lapArchive.buildRecord`; it also asserts archive
pumping happens after WS tick/poll and before notification retry. GitHub build + conformance passed;
GraphQL review threads resolved; CodeRabbit confirmed the final fix. Post-merge classification: no
migration/env/deps/script/workflow flags.

**Live proof still needed.** On `AG_PC` / Windows AC, drive a lap crossing at Magione (human driving
is fine) and confirm the old ~2 s visual freeze at S/F is gone. Also confirm the completed archive
still lands and the sidecar receives `setup.experiment.record` after reconnect/startup. If PASS, close
[#246](https://github.com/agorokh/ac-copilot-trainer/issues/246) with the merge commit, lap-crossing
observation, archive path, and sidecar notification evidence. If FAIL, keep #246 open and file the
remaining hot path separately.

## Resume here (2026-06-19 — #241/#242 MERGED: racing driver on `main`; STEERING is the wall; human-lap data is next)

**Read [#244](https://github.com/agorokh/ac-copilot-trainer/issues/244) first — it is the cold-start
handoff.** Account changeover mid-effort; this is the resume pointer.

**Where it stands.** The hands-off self-test scaffolding is merged (#233 CM launch, #236 self-test
runner, #239 HUD capture). The **racing driver** shipped in
[#241](https://github.com/agorokh/ac-copilot-trainer/issues/241) / PR
[#242](https://github.com/agorokh/ac-copilot-trainer/pull/242) **MERGED** `2026-06-19T06:25:05Z` as
squash [`372156a`](https://github.com/agorokh/ac-copilot-trainer/commit/372156a0a91926165677b7444f81d5a48572d9ab):
- `tools/ac_harness/racing_driver.py` follows `fast_lane.ai`'s embedded speed profile with braking
  points / trail braking / traction throttle (12 tests).
- **Gear bug fixed**: 1st gear's limiter (~7400 rpm) sat below the old 7600 shift point → car was
  **stuck in 1st** at 80 km/h. Now shifts **1→4**, **146 km/h** (was 52), range 12–146.
- `tools/ac_harness/racing_telemetry.py` — **human-lap recorder** (CSV of inputs+dynamics+lap/position).

Post-merge classification: **no migration/env/deps/script/workflow flags.**

**The wall = STEERING (not the racing logic).** `PurePursuit` cuts apexes / understeers → corners
crawl, lap scored **INVALID** → no `lap`/`delta` telemetry / no clean coaching reference. The input
channel is fully racing-capable (333 Hz, 1.48 g brake, wheelspin — proven). Full write-up:
[`03_Investigations/racing-driver-and-controller-2026-06-17`](../03_Investigations/racing-driver-and-controller-2026-06-17.md).

**Next (the plan in #244).** Operator can drive 5–10 real laps → record with
`python -m tools.ac_harness.racing_telemetry --out human_laps.csv --laps 10` → derive the human speed
profile / braking points / corner speeds / grip envelope → build a path-tracking steering controller
(Stanley/MPC) at the human's pace, replacing pure-pursuit. Acceptance: a VALID lap at ≳100 km/h avg
with `lap`/`delta` telemetry flowing.

**Rig:** AC currently down; daemon down; magione `surfaces.ini` Custom-AI edit was restored to stock
(re-apply per #244 for the carcsw controller; not needed for human driving). Gear encoding: AC
`gear` 0=R/1=N/2=1st (log `gear-1`). Live drivers/probes in `.scratch/part-g/`.

## What was delivered (2026-06-19 — #241 / PR #242 racing driver MERGED)

**[#241](https://github.com/agorokh/ac-copilot-trainer/issues/241) CLOSED / PR
[#242](https://github.com/agorokh/ac-copilot-trainer/pull/242) MERGED** `2026-06-19T06:25:05Z` as squash
[`372156a`](https://github.com/agorokh/ac-copilot-trainer/commit/372156a0a91926165677b7444f81d5a48572d9ab).
EPIC #154 Part G racing driver on `main`:

| Deliverable | Detail |
|-------------|--------|
| `tools/ac_harness/racing_driver.py` | Speed-profile following from `fast_lane.ai` with backward-pass braking points, trail braking, traction-limited throttle, gear management (12 unit tests) |
| `tools/ac_harness/racing_telemetry.py` | Human-lap CSV recorder (physics+graphics shared mem, deduped packet IDs) |
| Gear fix | 1st-gear limiter below shift point → stuck in 1st at 80 km/h; now 1→4, 146 km/h peak |
| Fixture | `tests/fixtures/racing_human_profile_magione.csv` |

**Verification:** GitHub CI green on head `d3587fc`; GraphQL `reviewThreads` 0 unresolved; 7 bot threads
all resolved (CodeRabbit + Sourcery). Post-merge classification: no flags.

**What remains:** steering controller from human-lap data ([#244](https://github.com/agorokh/ac-copilot-trainer/issues/244)) — PurePursuit understeers → INVALID laps → no `lap`/`delta` telemetry.

## Resume here (2026-06-17 — EPIC #154 #238/#239 MERGED: vision-oracle "eyes" (HUD capture) — LIVE-VERIFIED)

**[#238](https://github.com/agorokh/ac-copilot-trainer/issues/238) CLOSED / PR
[#239](https://github.com/agorokh/ac-copilot-trainer/pull/239) MERGED** (squash `3e677c7`). New
`tools/ac_harness/hud_capture.py` — the vision oracle's eyes: a **stdlib `ctypes` GDI** desktop grab
(**no new dependency**) + pure helpers (BGRA→RGB, named region crop full/left/coaching, a stdlib PNG
encoder, a mean/distinct **render-liveness** score that flags black/frozen frames). CLI
`python -m tools.ac_harness.hud_capture --out hud.png --region coaching` saves a PNG for agent-vision
HUD assertion and exits non-zero on a black frame. 15 unit tests; ruff-clean.

**Operator-grade LIVE verification (PASS, `AG_PC`):** launched AC on track via the daemon (cm) →
captured hands-off → liveness **RENDERING** (full: mean=25.7/distinct=230; coaching: mean=84.3/
distinct=61). **Inspected the PNGs**: AC live **in-cockpit at Spa** (wheel/dash/track; trainer overlay
top-left); coaching crop legible (`Practice`, `Drive/Setup/Exit` sidebar, `Session information`). The
agent-vision assertion path works. **Capture mechanism note (reusable):** AC runs borderless-windowed
→ a full-desktop GDI grab captures it (NOT black); per-window BitBlt of a fullscreen game returns black.

**The autonomous self-test now has launch + pipeline-assert + eyes — all hands-off, all live-verified.**

**Next (EPIC #154 Part G remainder — harder / data-dependent, deliberate next-session work):**
1. **carcsw drive into the self-test loop** (`self_test --drive`): re-apply the magione `surfaces.ini`
   Custom-AI permission (reverted to stock) + a magione `.cmpreset`, then `lap_driver` drives a real
   lap and the loop asserts coaching on it. *(The drive itself is the flakiest piece — menu-skip race +
   curb-clip lap invalidation; see [[autonomous-drive-live-verified-2026-06-16]].)*
2. **Wire `hud_capture` into `self_test`** as evidence on each run (capture + liveness alongside the WS
   assert; attach the PNG).
3. **Determinism-lock preset** + a CSP-side precondition assert (in-game Lua — needs rig verification).
4. **False-green-rate KPI (<5%)** — needs a human-vs-agent shadow corpus that does not exist yet; this
   is a measurement-framework + data-collection effort, not a pure code change.

## Resume here (2026-06-17 LATER — EPIC #154 #235/#236 MERGED: one-command autonomous self-test runner — LIVE PASS)

**[#235](https://github.com/agorokh/ac-copilot-trainer/issues/235) CLOSED / PR
[#236](https://github.com/agorokh/ac-copilot-trainer/pull/236) MERGED** (squash `d051096`). New
`tools/ac_harness/self_test.py` (`python -m tools.ac_harness.self_test --token …`) drives the harness
daemon **hands-off**: `/session/start` (cm) → wait driving → `/sidecar/start` → tap the sidecar WS →
assert the L1.5 producer contract (`sequence_probe`) → structured PASS/FAIL → `/session/stop`. `http`
and `tap` are injectable → 10 unit tests, no game. Builds on #233 (cm launch) + #191 (probe) + #157
(client).

**Operator-grade LIVE verification (PASS, `AG_PC`):** one command, no human at the wheel →
`outcome=driving` → sidecar up → **the trainer produced the live coaching pipeline**:
`coaching.snapshot=335, tire_temps=168, connection=34, session=1` over 35 s; L1.5 asserted OK
(`lap`/`delta` correctly conditional notes). EXIT 0. This exercises the full #170/#180/#182/#185
producer pipeline end-to-end, hands-off — the autonomous self-test the EPIC set out to build.

**Next (EPIC #154 Part G remainder):** (1) **screenshot/vision HUD oracle** — the "eyes"; capture the
AC framebuffer (full-desktop grab works for the fullscreen game; per-window BitBlt returns black) and
vision-assert the HUD render vs the WS numbers. (2) carcsw drive INTO the self-test loop (`--drive`):
re-apply the magione `surfaces.ini` Custom-AI permission + a magione `.cmpreset`, assert coaching on a
real lap. (3) determinism-lock preset + CSP precondition assert. (4) false-green-rate KPI < 5% (shadow
vs human). The launch + sidecar + pipeline-assert chain is now one command; the drive + vision + KPI
are what remain.

## Resume here (2026-06-17 — EPIC #154 #232/#233 MERGED: de-elevated CM launch — hands-off L2 keystone landed)

**Ran autonomous-deliver on the rig `AG_PC` (elevated agent shell).** Found and closed the live gap
in the merged Part F daemon (#229): it launched `acs.exe` **directly**, which trips the Steam-integrity
mismatch from the elevated shell (Steam + CM run **non-elevated**). The EPIC spec'd a CM-URL launch;
the merge took an `acs.exe` shortcut.

**[#232](https://github.com/agorokh/ac-copilot-trainer/issues/232) CLOSED / PR
[#233](https://github.com/agorokh/ac-copilot-trainer/pull/233) MERGED** (squash `c556dfe`). New
`ContentManagerActuator` (`tools/ac_harness/entry_launcher.py`) launches via
`Content Manager.exe "acmanager://race/quick?presetFile=<abs preset>"` → CM-IPC forwards to the
running **non-elevated** CM → `acs.exe` starts **non-elevated**. `make_actuator(mode)` + daemon
`--launch-mode {cm,acs}` (default **cm** on Windows), `--cm-exe`, `--cm-preset`. Reuses the shipped
detect-and-retry loop; `trigger_drive` is unsupported so the loop cold-relaunches on the menu-skip
race. Full method + gotchas: [`03_Investigations/cm-url-deelevated-launch-2026-06-16`](../03_Investigations/cm-url-deelevated-launch-2026-06-16.md).

**Operator-grade live verification (PASS, observed):** daemon in elevated shell →
`POST /session/start` (cm) → `outcome:"driving"` (shared-mem detector, sustained); `acs.exe`
**non-elevated**; on track in ~3 s; physics ~333 Hz; AC rendered on track (screenshot inspected).
`POST /sidecar/start` → external WS `hello_ack`. Guard: `/sidecar/start` before session → 409.
Off-sim: 15 new tests, ruff-clean; CI green; 6 bot threads (cursor/sourcery/coderabbit) all resolved
(fail-fast CLI validation, platform-aware defaults, absolute-path resolution).

**Next (EPIC #154 — toward fully hands-off L2):** all chain pieces now exist (launch ✓ via #233,
sidecar ✓, carcsw drive ✓ #190, asserts ✓ L1.5/oracle). Remaining **Part G**: (1) compose the full
unattended loop into one harness command (launch→sidecar→carcsw drive a lap→assert→reset); (2)
**screenshot/vision HUD oracle** (most rig-uniquely verifiable; "if you're not screenshotting it, it's
not delivered"); (3) determinism-lock preset + CSP precondition assert; (4) false-green-rate KPI < 5%.
For a real carcsw drive on magione, re-apply the track `surfaces.ini` Custom-AI permission (reverted to
stock) + create a magione `.cmpreset` (the `base test.cmpreset` used here is Porsche@Spa).

**Rig-local nit (not filed):** `tests/test_import_motec.py::test_default_output_dir_precedence` FAILS on
any box with a real AC install (incl. this rig) — `default_output_dir` discovers the live AC CSP state
dir, so the test's cwd-fallback assertion doesn't hold. Pre-existing, local-only (green on clean CI);
the test should monkeypatch the AC-state-dir lookup to be hermetic.

**Local `main` divergence (unchanged, intentional):** `dd5c613` (untrack local-baked `.cursor/hooks.json`)
is the operator's deliberately-unpushed Windows-Cursor adaptation — left as-is; vault/feature work branches
off `origin/main`. The merged `feat/issue-228` WIP was confirmed stale and discarded.

## Resume here (2026-06-16 LATER — #188 CLOSED on the rig; ran on AG_PC directly)

**[#188](https://github.com/agorokh/ac-copilot-trainer/issues/188) CLOSED.** Autonomous-deliver ran
**on the rig itself** (`AG_PC`) — the empirical question is answered: **`car.resetCounter` is PRESENT**
on this CSP build (live probe `[COPILOT][WRAP-SKEW-PROBE] resetCounter present=true value=2`).
Per the operator's own decision tree, present → close as moot; the #199 wrap-deferral is defensive-only
for resetCounter-less builds. Close comment:
[#188#issuecomment-4725615887](https://github.com/agorokh/ac-copilot-trainer/issues/188#issuecomment-4725615887).
Full evidence + Q2-moot reasoning: [`03_Investigations/issue-188-wrap-skew-rig-verification`](../03_Investigations/issue-188-wrap-skew-rig-verification.md).

**New rig-ops learning (saves ~20 min next time):** AC "Steam API has failed to initialize" was a
**Steam(elevated)/Content-Manager(non-elevated) integrity mismatch** (`ActiveProcess pid=0`). Fix =
`steam -shutdown` then relaunch Steam **non-elevated** via `explorer.exe` (auto-login, no creds).
Runbook: [`03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16`](../03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md).
**The agent shell on the rig is elevated → never launch `acs.exe` from it; always go through CM.**

**Rig launch path that works (proven this session):** Steam non-elevated + logged in → Content
Manager → Drive (Quick/HOTLAP, Porsche 911 GT3 R + Magione already configured) → **Go!** → car on
track in ~40s; the symlinked trainer auto-loads with `LAZY=PARTIAL` (its windows were already open,
so `script.update` ticks; CSP `ac.log` lands in `logs/custom_shaders_patch.log`, **not** `log.txt`).

**Post-merge reconcile (operator action — surfaced during /post-merge of #230):**
- **EPIC #154 Part F SHIPPED.** PR [#229](https://github.com/agorokh/ac-copilot-trainer/pull/229)
  *(in-session AC harness daemon)* **MERGED** to `main` (`4c8afd8`). So the local
  `feat/issue-228-harness-daemon` branch + its uncommitted WIP (`tools/ac_harness/daemon.py`,
  `.cursor/mcp.json`) is **STALE/superseded** — the working-tree `daemon.py` is an *older, pre-review*
  version (missing the merged length-check / `launch_generation` / double-read hardening), and
  `mcp.json` has a divergent local edit (context7/github servers removed). Recommend discarding the
  stale WIP and deleting the local branch once the operator confirms nothing there is wanted.
- **Local `main` is DIVERGED** from `origin/main` (1 ahead / 2 behind): local-only commit
  `dd5c613` *"untrack local-baked .cursor/hooks.json"* is **not** on `origin/main` (which still tracks
  the file). `git pull --ff-only` therefore fails (post-merge sync exit 10). **Human reconcile:** decide
  whether to drop `dd5c613` (`git reset --hard origin/main` on a clean `main`) or land it via a PR,
  then sync. This is why local `main` could not be auto-synced this session.

---

## Resume here (2026-06-16 — #188 rig verification OPEN; #190 CLOSED) [SUPERSEDED — #188 now closed above]

**Active:** [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188) — defensive wrap-reset code shipped in [#199](https://github.com/agorokh/ac-copilot-trainer/pull/199); **empirical rig question still open**. Runbook: [`03_Investigations/issue-188-wrap-skew-rig-verification`](../03_Investigations/issue-188-wrap-skew-rig-verification.md). Blockers from macOS: Tailscale ping to `pc` OK; SSH auth denied; sidecar down. Pending: ≥2-lap rig grep for `resetCounter` + wrap-skew frames (optional branch `feat/issue-188-rig-skew-probe` for `WRAP-SKEW-PROBE` logging).

**Closed:** [#190](https://github.com/agorokh/ac-copilot-trainer/issues/190) — Part E complete (see table below + vault PR [#226](https://github.com/agorokh/ac-copilot-trainer/pull/226)).

**Infra landed:** PR [#225](https://github.com/agorokh/ac-copilot-trainer/pull/225) (`b8f92ef`) — `.gitignore` for local-only noise (`.tmp/`, `backups/`, `tools/acc/`, `.claude/scheduled_tasks.lock`). Post-merge classification: no flags.

---

## Resume here (2026-06-16 — #190 CLOSED; EPIC #154 Part E complete)

**[#190](https://github.com/agorokh/ac-copilot-trainer/issues/190) CLOSED.** All Part E deliverables are merged on `main` and verified:

| Deliverable | PR(s) | Verification |
|-------------|-------|--------------|
| L1.5 WS sequence probe | [#191](https://github.com/agorokh/ac-copilot-trainer/pull/191) (`2f092da`) | 16+ unit tests; **live PASS** on real drive (2026-06-15) |
| carcsw Custom-AI mmap driver + PurePursuit + LapDriver | [#209](https://github.com/agorokh/ac-copilot-trainer/pull/209), [#221](https://github.com/agorokh/ac-copilot-trainer/pull/221), [#222](https://github.com/agorokh/ac-copilot-trainer/pull/222), [#223](https://github.com/agorokh/ac-copilot-trainer/pull/223) | 61+ pure tests; **live full lap + trainer coaching** on Magione (2026-06-16) — see [`autonomous-drive-live-verified-2026-06-16`](../03_Investigations/autonomous-drive-live-verified-2026-06-16.md) |
| Session replay for late-attaching L1.5 taps | [#201](https://github.com/agorokh/ac-copilot-trainer/pull/201) (`f6f2ed5`) | Lupa regression (`test_state_subscribe_session_sets_one_shot_replay_request`); in-sim smoke deferred to next rig pass |

**This session (autonomous-deliver):** `make ci-fast` on `main` @ `f6f2ed5` → **935 passed, 74 skipped**, coverage 81%+; focused #190 suites → **114 passed**. Rig SSH from macOS unavailable (no key); live gates already satisfied by prior AG_PC session.

**Next (EPIC #154):** Part F — in-session harness daemon (auto-login + unlocked desktop + AC launch without operator) for full L2 hands-off. Until then, the working loop is: operator launches AC once → agent runs `lap_driver` / `sequence_probe` autonomously. Latent follow-up: live smoke that mid-session `state.subscribe` to `session` triggers replay (low priority; off-sim covered).

---

## What was delivered (2026-06-16 — EPIC #154 Part E: carcsw driver PRODUCTIONIZED + merged)

**The autonomous in-sim driver is on `main`.** The work proven live (see
[`03_Investigations/autonomous-drive-live-verified-2026-06-16`](../03_Investigations/autonomous-drive-live-verified-2026-06-16.md))
shipped as four merged PRs (all refs #190):

- **[#209](https://github.com/agorokh/ac-copilot-trainer/pull/209) (`b573cc9`)** — `tools/ac_harness/custom_ai.py` (CSP Custom-AI mmap actuator/reader) + `ai_line.py` (fast_lane parser + `PurePursuit`) + `lap_driver.py` (`LapDriver`: pit-out OUT-phase, gear mgmt, position-return lap detection, stuck→teleport recovery). 61 pure tests. Reviewed by CodeRabbit + Cursor Bugbot + a **12-agent adversarial verification workflow**; review fixes folded in (car_index guard, `time.monotonic`, stuck-recovery throttle threshold, dead-code, stronger corner/gear tests).
- **[#221](https://github.com/agorokh/ac-copilot-trainer/pull/221) (`402e326`)** — `spline_position` offset 448→**240** (live byte-probed; 448 was garbage), handbrake@16 documented as unverified (write-0.0-only), `PurePursuit`/`load_ai_line`/`ControlOutput` exported at package level.
- **[#222](https://github.com/agorokh/ac-copilot-trainer/pull/222) (`31ffd4a`)** — ai_line cyclic closed-loop wrap coverage (the gap the verification workflow flagged + spun off as a task).
- **[#223](https://github.com/agorokh/ac-copilot-trainer/pull/223)** — `.gitattributes`: force `scripts/hook_*.py` to LF (the governed shims are byte-identity-gated against an LF canonical; Windows CRLF checkout made `test_public_governance_conformance` fail locally — the "drift" was a CRLF artifact, **not** a tampered shim; the pin `d28fab` is correct).

**Gear answer (operator Q):** the overnight 1st-gear-only was the conservative ~50 km/h cap holding rpm ~3,900, below the ~7,800-rpm (≈80 km/h) upshift point — demoed live (1st→2nd at rpm 7,763). Not a bug.

**Rig restored:** Magione `surfaces.ini` reverted to stock (byte-identical to `surfaces.ini.bak-precustomai`); the offline-hash edit is gone. `new_behaviour.ini [CUSTOM_AI] ENABLED=1` left (harmless dormant toggle).

**Tracked follow-up (latent, low priority):** clamp `PurePursuit._curvature_ahead` window to line length — only bites on closed lines shorter than the lookahead (~40 m); real km-scale `fast_lane` tracks never produce one.

## What was delivered (2026-06-16 - #114 / PR #206 setup experiment tracking)

**[#114](https://github.com/agorokh/ac-copilot-trainer/issues/114) CLOSED / PR [#206](https://github.com/agorokh/ac-copilot-trainer/pull/206) MERGED** `2026-06-16T11:10:51Z` as squash [`7d87f96`](https://github.com/agorokh/ac-copilot-trainer/commit/7d87f96ea6179d8d39f3610db49678c25752d632). The trainer now has a setup experiment layer: lap archives can be rebuilt into a JSONL experiment store, compared as old-vs-new setup A/B evidence, and queried for deterministic expected-improvement setup suggestions.

**Shipped behavior:** `tools.ai_sidecar.setup_optimizer` extracts schema-v1 lap archives into `journal/setup_experiments/experiments.jsonl`, records live lap archives idempotently, deduplicates rebuilds by `experiment_id`, rejects corrupt stores, and refuses missing lap directories before rewriting any store. The sidecar exposes CLI and v1 websocket surfaces for `setup.experiment.store`, `setup.experiment.record`, `setup.compare`, and `setup.suggest`; blocking file/stat work is offloaded from the async websocket loop and handler failures return structured `{ok:false,error}` frames. Lua registers the canonical store path after the v1 handshake, records newly archived laps, retries failed store registration from `tick()` with backoff, and does not send path-bearing setup frames to non-loopback websocket URLs.

**Verification:** local focused suites passed (`44 passed` across `tests/test_ai_sidecar_external.py`, `tests/test_setup_optimizer.py`, and `tests/test_ws_bridge_hello_handshake.py`; final Lua handshake file `11 passed`). Final local parity after all review hardening passed with `make ci-fast PYTHON=.venv/bin/python` (`935 passed, 74 skipped`, coverage 81.21%; ruff, bandit, docs policy, CSP API/UI checks complete). GitHub checks on PR #206 were green on head `07be4cc` (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery/Gemini quota-limited as comments only). GraphQL `reviewThreads` returned no unresolved non-outdated threads before merge. Post-merge classification: no migration/env/deps/script/workflow flags.

**What remains:** no #114 follow-up is required. This was verified off-sim through CLI, websocket, and Lupa harnesses from macOS; the next Windows/AC rig pass should smoke that real lap archives advance the experiment store and `setup.suggest` returns only after rows exist. Active focus remains #190 / carcsw productionization.

## What was delivered (2026-06-16 - #115 / PR #204 lap telemetry export)

**[#115](https://github.com/agorokh/ac-copilot-trainer/issues/115) CLOSED / PR [#204](https://github.com/agorokh/ac-copilot-trainer/pull/204) MERGED** `2026-06-16T09:44:11Z` as squash [`dc93b1b`](https://github.com/agorokh/ac-copilot-trainer/commit/dc93b1be5b78ea16067cdfef9ab42a77bf058d62). Archived lap JSON can now be exported with `python -m tools.lap_archive_export`, either as a stable generic CSV or as a deterministic MoTeC-shaped CSV bridge file.

**Shipped behavior:** the exporter streams generic CSV rows from one or more archive files/directories, skips invalid laps by default, supports `--include-invalid`, and writes stable columns covering lap identity plus sample telemetry. `--format motec-csv` emits quoted MoTeC-style metadata/channel/unit/data rows with beacon markers, rejects mixed session/car/track/layout inputs, preserves recorded `lap_ms` where present, and falls back to trace timing when needed. Output writes are constrained to relative paths under the current working directory, reject absolute or escaping paths, and replace the final file through a unique temporary sibling. Usage and MoTeC import caveats live in [`10_Development/13_Lap_Archive_Export`](../../../10_Development/13_Lap_Archive_Export.md).

**Verification:** focused exporter tests passed after final hardening (`12 passed` in `tests/test_lap_archive_export.py`). Full local parity passed on the merged branch with `make ci-fast PYTHON=.venv/bin/python` (`930 passed, 74 skipped`, coverage 81.56%; ruff, bandit, docs policy, root allowlist warnings, CSP API/UI checks all completed). Observed CLI proof produced a 4-row generic CSV and a 3-row MoTeC CSV under `.scratch/issue-115/`; absolute output and `..` escape attempts were rejected without creating files; mixed-session MoTeC input was rejected without a partial output. GitHub checks for PR #204 were green (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery skipped/rate-limited). GraphQL `reviewThreads` audit found no current unresolved blocking threads before merge. Post-merge classification: no migration/env/deps/script/workflow flags.

**What remains:** no #115 follow-up is required. This was an off-sim archive/export utility; no live Windows AC/CSP rig verification is required for the shipped behavior. Active focus remains #190 / carcsw productionization.

## What was delivered (2026-06-16 — #156 / PR #202 optional MCP smoke isolation)

**[#156](https://github.com/agorokh/ac-copilot-trainer/issues/156) CLOSED / PR [#202](https://github.com/agorokh/ac-copilot-trainer/pull/202) MERGED** `2026-06-16T09:38:49Z` as squash [`d71bca3`](https://github.com/agorokh/ac-copilot-trainer/commit/d71bca31f3db221bfc9c78273f84477c6bf372a5). The full local suite without `[knowledge]` no longer fails the optional MCP server smoke because hook/manifest tests no longer leak `scripts/` onto `sys.path` during collection.

**Shipped behavior:** hook and manifest tests now import repo scripts through `tools.testing.script_imports.load_script_module` instead of `sys.path.insert(.../scripts)`. The helper is path-aware, fails closed on module-name/path collisions, and supports same-directory sibling `.py` imports through a temporary meta-path finder without leaving `scripts/` globally visible or exposing `scripts/mcp/` as a top-level namespace package. The current `main` FastMCP availability guard for `tests/test_repo_knowledge/test_mcp_server_import.py` was preserved during rebase.

**Verification:** no-knowledge regression group passed (`70 passed, 3 skipped` across `tests/test_script_imports.py`, hook/manifest tests, and `tests/test_repo_knowledge/`); knowledge-enabled smoke passed with `/Users/arseny_gorokh/Projects/ac-copilot-trainer/.venv/bin/python -m pytest tests/test_repo_knowledge/test_mcp_server_import.py -q` (`1 passed`); final-base local `make ci-fast PYTHON=.scratch/venv-issue156/bin/python` passed (`928 passed, 75 skipped`, coverage 81.16%). GitHub checks on PR #202 were green on the final merged head (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery skipped/rate-limited). GraphQL `reviewThreads` returned no active threads. Post-merge classification: no migration/env/deps/script/workflow flags.

**What remains:** no #156 follow-up is required. Active focus remains #190 / carcsw productionization.

## What was delivered (2026-06-16 — #116 / PR #205 generated reference-lap prototype)

**[#116](https://github.com/agorokh/ac-copilot-trainer/issues/116) CLOSED / PR [#205](https://github.com/agorokh/ac-copilot-trainer/pull/205) MERGED** `2026-06-16T09:34:53Z` as squash [`6d0ddc8`](https://github.com/agorokh/ac-copilot-trainer/commit/6d0ddc845570ca973b9a2d88cce20dda4def4a30). The repo now has a stdlib-only generated reference-lap adapter, `python -m tools.ac_harness.reference_lap`, that emits lap archive schema v1 records with `source="imported"` / `import_format="generated_reference_v1"` and can also emit a trainer-state persistence fragment for `bestReferenceLapMs`, `bestLapTrace`, `bestBrakePoints`, and `bestCornerFeatures` while preserving the driver's `bestLapMs`.

**Decision captured:** [`01_Decisions/rl-reference-lap-generation`](../01_Decisions/rl-reference-lap-generation.md) chooses deterministic/off-sim generated references now and defers RL runtime dependencies (TUMFTM/CommonRoad/Gym/SB3) until there is a proven importer path and real acceptance need. Future solver output should enter through the same object-frame list passed to `build_archive_record`, not leak solver schemas into the trainer.

**Review hardening shipped before merge:** generated brake windows include unreleased braking tails; the bridge no longer overwrites driver PBs; the validator requires `corners`, rejects `lap.lap_ms` / final-trace `eMs` mismatches, and keeps `trailBrakeRatio` aligned with live `corner_analysis` (`avgBrake / maxBrake`).

**Verification:** local focused `tests/test_reference_lap.py` passed (`10 passed`); full merged-branch local `make ci-fast PYTHON=.venv/bin/python` passed (`929 passed, 75 skipped`, coverage 81.32%); GitHub checks on PR #205 were green on the merged head (`build`, `Canonical docs exist`, `conformance`, CodeRabbit, Cursor Bugbot; Sourcery skipped). GraphQL `reviewThreads` showed every thread resolved before merge. Generated artifact smoke emitted both archive JSON and trainer-state JSON under `.scratch/`. Post-merge classification: no migration/env/deps/script/workflow flags.

**Runtime caveat:** this is intentionally off-sim and does not prove an RL agent or external optimizer can produce a faster lap in AC. The next real integration step is an importer/activation path that consumes generated archive records the same way PR #207 consumes MoTeC imports. Active focus remains #190 / carcsw productionization.

## What was delivered (2026-06-16 — #188 / PR #199 defensive wrap-shaped teleport reset)

**[#199](https://github.com/agorokh/ac-copilot-trainer/pull/199) MERGED** `2026-06-16T09:31:34Z` as squash [`f03dea6`](https://github.com/agorokh/ac-copilot-trainer/commit/f03dea6c094fefee947d52b7a7b38b7172833d2d). This is the defensive code branch for [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188): CSP builds lacking `car.resetCounter` now defer wrap-shaped same-lap spline rewinds by one frame instead of treating them as definitely-normal lap wraps.

**Shipped behavior:** `delta.rollingResetDecision()` owns the end-of-update rolling reset decision. It resets immediately on `resetCounter`/teleport, lap rollback, or non-wrap same-lap spline rewind; it defers a wrap-shaped same-lap jump (`prevSpline` near 1.0 -> `spline` near 0.0), clears it if `lapCount` catches up on the next frame, and otherwise resets the abandoned stint. Qodo's edge-case note was addressed too: if `lapCount` is non-numeric/unavailable while pending, the decision remains pending rather than forcing a reset. The trainer stores this as `state.pendingWrapResetLapCount` and clears it on runtime/stint resets.

**Verification:** local final-base `PYTHON=.venv/bin/python make ci-fast` passed (`926 passed, 75 skipped`, 81.12% coverage); targeted `tests/test_delta.py tests/test_csp_helpers.py tests/test_repo_knowledge/test_mcp_server_import.py` passed (`22 passed, 1 skipped`); GitHub build/conformance/docs/CodeRabbit/Cursor Bugbot all green; GraphQL `reviewThreads` returned zero nodes; `post_merge_classify.py --pr 199` reported no post-merge flags.

**Honest residual:** this macOS checkout did not have a live AC/CSP rig, so the issue's empirical rig question is still unproven: whether the rig's CSP exposes `car.resetCounter`, and whether non-teleport lap wraps ever show `splinePosition` high->low with unchanged `lapCount`. Leave [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188) open until a rig pass confirms that reality. If `resetCounter` is present, the issue can likely close as defensive hardening shipped. If `lapCount` can lag by more than one frame at s/f, extend the deferral window with live evidence.

**2026-06-16 autonomous-deliver pass:** Tailscale reachability to `pc` (`100.75.251.87`) confirmed; SSH auth blocked from macOS; sidecar `:8765` down. Runbook: [`03_Investigations/issue-188-wrap-skew-rig-verification`](../03_Investigations/issue-188-wrap-skew-rig-verification.md). Issue comment: [#188#issuecomment-4723875486](https://github.com/agorokh/ac-copilot-trainer/issues/188#issuecomment-4723875486). Pending: ≥2-lap rig grep for `resetCounter` + wrap-skew frames.

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
   py -m tools.ai_sidecar --external-bind 0.0.0.0 --port 8765
   ```
   Run that from a shell with `AC_COPILOT_SIDECAR_TOKEN` already set. The rig
   hotspot is 2.4 GHz forced; keep the home Wi-Fi profile manual so it does not
   reclaim the single-radio Intel 7260 while the hotspot is hosting. Full
   diagnosis + recovery commands: [`wifi-hotspot-single-radio-2026-04-26`](../03_Investigations/wifi-hotspot-single-radio-2026-04-26.md).

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
4. **Home mesh Wi-Fi** segregates per-AP subnets; TCP dropped cross-AP. Hotspot is the dev path.
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
