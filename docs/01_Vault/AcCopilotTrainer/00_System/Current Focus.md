---

## type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-06-16T23:15:00Z
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - AcCopilotTrainer/03_Investigations/_index.md

# Current focus

**Repo:** ac-copilot-trainer.

**Active focus (2026-06-16):** [#188](https://github.com/agorokh/ac-copilot-trainer/issues/188) rig verification — `resetCounter` presence + s/f wrap-skew probe on `pc` (code in [#199](https://github.com/agorokh/ac-copilot-trainer/pull/199) already on `main`). [#190](https://github.com/agorokh/ac-copilot-trainer/issues/190) **CLOSED**. Next EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) thread after #188: Part F harness daemon. Parallel hot path: Stream A rig screen EPIC [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) Parts E–F.

**Infra (2026-05-20):** PR [#111](https://github.com/agorokh/ac-copilot-trainer/pull/111) closed the [#108](https://github.com/agorokh/ac-copilot-trainer/issues/108) agent-surface campaign (closeout doc only; five agent SHA alignments deferred). PR [#109](https://github.com/agorokh/ac-copilot-trainer/pull/109) memory-contract cursor rule fix remains on `main`.

## Stream A — Rig screen Phase-2 UI (PR #91 merged — Parts A–D on `main`)

**Infra (2026-05-16):** PR [#96](https://github.com/agorokh/ac-copilot-trainer/pull/96) landed template-2026.05 deterministic Claude hooks on `main` (`5d3019e`) — does not change device/UI scope; removes LLM-bearing Stop/PreToolUse hooks that caused session stalls.

**Status:** PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** `2026-04-29T17:02:22Z` as squash commit `[35d770c](https://github.com/agorokh/ac-copilot-trainer/commit/35d770c7e51da021133488809d4c5dbd254e0195)` on `main` (LVGL 8.3 portrait UI, launcher, AC Copilot mirror + `coaching.snapshot`, Pocket Technician + `setup.list` / `setup.load`, trainer Lua/sidecar protocol, lap-archive path alignment, Windows `ar` batching). Device bring-up catalogue: `[screen-end-to-end-bringup-2026-04-26](../03_Investigations/screen-end-to-end-bringup-2026-04-26.md)`.

PR #83 (WS + Lua bridge) **MERGED 2026-04-22** at `caa8a9ad` — still the foundation under Stream A.

**Outstanding housekeeping:** Issue [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81) may still be OPEN from before PR #83 — close with `gh issue close 81` when confirmed duplicate.

**Next (EPIC #86 remainder, new PRs):**

- **Part E** — Setup Exchange (`se_proxy.py`, SPIFFS LRU) per issue.
- **Part F** — SPIFFS persistence, telemetry backpressure, debug screen, token runbook.
- **Part A4** — `lv_font_conv` for bundled faces (screens still default to built-in Montserrat until converted).
- **Polish / bugs** — `start_sidecar.bat` external-bind + token; PT BB chip refresh landed in PR [#100](https://github.com/agorokh/ac-copilot-trainer/pull/100) (optional on-device smoke).

**Live-dev:** Hotspot + sidecar path per `[glossary/rig-network.md](../glossary/rig-network.md)`. Firmware: `python -m platformio run -e jc3248w535` under `firmware/screen/` (CI does not build firmware).

## Stream B — CSP-apps integration (Pocket Technician, Setup Exchange)

Integration ADR landed 2026-04-21 as `[screen-and-csp-apps-integration.md](../01_Decisions/screen-and-csp-apps-integration.md)`. Verdict: **replicate, don't bridge.** Our trainer Lua VM calls `ac.getSetupSpinners()` + `ac.setSetupSpinnerValue()` directly (same APIs PT uses); sidecar watches `UserSetups/<carID>/` for SX-dropped files. Both PT and SX stay installed; we coexist, not compete.

Surface map of both apps lives in `[csp-app-pocket-tech-setup-exchange-2026-04-21](../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md)`.

**Next:** `setup.list` / `setup.load` shipped with PR #91; remaining B-stream work is spinner tiles / `setup_control.lua` if still desired, plus Setup Exchange (Part E).

## Stream C — Physical rig integration EPIC #59

**New discovery**: `[10_Rig/physical-rig-integration-epic-59.md](../10_Rig/physical-rig-integration-epic-59.md)` captures the full scope — Arduino UNO (fan + OLED + seat vibration motors + pedal haptics), ESP32 touch dashboard (**Stream A is this**), Dayton BST-1 under-seat shaker (**done as Phase 1R**), salvaged Xbox controller motors for pedal haptics, full pin map.

**Protocol update (2026-06-16):** PR [#203](https://github.com/agorokh/ac-copilot-trainer/pull/203) delivered the sidecar `telemetry_tick` / `haptic_event` route for physical peripherals, including legacy rig-screen classification and haptics-only fan-out. Downstream hardware firmware can now consume a stable sidecar contract; active dev focus still stays on #190 / carcsw productionization.

Stream A is the first slice of this epic. Phase 3b (side bolster motors) and Phase 4 (pedal haptics) land after Phase 2 screen is fully wired.

## Stream D — PR #75 in-game smoke test (carried-over)

Now **MERGED 2026-04-14**. Ollama corner coaching pipeline (`corner_query` / `corner_advice`, sub-550 ms) is live. See `[pr-75-ollama-corner-coaching-protocol](../03_Investigations/pr-75-ollama-corner-coaching-protocol.md)` for the protocol the rig screen can subscribe to.

## Priority call

Stream A (rig screen Phase-2 LVGL + Figma UI + setup spinner tiles) is the hot path — user designed the visuals, firmware Phase 1 is end-to-end working, next tangible win is "tap a tile on the screen, see the setup change in-game." Stream B integration is folded into Stream A's protocol work.

## Recently landed (reverse chronological)

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
