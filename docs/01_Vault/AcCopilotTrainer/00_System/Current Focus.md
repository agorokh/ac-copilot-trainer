---

## type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-07-03T04:35:22Z
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/pr-444-atelier-main-dashboard-2026-07-01.md
  - AcCopilotTrainer/01_Decisions/voice-intensity-register-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-394-voice-reliability-2026-06-30.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/03_Investigations/stanley-steering-live-verified-2026-06-19.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - AcCopilotTrainer/03_Investigations/_index.md

# Current focus

**Repo:** ac-copilot-trainer.

**Active focus (2026-07-03):** PR
[#465](https://github.com/agorokh/ac-copilot-trainer/pull/465) for
[#461](https://github.com/agorokh/ac-copilot-trainer/issues/461) is review-converged at
`3568cd4` but not merged in this session. It replaces the forbidden install-tree setup+drive compose
path with Content Manager launch plus compliant AC-Documents `race.ini` re-bake, hardens setup
snapshot/no-setup handling, and passed CI + resolve-gate + GraphQL/Qodo/Copilot review gates. The
self-hosted reviewer did not post a current-SHA review after the final cooldown, so its gate is
vacuously satisfied per `resolve-pr` anti-hang rules. Next action: merge PR #465 if desired, then run
post-merge sync/SAVE.

**Delivered (2026-07-02):** PR [#460](https://github.com/agorokh/ac-copilot-trainer/pull/460)
merged [#459](https://github.com/agorokh/ac-copilot-trainer/issues/459) — autonomous harness as a
product + setup verify. Detail: [[issue-459-harness-product-2026-07-02]].

**Delivered (2026-07-02):** PR [#452](https://github.com/agorokh/ac-copilot-trainer/pull/452)
**MERGED** at [`ff65522`](https://github.com/agorokh/ac-copilot-trainer/commit/ff6552271107884222dd20c6b3420921e71318f9) -
telemetry-learned shift points for [#442](https://github.com/agorokh/ac-copilot-trainer/issues/442).
Lap/reference traces now carry `rpm`; `shift_profile.lua` learns per-gear upshift RPMs and
corner-exit gear provenance from the active reference; SHIFT UP coaching and the Racing Atelier RPM
zones use learned targets before heuristic limiter fractions. Review hardening covered old archives
without `rpm`, neutral/manual shift frames, skipped downsampled gear jumps, missing limiter readings,
and corner-exit sampling before the following straight. GitHub checks green, resolve gate clean, Qodo
`Bugs (0)`, Gemini current-SHA no feedback. #442 is **CLOSED**.

**Delivered (2026-07-02):** PR [#455](https://github.com/agorokh/ac-copilot-trainer/pull/455)
**MERGED** at [`5c582f7`](https://github.com/agorokh/ac-copilot-trainer/commit/5c582f7f7be166c8b10901d1116f268e7e214fef) -
post-merge review hardening for [#408](https://github.com/agorokh/ac-copilot-trainer/issues/408).
`reference_source=imported` now matches only generic imported references, not `pro` / `tt` /
`generated`, and partial Track Titan debug archives are excluded from comparison fallback candidates.
GitHub build/conformance/docs green; Qodo follow-up reported no material issues.

**Delivered (2026-07-02):** PR [#451](https://github.com/agorokh/ac-copilot-trainer/pull/451)
**MERGED** at
[`81be1f3`](https://github.com/agorokh/ac-copilot-trainer/commit/81be1f33f52dcd3efe08c6bcc0582e1307a3a62c) -
voice-bank timing and stale-bank invalidation for
[#381](https://github.com/agorokh/ac-copilot-trainer/issues/381). Kokoro hot-register speeds and the
Piper alert/urgent/critical ladder now keep neural act cues inside the 450 ms brake-alarm budget;
`INTENSITY_CHAIN_VERSION=3` forces old `prosody2+intensity2` banks to fail validation; user
`AC_COPILOT_VOICE_BANK` points at
`C:\Users\arsen\Projects\ac-copilot-trainer\.scratch\coach-bank-kokoro-fenrir-v3-intensity3-20260702`.
Runtime proof: timing report urgent 379.6 ms, critical 361.4 ms,
`brake_alarm_within_450ms=true`; sidecar `/health.voice.enabled=true` with `rtmixer` on the USB
Sound Device. **#381 remains OPEN** only for the human-gated at-wheel A/B listening confirmation.

**Delivered (2026-07-02):** PR [#453](https://github.com/agorokh/ac-copilot-trainer/pull/453)
**MERGED** at [`97a963f`](https://github.com/agorokh/ac-copilot-trainer/commit/97a963f) - session
review browser/report products for [#404](https://github.com/agorokh/ac-copilot-trainer/issues/404)
and reference selection for [#408](https://github.com/agorokh/ac-copilot-trainer/issues/408). #404
is **CLOSED** (Part A in #423; Parts B-D in #453), and #408 is **CLOSED** (Parts A-B in #418, Part C
through #353/#428, Part D in #453). Session Review now writes schema-v2 Markdown/JSON/HTML with
Debrief, Next Session, History, Lap-Time Trend, Corner Trends, and Lap Compare; CLI/sidecar reference
selection supports `auto` / `your-best` / `pro` / `tt` / `generated` / `imported` / `none`; external
broadcasts expose basenames only. CI green, review threads resolved, post-merge classification clean.

**Delivered (2026-07-02):** Racing Atelier **runtime adoption complete on all three surfaces**
([#432](https://github.com/agorokh/ac-copilot-trainer/issues/432) Parts A2+B; #86 conformance fix):
PRs [#444](https://github.com/agorokh/ac-copilot-trainer/pull/444) (`82ced33`, in-game
main-dashboard card + COACHING tile — operator-directed evolution: 62px vitals, RPM shift zones,
SHIFT UP verb; live-verified in-sim), [#445](https://github.com/agorokh/ac-copilot-trainer/pull/445)
(`6f04755`, launcher photo-parity, real-pixel verified) and
[#446](https://github.com/agorokh/ac-copilot-trainer/pull/446) (`91ca72a`, rig-screen badge/delta
fixes the operator found on the glass — flashed to the device). Detail:
[[pr-444-atelier-main-dashboard-2026-07-01]]. **Operator-pending:** rig-screen photo vs
`esp32_rig.png`; in-sim BRAKE-state glance. **Open flake:** autonomous driver stalls ~500m from
pit start (both drivers) — file vs the harness next session. Follow-up
[#442](https://github.com/agorokh/ac-copilot-trainer/issues/442) is now delivered by PR #452.

**Delivered (2026-07-01):** PR [#429](https://github.com/agorokh/ac-copilot-trainer/pull/429)
**MERGED** ([`047309e`](https://github.com/agorokh/ac-copilot-trainer/commit/047309ef450c56c6e95a886cca86724e277a64e5))
implementing [#381](https://github.com/agorokh/ac-copilot-trainer/issues/381) four-tier expressive
voice intensity (`calm`/`alert`/`urgent`/`critical`, manifest v3, original race-engineer persona
signature). The register ladder was hoisted into the shared `tools/ai_sidecar/registers.py` so the
observer and voice vocabulary stop re-declaring it. CI green; 10 bot threads resolved.
**Operator-pending (not a code deliverable):** the on-rig A/B listening confirmation that
high-importance cues sound more urgent than low ones — audible-intensity is operator-confirmed per
the honesty invariant, never asserted by the pipeline. The #429 follow-up
[#438](https://github.com/agorokh/ac-copilot-trainer/issues/438) is now **CLOSED** — PR
[#441](https://github.com/agorokh/ac-copilot-trainer/pull/441) **MERGED**
([`65e9d42`](https://github.com/agorokh/ac-copilot-trainer/commit/65e9d42c4de469d20483cbd6da7b29341b20465d),
2026-07-02): `Manifest.validate()` enforces the persona/prosody/intensity `voice_signature` suffix,
`from_bank()` disables on drift, and `bake_bank()` fails fast on a suffix-less backend. Detail:
[[pr-441-voice-signature-gate-2026-07-01]].

**Active focus (2026-06-17):** EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) — **Part F harness daemon shipped** ([#228](https://github.com/agorokh/ac-copilot-trainer/issues/228)/PR #229) and its on-rig launch gap fixed ([#232](https://github.com/agorokh/ac-copilot-trainer/issues/232) **CLOSED** / PR [#233](https://github.com/agorokh/ac-copilot-trainer/pull/233) **MERGED** `c556dfe`): the daemon now launches AC **de-elevated via Content Manager** (`--launch-mode cm`), live-verified hands-off on `AG_PC`. The autonomous self-test is now **one command** ([#235](https://github.com/agorokh/ac-copilot-trainer/issues/235) **CLOSED** / PR [#236](https://github.com/agorokh/ac-copilot-trainer/pull/236) **MERGED** `d051096`): `python -m tools.ac_harness.self_test` drives the daemon hands-off and asserts the live coaching pipeline — **LIVE PASS** (`coaching.snapshot=335, tire_temps=168, connection=34`, no human at the wheel). The vision-oracle **"eyes"** also landed ([#238](https://github.com/agorokh/ac-copilot-trainer/issues/238) **CLOSED** / PR [#239](https://github.com/agorokh/ac-copilot-trainer/pull/239) **MERGED** `3e677c7`): `tools.ac_harness.hud_capture` (stdlib ctypes GDI, no new dep) captures the live AC HUD hands-off with a render-liveness check — **LIVE-VERIFIED** (in-cockpit at Spa, HUD text legible). [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188)/[#190](https://github.com/agorokh/ac-copilot-trainer/issues/190) **CLOSED**. **The autonomous self-test now has launch + pipeline-assert + eyes, all hands-off + live-verified.**

**Active focus (2026-06-19) — HANDOFF, see [#244](https://github.com/agorokh/ac-copilot-trainer/issues/244):** Part G **racing driver** **MERGED** ([#241](https://github.com/agorokh/ac-copilot-trainer/issues/241) / PR [#242](https://github.com/agorokh/ac-copilot-trainer/pull/242) `372156a`): follows `fast_lane.ai`'s embedded speed profile with braking points/trail braking; **gear bug fixed** (was stuck in 1st — limiter below shift point) → now shifts 1→4, **146 km/h** (was 52). `tools/ac_harness/racing_telemetry.py` records human laps. **The wall is STEERING** (pure-pursuit cuts apexes → corners crawl, lap INVALID → no `lap`/`delta` telemetry). **Next:** record 5–10 human GT3 laps → build a path-tracking steering controller from real corner speeds/braking points. Full state: [`racing-driver-and-controller-2026-06-17`](../03_Investigations/racing-driver-and-controller-2026-06-17.md). Parallel hot path: Stream A rig screen EPIC [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) after PR [#365](https://github.com/agorokh/ac-copilot-trainer/pull/365) is final polish/proof: font conversion outputs, persistence/backpressure/debug-screen polish if still desired, and final on-device smoke.

**Active focus update (2026-06-19 LATER) — #244 / PR [#248](https://github.com/agorokh/ac-copilot-trainer/pull/248) MERGED + LIVE-VERIFIED on the rig:**
Ran `/autonomous-deliver 244` **on `AG_PC` itself** (prior Mac→rig blocker moot). The merged Stanley
controller from the human profile drove Magione via carcsw, no human → **3 AC VALID laps** (best
**106.8 s**, max **207.6 km/h**, gears 1–6, 0 stuck), and the sidecar tap showed **`delta=2935`** live
delta-to-reference + `coaching.snapshot=3797` — **the `lap`/`delta` telemetry wall is broken**. The
trainer captured the agent's lap as its coaching reference (lap archives written). **Residual:** best
clean lap is ~85% of the human's relaxed pace (106.8 s vs 90.7 s / 83.5 vs 98.7 km/h); the literal
`avg ≳100 km/h` bar is unmet and an aggressive-throttle tuning pass REGRESSED (TC-off wheelspin), so the
merged defaults are near-optimal. The last ~15% is separable controller-sophistication on
`racing_driver.py` → stays as remaining Part-G scope on #244 (no new overlapping issue). **#244 + #154
stay OPEN** for the pace bar; operator decides whether the wall-break + telemetry milestone closes
Part-G-core. Full write-up: [`stanley-steering-live-verified-2026-06-19`](../03_Investigations/stanley-steering-live-verified-2026-06-19.md).

**Runtime hotfix (2026-06-19) — #246 / PR #249 MERGED + CLOSED (live-verified):**
PR [#249](https://github.com/agorokh/ac-copilot-trainer/pull/249) (`4e2a310`) moved lap-archive writes
off the lap-complete/SF frame. **[#246](https://github.com/agorokh/ac-copilot-trainer/issues/246)
CLOSED** on the rig this session: timestamped tap of the script-frame `coaching.snapshot` stream
showed max gap **255 ms** (at S/F: 217 ms / 255 ms, not ~2 s); archives still land off-frame, laps
`valid=True`. The ~2 s render freeze is gone. Evidence:
[#246#issuecomment-4754133099](https://github.com/agorokh/ac-copilot-trainer/issues/246#issuecomment-4754133099).

**Active focus update (2026-06-27) — #324 / PR [#325](https://github.com/agorokh/ac-copilot-trainer/pull/325) MERGED (`0fb721f`), generality + flat-out LIVE-VERIFIED:**
Operator pushback ("the composed run wasn't racing — stuck in 1st gear") drove the fix. New
`tools/ac_harness/auto_drive.py` is the genuinely-composed one-command L2 loop (launch → carcsw
hijack w/ retry → autonomous drive in a thread → WS producer assert), **parametrized by
car/track/preset**, with **sim-death anti-false-green** (Car0 packet stagnation). Three driver modes:
`cruise` (LapDriver), `racing` (AI-line pace), **`ggv`** (flat-out friction-circle min-time).
**Generality proven beyond Magione/Porsche**: Imola + Audi R8 LMS (full lap + reference coaching),
Mugello + Corvette C7R, and **Spa + BMW Z4 GT3 flat-out top gear 6 / 211 km/h** with reference
coaching (`T2 · target entry 241 km/h`). Load-bearing fix: the generic GGV's `k_aero_lat` MUST be 0
(an aero-lateral term spins the GT3 out — a multi-agent verification workflow caught it against the
#259 plant fit). Honest residual: flat-out on Stanley still loses a few corners; the clean ~83 s line
needs curvature-ff + per-car `ff_c1/c2` calibration (#244). #154 stays OPEN (children #277/#278/#305 +
Part-G KPI residual). Full state:
[`autonomous-drive-multitrack-generality-2026-06-27`](../03_Investigations/autonomous-drive-multitrack-generality-2026-06-27.md).

**Infra (2026-05-20):** PR [#111](https://github.com/agorokh/ac-copilot-trainer/pull/111) closed the [#108](https://github.com/agorokh/ac-copilot-trainer/issues/108) agent-surface campaign (closeout doc only; five agent SHA alignments deferred). PR [#109](https://github.com/agorokh/ac-copilot-trainer/pull/109) memory-contract cursor rule fix remains on `main`.

## Stream A — Rig screen Phase-2 UI (PR #91 merged — Parts A–D on `main`)

**Infra (2026-05-16):** PR [#96](https://github.com/agorokh/ac-copilot-trainer/pull/96) landed template-2026.05 deterministic Claude hooks on `main` (`5d3019e`) — does not change device/UI scope; removes LLM-bearing Stop/PreToolUse hooks that caused session stalls.

**Status:** PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** `2026-04-29T17:02:22Z` as squash commit `[35d770c](https://github.com/agorokh/ac-copilot-trainer/commit/35d770c7e51da021133488809d4c5dbd254e0195)` on `main` (LVGL 8.3 portrait UI, launcher, AC Copilot mirror + `coaching.snapshot`, Pocket Technician + `setup.list` / `setup.load`, trainer Lua/sidecar protocol, lap-archive path alignment, Windows `ar` batching). Device bring-up catalogue: `[screen-end-to-end-bringup-2026-04-26](../03_Investigations/screen-end-to-end-bringup-2026-04-26.md)`.

PR #83 (WS + Lua bridge) **MERGED 2026-04-22** at `caa8a9ad` — still the foundation under Stream A.

**Outstanding housekeeping:** Issue [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81) may still be OPEN from before PR #83 — close with `gh issue close 81` when confirmed duplicate.

**Next (EPIC #86 remainder after PR #365):**

- **Delivered by PR #365** — Game Point launcher, Setup Exchange screen/proxy/install path, Pocket Technician spinner controls, and environment-only sidecar token/voice routing.
- **Still open on #86** — Part A4 `lv_font_conv` outputs; SPIFFS/persistence/backpressure/debug-screen polish if still desired; final device smoke artifact covering launcher → AC Copilot live hints → Pocket Technician setup load → Setup Exchange browse/download/install.

**Live-dev:** Hotspot + sidecar path per `[glossary/rig-network.md](../glossary/rig-network.md)`. Firmware: `python -m platformio run -e jc3248w535` under `firmware/screen/` (CI does not build firmware).

## Stream B — CSP-apps integration (Pocket Technician, Setup Exchange)

Integration ADR landed 2026-04-21 as `[screen-and-csp-apps-integration.md](../01_Decisions/screen-and-csp-apps-integration.md)`. Verdict: **replicate, don't bridge.** Our trainer Lua VM calls `ac.getSetupSpinners()` + `ac.setSetupSpinnerValue()` directly (same APIs PT uses); sidecar watches `UserSetups/<carID>/` for SX-dropped files. Both PT and SX stay installed; we coexist, not compete.

Surface map of both apps lives in `[csp-app-pocket-tech-setup-exchange-2026-04-21](../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md)`.

**Next:** `setup.list` / `setup.load` shipped with PR #91; spinner controls and Setup Exchange screen/proxy/install shipped with PR #365. Remaining B-stream work is optional `setup_control.lua` / UI polish if still desired, plus the #86 final on-device smoke artifact.

## Stream C — Physical rig integration EPIC #59

**New discovery**: `[10_Rig/physical-rig-integration-epic-59.md](../10_Rig/physical-rig-integration-epic-59.md)` captures the full scope — Arduino UNO (fan + OLED + seat vibration motors + pedal haptics), ESP32 touch dashboard (**Stream A is this**), Dayton BST-1 under-seat shaker (**done as Phase 1R**), salvaged Xbox controller motors for pedal haptics, full pin map.

**Protocol update (2026-06-16):** PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) delivered the sidecar `telemetry_tick` / `haptic_event` route for physical peripherals, including legacy rig-screen classification and haptics-only fan-out. Downstream hardware firmware can now consume a stable sidecar contract; active dev focus still stays on #190 / carcsw productionization.

Stream A is the first slice of this epic. Phase 3b (side bolster motors) and Phase 4 (pedal haptics) land after Phase 2 screen is fully wired.

## Stream D — PR #75 in-game smoke test (carried-over)

Now **MERGED 2026-04-14**. Ollama corner coaching pipeline (`corner_query` / `corner_advice`, sub-550 ms) is live. See `[pr-75-ollama-corner-coaching-protocol](../03_Investigations/pr-75-ollama-corner-coaching-protocol.md)` for the protocol the rig screen can subscribe to.

## Priority call

Stream A (rig screen Phase-2 LVGL + Figma UI + final on-device proof) is the hot path — the Game Point/Pocket Technician/Setup Exchange code path is now merged, so the next tangible win is a clean physical-rig smoke artifact across launcher → live hints → setup load → Setup Exchange install. Stream B integration is folded into Stream A's protocol work.

## Recently landed (reverse chronological)

- **2026-07-01 UTC / 2026-06-30 PT** - PR [#428](https://github.com/agorokh/ac-copilot-trainer/pull/428)
  **MERGED** at `9685155` - **Track Titan harness curriculum** ([#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)
  **CLOSED**): adds `track_titan_harness_curriculum_v1`, `tools.tt_ingest curriculum`, retained
  coaching/last-session pairing, self-consistent in-lake `curriculum_lapN.json` output guards, derived
  retention cascade planning, and docs for the M-TT3 artifact. Classification: no migration/env/deps/script/workflow flags.
- **2026-07-01 UTC / 2026-06-30 PT** - PR [#433](https://github.com/agorokh/ac-copilot-trainer/pull/433)
  **MERGED** at `cd17dfe` - **setup review hardening** ([#407](https://github.com/agorokh/ac-copilot-trainer/issues/407)
  follow-up): setup archive/store ingestion now rejects malformed UTF-8 without replacement
  decoding, JSONL experiment-store reads stay streaming, closed-loop guards ignore later missing
  unrelated params instead of reporting false confounds, and `.secrets.baseline` hash validation
  accepts uppercase SHA-1 metadata. Classification: `scripts/` changed for policy hash regex only;
  no migration/env/deps/workflow action required.
- **2026-07-01 UTC / 2026-06-30 PT** - PR [#417](https://github.com/agorokh/ac-copilot-trainer/pull/417)
  **MERGED** at `a4ae501` - **setup intelligence** ([#407](https://github.com/agorokh/ac-copilot-trainer/issues/407)
  **CLOSED**): adds complaint-language setup advice, setup diffs, loopback-only closed-loop
  suggestions, schema-backed decoded display/cautions, packaged schema assets, and Windows-safe
  policy secret scanning. Classification: `scripts/` and `Makefile` changed for policy/secret scan
  plumbing; no migration/env/deps/workflow action required.
- **2026-07-01 UTC / 2026-06-30 PT** - PR [#422](https://github.com/agorokh/ac-copilot-trainer/pull/422)
  **MERGED** at `28048c1` - **coaching diagnosis depth** ([#405](https://github.com/agorokh/ac-copilot-trainer/issues/405)
  **CLOSED**): Coach v2 now spatially matches current/reference corners by apex spline, reuses one
  corner/signature/reference-match pass across reports and protocol follow-up, and emits richer
  `steering`, `brake_shape`, `gear`, `exit_road_usage`, and `consistency` diagnostics. History
  archives are bounded, same-combo scoped, deduped by metadata plus streaming trace digest, and routed
  through `historyArchivePaths`. Classification: no migration/env/deps/script/workflow flags.
- **2026-06-30** - PR [#419](https://github.com/agorokh/ac-copilot-trainer/pull/419)
  **MERGED** at `14f6257` - **driver progression profile** ([#403](https://github.com/agorokh/ac-copilot-trainer/issues/403)
  **CLOSED**): Coach v2 now derives cue density and curriculum from the persistent driver profile,
  scoped to the active car/track/layout. Added `tools.ai_sidecar.driver_progression`, hardened
  profile rebuild/idempotency/corner sample merging, documented `AC_COPILOT_DRIVER_PROFILE`, and
  kept runtime profile writes constrained to approved `journal/driver/profile.json` roots.
  Classification: `.env.example` changed for the documented profile override; no migration/deps/workflow flags.
- **2026-06-30** - PR [#418](https://github.com/agorokh/ac-copilot-trainer/pull/418)
  **MERGED** at `17aa36b` - **sector benchmarks and SuperLap targets** ([#408](https://github.com/agorokh/ac-copilot-trainer/issues/408)
  epic remains **OPEN**): post-lap sector/micro-sector deltas, complete-only stitched SuperLap
  targets, protocol/HUD surfacing, valid/same car-track-layout benchmark scoping, explicit lap-clock
  boundary handling, and 1-based benchmark indices. Classification: no migration/env/deps/script/workflow
  flags. Remaining #408 work: TT M-TT3 via [#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)
  and fuller reference-library management.
- **2026-06-30** - PR [#415](https://github.com/agorokh/ac-copilot-trainer/pull/415)
  **MERGED** at `c407d46` - **telemetry data platform** ([#402](https://github.com/agorokh/ac-copilot-trainer/issues/402)
  **CLOSED**): DuckDB `sessions` / `stints` rollups, compacted driver profile ledger, dry-run-first
  lap/TT retention, stdout CSV streaming, and telemetry data-platform docs. Review hardening made
  retention fail closed on invalid profiles, preserve compacted bests through partial rebuilds,
  reject negative caps, invalidate TT derived indexes after TT deletions, and normalize Windows
  drive-letter paths in the Git Bash agentic-memory wrapper. Classification: `scripts/` changed due
  wrapper hardening; no migration/env/deps/workflow action required.
- **2026-06-30** - PR [#416](https://github.com/agorokh/ac-copilot-trainer/pull/416)
  **MERGED** at `9832004` - **race management cues** ([#406](https://github.com/agorokh/ac-copilot-trainer/issues/406)
  **CLOSED**): live stint-level fuel-to-finish, tyre, brake, and conditions advisories now ride
  beside Coach v2 / the legacy observer and emit through the existing `coaching.cue` + voice path.
  Lua telemetry publishes fuel and tyre temps when available; protocol validation covers the new
  channels. Review hardening added critical-tyre escalation and lap-rollback fuel reset tests.
- **2026-06-30** - PR [#410](https://github.com/agorokh/ac-copilot-trainer/pull/410)
  **MERGED** at `d669b19` - **Racing Atelier design package** ([#400](https://github.com/agorokh/ac-copilot-trainer/issues/400)
  **CLOSED**): committed the canonical handoff package and render-target gate, removed the retired
  AG Porsche Academy components, and added review hardening for offline/CDN warnings plus safer
  prototype `postMessage` origin handling. Post-merge classification found no flags. ZIP
  reconciliation showed all 95 package files present; real drift from the raw ZIP is intentional
  hardening, not missing content. Browser verification loaded Game Point, in-game HUD, and ESP32 rig
  kits over localhost with the expected Racing Atelier palette and instrument geometry. Details:
  [`pr-410-racing-atelier-design-package-2026-06-30`](../03_Investigations/pr-410-racing-atelier-design-package-2026-06-30.md).
- **2026-06-30** — PR [#394](https://github.com/agorokh/ac-copilot-trainer/pull/394) **MERGED** at
  `b14c984` — **voice reliability for packaged Game Point** ([#392](https://github.com/agorokh/ac-copilot-trainer/issues/392)
  **CLOSED**): sidecar `/health.voice` is the launcher source of truth; Game Point now reports
  disabled/stale schema-v1 banks, adopted no-voice sidecars, missing old voice health, observer-only
  sidecars when playback was requested, and pyttsx3 startup failures honestly. PyInstaller collects
  the installable voice floor (`numpy`, `sounddevice`, `pyttsx3`) and only collects opt-in `rtmixer`
  modules when present. Windows packaged proof was captured on `pc` at the packaging head; final
  review-fix behavior was re-smoked locally because `pc` was offline before merge. Details:
  [`pr-394-voice-reliability-2026-06-30`](../03_Investigations/pr-394-voice-reliability-2026-06-30.md).
- **2026-06-30** — PR [#395](https://github.com/agorokh/ac-copilot-trainer/pull/395) **MERGED** at
  `b122e1b` — **M-TT2 Track Titan reference archive builder** ([#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)):
  `tools.tt_ingest reference` builds schema-v1 `lap_archive` records from retained TT services
  telemetry, with strict full-lap spatial coverage, reference-lap timing/identity validation,
  debug-only partial metadata, and a runtime guard so partial TT archives cannot install as M0 live
  observers. Lake discovery is scoped by session/lap, repeated same-lap `/last-session` captures are
  retained as deterministic segment-window files, and archive output cannot overwrite retained TT
  inputs. Classification: no migration/env/deps/workflow flags. #353 stays OPEN for M-TT3
  per-corner analysis -> harness curriculum/oracle work and for live full-window capture before
  production non-partial TT references exist.
- **2026-06-29** — PR [#370](https://github.com/agorokh/ac-copilot-trainer/pull/370) **MERGED** at
  `26e9a09` — **M-TT1 Track Titan services crack** ([#353](https://github.com/agorokh/ac-copilot-trainer/issues/353)):
  `tools/tt_ingest/tt_services.py` (services client) + `coaching` CLI retaining per-lap raw
  reference + advice evidence to the write-once lake. **Auth corrected**: services `/api/v2/*` /
  `/dynamic-reference-laps/*` / `/advice/*` use the raw Cognito **access token** (not SigV4 — that
  was the disproved hypothesis); verified live (accessToken→200, idToken→403). Per-corner coaching
  oracle works E2E. Classification: additive `tools/`+tests+fixtures, no migrations/env/deps.
  Resume → **M-TT2** (reference telemetry → `lap_archive` → M0 `--reference-archive`). Full state:
  [`tt-services-sigv4-crack-2026-06-29`](../03_Investigations/tt-services-sigv4-crack-2026-06-29.md).
- **2026-06-29** — PR [#365](https://github.com/agorokh/ac-copilot-trainer/pull/365) **MERGED** at
  `854f822` — **Game Point launcher supervisor** ([#363](https://github.com/agorokh/ac-copilot-trainer/issues/363)
  **CLOSED**): Windows launcher package/shortcut/settings, supervised sidecar start/status/logging,
  environment-only sidecar token/voice routing, Pocket Technician spinner controls, Setup Exchange
  proxy/install path + rig-screen browse/download/install UI, and Game Point docs. Classification:
  `.env.example` and `pyproject.toml` changed; no migrations.
- **2026-06-28** — PR [#348](https://github.com/agorokh/ac-copilot-trainer/pull/348) **MERGED** at
  `226bc97` — **Coaching lakehouse DuckDB** ([#344](https://github.com/agorokh/ac-copilot-trainer/issues/344) P1):
  embedded DuckDB star schema in `tools/coaching_lake` rebuilt from lap-archives.
  9 off-sim tests, ~46s build time. Closes the P1 query engine requirement for EPIC #344.
- **2026-06-28** — PR [#349](https://github.com/agorokh/ac-copilot-trainer/pull/349) **MERGED** at
  `c477aee` — **live voice wiring** ([#341](https://github.com/agorokh/ac-copilot-trainer/issues/341)
  M0 **CLOSED**): sidecar turns the live `telemetry_tick` stream into spoken cues — `coaching.cue` topic
  + `voice` client-class + optional `spline`/`lap` validation; `server.py` `_publish_coaching_cues`
  feeds the `RealtimeObserver` per tick → speaks via the in-process #340 `VoiceCoach` **and** publishes
  `coaching.cue` to WS peers; `--voice-reference`/`--voice-bank` flags (audio deps lazy, OFF by default).
  A parallel session hardened it (scheduler tie-break by rank→freshness + act-cue latency logging). 9
  wiring tests + e2e round-trip; ci-fast green. **#350 follow-up:** the Lua `telemetry_tick`-with-`spline`
  producer already shipped (`telemetry_publisher.lua`, #341/#342) and **PR [#372](https://github.com/agorokh/ac-copilot-trainer/pull/372)
  MERGED** (`e0c93fd`, 2026-06-29) re-scoped to the bake path (batch Piper + 48 kHz default). **Only the
  on-rig audible smoke remains** — rig-gated, currently SSH-blocked from m5 → [#350](https://github.com/agorokh/ac-copilot-trainer/issues/350) (OPEN).
- **2026-06-28** — PR [#338](https://github.com/agorokh/ac-copilot-trainer/pull/338) **MERGED** at
  `f8d010e` — CoachingOracle **Qodo round-6 hardening** ([#333](https://github.com/agorokh/ac-copilot-trainer/issues/333)
  follow-up to #334): None-on-failure `get_coaching()`, spaced debrief OCR marker, nested-None coercion,
  WinRT await budget + cancel, helper timeout tests (19/19). No post-merge classification flags.
- **2026-06-28** — PR [#343](https://github.com/agorokh/ac-copilot-trainer/pull/343) **MERGED** at
  `f50719c` — **in-the-ear voice coach** ([#340](https://github.com/agorokh/ac-copilot-trainer/issues/340)
  **CLOSED**): new `tools/ai_sidecar/voice/` speaks the same `Advisory` stream the text HUD renders, via
  a pre-rendered phrase bank (not live TTS) + urgency scheduler (barge-in/dedup/TTL/cooldown). Stdlib
  core dep-free (audio deps behind a new `voice` extra); 51 tests; `make ci-fast` green. Off-rig verified:
  emit→dispatch latency **1.27 ms** (≤150 ms budget), 9.19 s real-speech WAV. Decision:
  [`voice-coach-architecture-2026-06-28`](../01_Decisions/voice-coach-architecture-2026-06-28.md).
  **Deferred (rig-gated):** on-rig audible verification at the wheel; v1.1 number-splicing. #154 stays OPEN.
- **2026-06-27** — PR [#325](https://github.com/agorokh/ac-copilot-trainer/pull/325) **MERGED** at
  `0fb721f` — `tools/ac_harness/auto_drive.py`: one-command composed L2 loop (launch → hijack → drive
  → WS assert), driver modes cruise/racing/**ggv flat-out**, sim-death anti-false-green, `max_gear_used`;
  closes [#324](https://github.com/agorokh/ac-copilot-trainer/issues/324). Live-verified non-Magione /
  non-Porsche: Imola+Audi R8 LMS (full lap + reference coaching), Mugello+Corvette C7R, Spa+BMW Z4 GT3
  **flat-out 6th gear / 211 km/h** with reference coaching. 21 off-sim tests; no post-merge flags.
  #154 stays OPEN.
- **2026-06-19** — PR [#248](https://github.com/agorokh/ac-copilot-trainer/pull/248) **MERGED** at
  `88249bf` — Stanley steering + `RacingDriver.from_human_profile` ([#244](https://github.com/agorokh/ac-copilot-trainer/issues/244)).
  **LIVE-VERIFIED on `AG_PC`**: 3 AC VALID laps via carcsw (best 106.8 s, 207.6 km/h, gears 1–6),
  sidecar `delta=2935` + `coaching.snapshot=3797`, agent lap captured as trainer reference. The
  steering/telemetry wall is broken. Residual: pace ~85% of human (`avg ≳100 km/h` bar unmet; defaults
  near-optimal, aggressive tuning regressed) → remaining Part-G scope on #244. #244/#154 stay OPEN.
  See [`stanley-steering-live-verified-2026-06-19`](../03_Investigations/stanley-steering-live-verified-2026-06-19.md).
- **2026-06-19** — PR [#249](https://github.com/agorokh/ac-copilot-trainer/pull/249) **MERGED** at
  `4e2a310` — mitigates [#246](https://github.com/agorokh/ac-copilot-trainer/issues/246) by replacing
  synchronous lap-complete archive writes with a queued per-frame `lapArchive.createWriteJob`, temp-file
  streaming/finalization, and retrying `setup.experiment.record` notifications after WS tick/poll.
  Classification: no post-merge flags. **Issue #246 remains open until live AC rig proof confirms the
  S/F render freeze is gone.**
- **2026-06-19** — PR [#242](https://github.com/agorokh/ac-copilot-trainer/pull/242) **MERGED** at `372156a` — closed [#241](https://github.com/agorokh/ac-copilot-trainer/issues/241) with `tools/ac_harness/racing_driver.py` (speed-profile following, braking points, trail braking, traction throttle; 12 tests) + `tools/ac_harness/racing_telemetry.py` (human-lap CSV recorder). Gear bug fixed (1→4 shifts, 146 km/h). Classification: no post-merge flags. **Next:** human-lap capture + path-tracking steering controller ([#244](https://github.com/agorokh/ac-copilot-trainer/issues/244)).
- **2026-06-16** — **#188 CLOSED** (on the rig, autonomous-deliver). Direct probe on `AG_PC`: `car.resetCounter` **present** (`[COPILOT][WRAP-SKEW-PROBE] resetCounter present=true value=2`) → teleports fully handled → closed as moot ([close comment](https://github.com/agorokh/ac-copilot-trainer/issues/188#issuecomment-4725615887)). No code change (the #199 defensive deferral stays). New rig-ops node: [steam-elevation-mismatch-ac-launch-2026-06-16](../03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md).
- **2026-06-16** — **#190 CLOSED** — EPIC #154 Part E complete. Merged PRs: [#191](https://github.com/agorokh/ac-copilot-trainer/pull/191) L1.5 probe, [#209](https://github.com/agorokh/ac-copilot-trainer/pull/209)/[#221](https://github.com/agorokh/ac-copilot-trainer/pull/221)/[#222](https://github.com/agorokh/ac-copilot-trainer/pull/222)/[#223](https://github.com/agorokh/ac-copilot-trainer/pull/223) carcsw driver, [#201](https://github.com/agorokh/ac-copilot-trainer/pull/201) session replay for late taps. Live-verified autonomous lap + coaching on Magione. Next EPIC thread: Part F harness daemon.
- **2026-06-16** — PR [#206](https://github.com/agorokh/ac-copilot-trainer/pull/206) **MERGED** at `7d87f96` — closed [#114](https://github.com/agorokh/ac-copilot-trainer/issues/114) with setup experiment tracking and suggestions. Adds `tools.ai_sidecar.setup_optimizer`, JSONL experiment rebuild/live recording from lap archives, setup A/B comparison, deterministic expected-improvement suggestion, CLI + v1 websocket frames, Lua store registration/recording, path safety, corrupt-store/missing-dir guards, and docs in [`13_Setup_Experiments`](../../../10_Development/13_Setup_Experiments.md). Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#204](https://github.com/agorokh/ac-copilot-trainer/pull/204) **MERGED** at `dc93b1b` — closed [#115](https://github.com/agorokh/ac-copilot-trainer/issues/115) with `tools.lap_archive_export`, a streamed lap-archive CSV exporter plus deterministic MoTeC-shaped CSV bridge, documented in [`13_Lap_Archive_Export`](../../../10_Development/13_Lap_Archive_Export.md). Output paths are contained under cwd, invalid laps are skipped by default, mixed MoTeC inputs are rejected, and post-merge classification found no flags. Active focus remains #190.
- **2026-06-16** — PR [#202](https://github.com/agorokh/ac-copilot-trainer/pull/202) **MERGED** at `d71bca3` — closed [#156](https://github.com/agorokh/ac-copilot-trainer/issues/156) by removing `scripts/` `sys.path` pollution from hook/manifest tests and adding `tools.testing.script_imports`, a path-aware file loader with sibling-script support that does not expose `scripts/mcp` as a namespace package. Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#205](https://github.com/agorokh/ac-copilot-trainer/pull/205) **MERGED** at `6d0ddc8` — generated reference-lap prototype for [#116](https://github.com/agorokh/ac-copilot-trainer/issues/116). Adds stdlib-only `tools.ac_harness.reference_lap`, schema-v1 `generated_reference_v1` archive emission, trainer-state bridge preserving driver PBs, validator hardening, and ADR [`rl-reference-lap-generation`](../01_Decisions/rl-reference-lap-generation.md) deferring RL runtime dependencies. Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#214](https://github.com/agorokh/ac-copilot-trainer/pull/214) **MERGED** at `3e9c927` — removed the PyYAML runtime dependency from the PR-pain allowlist gate after PR #198 exposed a failing post-merge `score` run. Adds `tools/pr_pain/config.py`, routes `.github/workflows/pr-pain-detection.yml` through it, and reuses it for `extra_bot_logins`. Classification: `.github/workflows/` changed; post-merge `PR pain detection / score` succeeded on the merge commit. Active focus remains #190.
- **2026-06-16** — PR [#200](https://github.com/agorokh/ac-copilot-trainer/pull/200) **MERGED** at `ee25118` — detect-and-retry AC entry launcher; closes [#177](https://github.com/agorokh/ac-copilot-trainer/issues/177). Adds `tools/ac_harness/entry_launcher.py`, a pluggable `EntryLauncher`, default `ColdRestartActuator`, atomic `race.ini` `SPAWN_SET=PIT` normalization, retry/relaunch loop around `DrivingEntryDetector`, and CLI timing knobs. Classification: no post-merge flags. Mac-side verification is complete; live Windows/AC rig verification remains the next runtime smoke. Active focus remains #190.
- **2026-06-16** — PR [#207](https://github.com/agorokh/ac-copilot-trainer/pull/207) **MERGED** at `0c637e3` — MoTeC CSV reference-lap importer plus opt-in imported-reference activation; closes [#79](https://github.com/agorokh/ac-copilot-trainer/issues/79). Imported laps write schema-v1 `source="imported"` / `import_format="motec_csv"` archive JSON and can drive realtime coaching only when faster than the local PB, without overwriting local PB persistence. Classification: no post-merge flags. Active focus remains #190.
- **2026-06-16** — PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) **MERGED** at `e5103be` — sidecar physical-peripheral protocol (`telemetry_tick`, `haptic_event`), derived haptic cues, haptics/screen routing, signed slip, partial tyre maps, legacy `ac-copilot-screen-*` classification; closes [#118](https://github.com/agorokh/ac-copilot-trainer/issues/118). No migration/env/deps/script/workflow post-merge flags; active focus remains #190.
- **2026-06-16** — PR [#198](https://github.com/agorokh/ac-copilot-trainer/pull/198) **MERGED** at `4a8ab98` — CI policy now accepts documented `vault/post-merge-pr<N>` handoff branches via `vault/`; closes [#179](https://github.com/agorokh/ac-copilot-trainer/issues/179). Classification: `scripts/` changed; no runtime/migration action. Active focus remains #190.
- **2026-06-16** — PR [#197](https://github.com/agorokh/ac-copilot-trainer/pull/197) **MERGED** at `392a868` — `ws_bridge.openEpoch()` reconnect re-arm for lifecycle `session` emission; closes [#183](https://github.com/agorokh/ac-copilot-trainer/issues/183). No migration/env/deps/script/workflow post-merge flags; active focus remains #190.
- **2026-06-13** — PR [#165](https://github.com/agorokh/ac-copilot-trainer/pull/165) **MERGED** at `1a08d45` — fleet-propagated `secrets-from-doppler` Scope-clause CI drift-guard (`tests/test_invariants_present.py`; template-repo#308/#309). Infra only; does not move Stream A / EPIC #154.
- **2026-05-17** — PR [#100](https://github.com/agorokh/ac-copilot-trainer/pull/100) **MERGED** at `ac810c0` — PT row BB chip refresh (LVGL + Lua `chipInt` + firmware JSON int path); closes [#93](https://github.com/agorokh/ac-copilot-trainer/issues/93).
- **2026-05-17** — PR [#99](https://github.com/agorokh/ac-copilot-trainer/pull/99) **MERGED** at `ebdef7e` — `tools/session_journal.py` loader hardening + tests; closes [#97](https://github.com/agorokh/ac-copilot-trainer/issues/97).
- **2026-04-29** — PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** at `35d770c` — Phase-2 LVGL rig screen Parts A–D (launcher, AC Copilot mirror, Pocket Technician, trainer/sidecar plumbing).
- **2026-04-25** — PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) development: Part A + B through full Parts C+D bring-up (pre-merge branch work).
- **2026-04-25** — PR [#89](https://github.com/agorokh/ac-copilot-trainer/pull/89) `.gitattributes *.sh/*.bash eol=lf` **MERGED** at `a55a0ed`. Hotfix for the Windows CRLF hook misfire from PR #87. Same item is queued upstream as part of `[agorokh/template-repo#97](https://github.com/agorokh/template-repo/issues/97)`.
- **2026-04-24** — PR [#87](https://github.com/agorokh/ac-copilot-trainer/pull/87) **template sync to template-repo@061d9ab** MERGED at `ab13a71`. Fixes orchestrator hook-drift, ships 9 new skills, deterministic flow-control hooks, post-merge steward + `vault-automerge.yml`. Upstream tracker `agorokh/template-repo#97` for 17+ deferred items. Full context in `[03_Investigations/template-sync-pr87-2026-04-24](../03_Investigations/template-sync-pr87-2026-04-24.md)`.
- **2026-04-22** — Session MCP infra: installed TurboVault + 6 MCP servers; see `~/Projects/mcp-work/mcp-servers` + `docs.claude.md`.
- **2026-04-22** — PR [#84](https://github.com/agorokh/ac-copilot-trainer/pull/84) vault post-merge handoff.
- **2026-04-22** — PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) external WS + Lua bridge MERGED.
- **2026-04-22** — PR [#80](https://github.com/agorokh/ac-copilot-trainer/pull/80) post-merge steward automation.
- **2026-04-21** — PR [#78](https://github.com/agorokh/ac-copilot-trainer/pull/78) sidecar auto-launch + per-lap archive (schema v1, 500 MB cap). See `[pr-78-sidecar-autolaunch-lap-archive](../03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md)`.
- **2026-04-14** — PR [#75](https://github.com/agorokh/ac-copilot-trainer/pull/75) Ollama corner coaching + CSP cdata-callable fixes.
- **2026-04-07** — PR [#73](https://github.com/agorokh/ac-copilot-trainer/pull/73) Phase-5 HUD rebuild + bundled Michroma/Montserrat/Syncopate fonts + `FIXED_SIZE` manifest.
- **2026-04-06** — PR [#70](https://github.com/agorokh/ac-copilot-trainer/pull/70) visual design match with Figma spec.
