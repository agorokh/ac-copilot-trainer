---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-25T07:30:00Z
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/10_Rig/physical-rig-integration-epic-59.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Current focus

**Repo:** ac-copilot-trainer.

## Stream A — Rig screen Phase-2 UI (PR #91 OPEN — Part A + Part B in flight)

**Status:** PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **OPEN, ready for review** at head `8f88881` (2026-04-25). Branch `feat/issue-86-rig-screen-phase2-launcher-and-apps`. Part A (LVGL 8.3 bring-up + framework + tokens + font staging, commit `4557da5`) and Part B (App Launcher screen + 3-second WS disconnect debounce, commit `8f88881`) both shipped. Part B's commit also folds in the 8 bot-review fixes against the Part A commit (gemini P1 touch coord underflow, chatgpt-codex P1 launcher-on-boot vs WS-open, sourcery P{S,RAM,nav,volatile}, Copilot heap_caps include + LV_TICK_CUSTOM + .gitignore + nav.h doc). First CI run on `4557da5` failed only on `ci-conventional` because the PR was opened with the EPIC's title and renamed afterwards — the post-rename CI run on `8f88881` should pass.

PR #83 (the foundation underneath all of this) **MERGED 2026-04-22T17:20** at head `caa8a9ad`. Sidecar external-bind + token auth + `{v,type}` protocol extension + Lua action/config bridge are live on `main`.

**Outstanding housekeeping:** Issue [#81](https://github.com/agorokh/ac-copilot-trainer/issues/81) still OPEN even though #83 (its implementation) merged — needs manual close with `gh issue close 81`.

**Next:** Resolve any new bot reviews against `8f88881`, monitor CI to green, mark PR #91 mergeable. Then Parts C–F land as follow-up commits on the **same** branch (per the issue's "single PR per epic" rule):
- **Part C** — AC Copilot mirror (ACCopilot.tsx port). New `coaching.snapshot` topic at 10 Hz from `coaching_overlay.lua`, plus `corner_advice` subscription from PR #75.
- **Part D** — Pocket Technician custom picker. First bidirectional screen — `setup_library.lua`, `setup.list`/`setup.load` WS pairs, pits-only safety gate.
- **Part E** — Setup Exchange browser. New `tools/ai_sidecar/se_proxy.py` proxying `http://se.acstuff.club`, SPIFFS LRU cache.
- **Part F** — SPIFFS persistence + telemetry backpressure + 5-tap debug screen + token rotation runbook.

**Live-dev requirement:** PC's **Windows Mobile Hotspot `AG_PC 7933`** must be on. Router AHOME5G mesh blocks cross-AP TCP. See [`00_System/glossary/rig-network.md`](../00_System/glossary/rig-network.md) for all the addresses.

**Hardware verification still pending:** Part A+B compile but have not been flashed (PlatformIO not on this agent's path; CI doesn't build firmware). Local verification step — `pio run -d firmware/screen` for compile, `-t upload` for flash — documented in PR #91 body.

## Stream B — CSP-apps integration (Pocket Technician, Setup Exchange)

Integration ADR landed 2026-04-21 as [`screen-and-csp-apps-integration.md`](../01_Decisions/screen-and-csp-apps-integration.md). Verdict: **replicate, don't bridge.** Our trainer Lua VM calls `ac.getSetupSpinners()` + `ac.setSetupSpinnerValue()` directly (same APIs PT uses); sidecar watches `UserSetups/<carID>/` for SX-dropped files. Both PT and SX stay installed; we coexist, not compete.

Surface map of both apps lives in [`csp-app-pocket-tech-setup-exchange-2026-04-21`](../03_Investigations/csp-app-pocket-tech-setup-exchange-2026-04-21.md).

**Next:** implement the same-VM `setup_control.lua` + new protocol types `setup.spinner.list/set/ack` and `setup.list/load`. Lands as Phase-2 work alongside the LVGL UI.

## Stream C — Physical rig integration EPIC #59

**New discovery**: [`10_Rig/physical-rig-integration-epic-59.md`](../10_Rig/physical-rig-integration-epic-59.md) captures the full scope — Arduino UNO (fan + OLED + seat vibration motors + pedal haptics), ESP32 touch dashboard (**Stream A is this**), Dayton BST-1 under-seat shaker (**done as Phase 1R**), salvaged Xbox controller motors for pedal haptics, full pin map.

Stream A is the first slice of this epic. Phase 3b (side bolster motors) and Phase 4 (pedal haptics) land after Phase 2 screen is fully wired.

## Stream D — PR #75 in-game smoke test (carried-over)

Now **MERGED 2026-04-14**. Ollama corner coaching pipeline (`corner_query` / `corner_advice`, sub-550 ms) is live. See [`pr-75-ollama-corner-coaching-protocol`](../03_Investigations/pr-75-ollama-corner-coaching-protocol.md) for the protocol the rig screen can subscribe to.

## Priority call

Stream A (rig screen Phase-2 LVGL + Figma UI + setup spinner tiles) is the hot path — user designed the visuals, firmware Phase 1 is end-to-end working, next tangible win is "tap a tile on the screen, see the setup change in-game." Stream B integration is folded into Stream A's protocol work.

## Recently landed (reverse chronological)

- **2026-04-25** — PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) Part A + Part B **OPEN** (head `8f88881`). LVGL bring-up, navigator, design tokens, the real Launcher screen + 3-second WS disconnect debounce. Awaiting CI green + bot follow-up sweep (PR resolution loop).
- **2026-04-25** — PR [#89](https://github.com/agorokh/ac-copilot-trainer/pull/89) `.gitattributes *.sh/*.bash eol=lf` **MERGED** at `a55a0ed`. Hotfix for the Windows CRLF hook misfire from PR #87. Same item is queued upstream as part of [`agorokh/template-repo#97`](https://github.com/agorokh/template-repo/issues/97).
- **2026-04-24** — PR [#87](https://github.com/agorokh/ac-copilot-trainer/pull/87) **template sync to template-repo@061d9ab** MERGED at `ab13a71`. Fixes orchestrator hook-drift, ships 9 new skills, deterministic flow-control hooks, post-merge steward + `vault-automerge.yml`. Upstream tracker `agorokh/template-repo#97` for 17+ deferred items. Full context in [`03_Investigations/template-sync-pr87-2026-04-24`](../03_Investigations/template-sync-pr87-2026-04-24.md).
- **2026-04-22** — Session MCP infra: installed TurboVault + 6 MCP servers; see `~/Projects/mcp-work/mcp-servers` + `docs.claude.md`.
- **2026-04-22** — PR [#84](https://github.com/agorokh/ac-copilot-trainer/pull/84) vault post-merge handoff.
- **2026-04-22** — PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83) external WS + Lua bridge MERGED.
- **2026-04-22** — PR [#80](https://github.com/agorokh/ac-copilot-trainer/pull/80) post-merge steward automation.
- **2026-04-21** — PR [#78](https://github.com/agorokh/ac-copilot-trainer/pull/78) sidecar auto-launch + per-lap archive (schema v1, 500 MB cap). See [`pr-78-sidecar-autolaunch-lap-archive`](../03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md).
- **2026-04-14** — PR [#75](https://github.com/agorokh/ac-copilot-trainer/pull/75) Ollama corner coaching + CSP cdata-callable fixes.
- **2026-04-07** — PR [#73](https://github.com/agorokh/ac-copilot-trainer/pull/73) Phase-5 HUD rebuild + bundled Michroma/Montserrat/Syncopate fonts + `FIXED_SIZE` manifest.
- **2026-04-06** — PR [#70](https://github.com/agorokh/ac-copilot-trainer/pull/70) visual design match with Figma spec.
