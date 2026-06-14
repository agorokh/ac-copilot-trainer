---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-06-13T00:00:00Z
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

## Resume here (2026-06-14 — autonomous run ON the rig AG_PC; #170 handshake fix MERGED; EPIC #154 rig-local unlock)

**Biggest reframe:** this session ran **Claude Code directly on the rig** (`AG_PC`, Tailscale `100.75.251.87` — the exact host EPIC [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) calls "blocked"). The `status:blocked-on-rig` control-channel premise is **obsolete for a locally-running agent**: direct local launch (`acs.exe`) + headless observation (sidecar WS tap, CSP logs, Windows-MCP screenshots). See the [#154 rig-local-unlock comment](https://github.com/agorokh/ac-copilot-trainer/issues/154#issuecomment-4700939387). On-box confirmed: AC user-data = `C:\Users\arsen\OneDrive\Documents\Assetto Corsa` (`cfg\race.ini` present → operator-ask #3 closed); Steam logged in (`agorokh3`); AC+CSP(`dwrite.dll`)+Content Manager installed; `apps\lua\AC_Copilot_Trainer` is a **symlink → repo `src/ac_copilot_trainer`** (edit repo = live in AC after an AC relaunch). Proven: AC launches+renders, CSP loads, trainer reads live car-0 state (`[COPILOT][RT-DIAG] sp=… trackLen=3559`).

**SHIPPED — [#170](https://github.com/agorokh/ac-copilot-trainer/issues/170) / PR [#171](https://github.com/agorokh/ac-copilot-trainer/pull/171) MERGED (squash `7a5b99c`):** a **real production bug found only by running on the rig** — the trainer connected to the sidecar but **never registered as a v1 peer**, so `coaching.snapshot` was silently rejected and never fanned out (rig-screen mirror + any harness tap). Three coupled defects in `ws_bridge.lua`: (1) `publishTopic` published before the hello handshake (guarded only on `sock`); (2) the sidecar's `{v:1,type:error}` reply false-positively set `sidecarProtocolReady`, cancelling the hello retry; (3) the retry was sim-time-paced, frozen in the pre-drive pit menu. Fix: gate `publishTopic`+hello-retry-stop on a **v1-only `externalHelloAcked`** (decoupled from legacy `protocol=1` readiness — chatgpt-codex P1); never flip readiness on error frames; **frame-paced** retry; **re-arm in `onOpen`** for CSP auto-reconnect (CodeRabbit Major). New lupa L0 regression `tests/test_ws_bridge_hello_handshake.py` (6 tests, all green). CI green, both bot threads resolved, full cooldown honored.

**Verification status (honest):** #170 verified by the deterministic lupa suite + observed in-game mechanism (pre-fix rejection storm at the WS layer, post-fix suppressed). The in-game **positive** confirmation (`coaching.snapshot` flowing during real driving) is **blocked on a one-time human action** — see below.

**KEY finding — garage→on-track autonomy (the EPIC's crux):** full investigation in [`03_Investigations/garage-to-track-autonomous-entry-2026-06-13`](../03_Investigations/garage-to-track-autonomous-entry-2026-06-13.md). Two stages: (1) **session entry** is a *launch* problem — `race.ini` Hotlap (`[SESSION_0] TYPE=3 SPAWN_SET=HOTLAP`) + `acs.exe` spawns car 0 **on track** (verified: `sp` advances), BUT does **NOT** skip the pre-drive "Drive" screen — `sim.isInMainMenu` stays true so `wsBridge.tick` never runs. OS input injection into AC's menu is **confirmed dead** (raw input + no background focus). **The single minimal human action that unlocks full in-sim autonomy = enable Content Manager → Settings → Drive → "start session immediately" ONCE**; thereafter launch-into-driving is click-free. (2) **driving** once on track = CSP **Custom AI mmap** (sidecar writes `cai_car_controls` at 333 Hz); the trainer App context can't pilot (APIs `__allow`-gated to newmodes/cphys) — App stays the control plane.

**Next moves (priority):**
1. **Part D — make the 5 declared WS topics real** (the next clean deliverable; **headless-verifiable, NOT blocked by driving**). Full build plan from a 4-agent research workflow: expand `external_protocol.py KNOWN_TOPICS` to the honest 7-name set (add `coaching.snapshot` + `setup.active`); add producers — `connection_publisher.lua` (~1 Hz), `session_publisher.lua` (event), inline `lap` publish at the lap boundary, `delta_publisher.lua` (10 Hz, reuses `delta.deltaSecondsAtSpline`), `tire_temps` (new `Mon:currentTemps()` + publish after `tires:update`); keep `state.subscribe` advisory (fan-out is already topic-agnostic broadcast). Verify via a new lupa test mirroring `test_ws_bridge_hello_handshake.py` + a **drift-guard** test (every `publishTopic("<lit>"` ∈ KNOWN_TOPICS — structural fix for the #170-class "forgot the allow-list" pitfall). All publishes MUST go through `wsBridge.publishTopic` (the line-984 `sock and externalHelloAcked` gate); pcall-guard all sim/car reads.
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
