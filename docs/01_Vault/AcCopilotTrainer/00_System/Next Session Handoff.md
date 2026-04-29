---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-29T17:20:00Z
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
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
  - AcCopilotTrainer/03_Investigations/pr-75-ollama-corner-coaching-protocol.md
  - AcCopilotTrainer/03_Investigations/template-sync-pr87-2026-04-24.md
---

# Next session handoff

## Resume here (2026-04-29 — PR #91 merged to `main`)

PR [#91](https://github.com/agorokh/ac-copilot-trainer/pull/91) **MERGED** `2026-04-29T17:02:22Z` as squash [`35d770c`](https://github.com/agorokh/ac-copilot-trainer/commit/35d770c7e51da021133488809d4c5dbd254e0195). **Issue #86 Parts A–D** (LVGL launcher, AC Copilot mirror, Pocket Technician + trainer/sidecar) are on `main`. Post-merge steward: `scripts/post_merge_classify.py --pr 91` reported **no** migration/env/deps/script flags.

**Still the best single read for device reality:** [screen-end-to-end-bringup-2026-04-26.md](../03_Investigations/screen-end-to-end-bringup-2026-04-26.md) (eight root causes fixed between CI-green and on-device green).

**Open follow-ups** (next PRs / issue #86 E–F):

1. **`start_sidecar.bat` loopback-only** — rig screen needs `--external-bind 0.0.0.0` + token path (see bring-up doc).
2. **BB chip stale on some PT rows** — FW-side; trainer sends correct values.
3. **Part A4 fonts** — run `lv_font_conv` for bundled TTFs; until then Montserrat 14 ASCII only.
4. **Part E / Part F** per EPIC #86 (Setup Exchange, polish/SPIFFS/debug).

**Hotspot pitfall:** disable Windows Mobile Hotspot power-saving when AC runs (see [`wifi-hotspot-single-radio-2026-04-26`](../03_Investigations/wifi-hotspot-single-radio-2026-04-26.md)).

### Branch + PR state

Feature branch `feat/issue-86-rig-screen-phase2-launcher-and-apps` was deleted locally after merge (remote may still exist briefly). Continue from **`main`** @ `35d770c` or newer.

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
