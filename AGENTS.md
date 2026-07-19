# Repository Guidelines

**This file guides all AI agents and human operators working in this repository.**

**Status:** AC Copilot Trainer
**Version:** 1.4
**Category:** Core

---

## Memory-first — every named agent starts with a Tier-3 substrate query

Every named agent in `.claude/agents/*.md` (issue-driven orchestrator, PR-resolution follow-up, post-merge steward, dependency review, learner) opens with a `## Tier-3 Substrate Query (mandatory first step)` section. The agent **must** issue at least one `mcp__agentic-memory__query_knowledge_graph` call with a task-specific prompt **before** any other action (routing, branch creation, classification, scoring, extraction). The runtime gate (`scripts/hook_memory_gate.py`) blocks code-path edits without a fresh, file-relevant Tier-3 stamp. Read the canonical contract at [`docs/00_Core/MEMORY_CONTRACT.md`](docs/00_Core/MEMORY_CONTRACT.md). Both Cursor and Claude Code load the same `.claude/agents/*.md` files — the procedure is unified across hosts.

---

## Mandatory reading

1. **[AGENT_CORE_PRINCIPLES.md](AGENT_CORE_PRINCIPLES.md)** — Non-negotiable workflow and hygiene.
2. **[docs/10_Development/10_Agent_Protocol.md](docs/10_Development/10_Agent_Protocol.md)** — Where files go and what is forbidden.
3. **[docs/00_Core/SESSION_LIFECYCLE.md](docs/00_Core/SESSION_LIFECYCLE.md)** — LOAD → OPERATE → SAVE; integrates with the vault graph.
4. **Vault (mandatory)** — Graph schema: [docs/01_Vault/00_Graph_Schema.md](docs/01_Vault/00_Graph_Schema.md); session files under `docs/01_Vault/AcCopilotTrainer/00_System/` (rename `AcCopilotTrainer` on bootstrap; see [docs/00_Core/BOOTSTRAP_NEW_PROJECT.md](docs/00_Core/BOOTSTRAP_NEW_PROJECT.md)).
5. **[docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md)** — Cursor, Claude Code, Claude Desktop, MCP — same rules across tools.
6. **Template maintainers:** [docs/00_Core/MAINTAINING_THE_TEMPLATE.md](docs/00_Core/MAINTAINING_THE_TEMPLATE.md) — how to keep the canonical template current.

**Agent mesh (Claude Code):** [CLAUDE.md](CLAUDE.md) § Orchestration gives the overview. **Cursor** users: the Task tool cannot use Claude Code agent names as `subagent_type`; use `generalPurpose` + `.claude/agents/*.md` checklists per [`.cursor/rules/cursor-task-delegation.mdc`](.cursor/rules/cursor-task-delegation.mdc). Key locations:

- **Routing table:** `~/.agents/skills/orchestrate/SKILL.md` § Routing
- **PR/bot loop:** `/resolve-pr` owns the `sleep 600` + GraphQL `reviewThreads` procedure (see `~/.agents/skills/resolve-pr/SKILL.md`)
- **Dependency/tooling PRs:** `dependency-review` fronts, then hands off to `/resolve-pr` (see `~/.agents/skills/dependency-review/SKILL.md`)

---

## Core principles (customize)

1. **Architecture-first** — Read existing modules and docs before adding parallel patterns.
2. **Issue-driven** — Default: GitHub Issue → branch → PR → review → merge.
3. **Single source of truth** — Prefer one obvious home for logic, config, and docs; link instead of duplicating.
4. **Observable changes** — Tests or scripted checks that prove behavior changed as intended.
5. **Security-first** — No secrets in repo; least privilege for tokens; document data sensitivity in the vault.

**Add domain-specific rules below** (service entry points, forbidden APIs, storage layout, etc.).

### Domain extension area

- **Runtime:** Assetto Corsa with Custom Shaders Patch (CSP) v0.2.11+
- **Primary language:** Lua 5.1 / LuaJIT 2.1 (CSP Lua apps)
- **Secondary:** Python 3 (AC Python apps for reference/porting)
- **UI framework:** Dear ImGui (via CSP ui.* namespace)
- **3D rendering:** CSP render.* API for track surface markers
- **Data sources:** AC shared memory, telemetry APIs, AI spline files
- **Target platform:** Windows (Assetto Corsa is Windows-only)
- **Installation path:** assettocorsa/apps/lua/{app_name}/
- **No writes outside** the app's own data folder and AC Documents folder

---

## PR workflow and branch naming

- **Branch examples:** `feat/issue-42-add-parser`, `fix/issue-99-race`, or team-specific `cursor/feat_issue-42_utcslug`.
- **PR title:** Imperative mood; reference Issue: `Fix cache key for batch job (#99)`.
- **Before ready for review:** `make ci-fast` passes; inline bot threads addressed or explained.

---

## Bot and review expectations

Treat automated review comments as blocking unless:

- The comment is factually wrong — reply with evidence and, if needed, open a follow-up Issue; or
- The finding is out of scope — state that explicitly and link the Issue that will cover it.

---

## Persistent memory (three tiers)

| Tier | Location | Use |
|------|----------|-----|
| 1 | `AGENTS.md` (bottom) | Short operational facts, policy updates |
| 2 | `docs/01_Vault/AcCopilotTrainer/` (+ `docs/01_Vault/00_Graph_Schema.md`) | Linked graph: ADRs, invariants, glossary, investigations, session handoff |
| 3 | Semantic substrate per [`ops/memory_manifest.yml`](ops/memory_manifest.yml) | **Read at LOAD** via `mcp__agentic-memory__query_knowledge_graph`; written indirectly via vault → ingest (see [`docs/00_Core/MEMORY_CONTRACT.md`](docs/00_Core/MEMORY_CONTRACT.md)) |

Skill: `~/.agents/skills/vault-memory/SKILL.md` (mirrored under `.cursor/skills/`). Session protocol: `docs/00_Core/SESSION_LIFECYCLE.md`.

**Bootstrap (new copy of this template):** `~/.agents/skills/new-project-setup/SKILL.md` (mirrored under `.cursor/skills/`) — `/new-project-setup`.

---

## Local development

- **Install:** see `README.md` and `WARP.md`.
- **Checks:** `make ci-fast` (format, lint, tests, policy scripts).
- **Pre-commit:** `make hooks-install` once per clone.
- **Optional stacks:** DB, AWS, HF, Ollama, browser automation — [docs/00_Core/OPTIONAL_CAPABILITIES.md](docs/00_Core/OPTIONAL_CAPABILITIES.md).
- **Sidecar reference lap (M0 voice coaching):** `AC_COPILOT_REFERENCE_ARCHIVE` — path to a faster reference lap archive JSON; used when starting the sidecar without `--reference-archive` so the live observer can emit `coaching.cue` advisories for the voice client.
- **Driver profile/progression (#403):** `AC_COPILOT_DRIVER_PROFILE` — optional path to `journal/driver/profile.json` under AC Documents or Game Point roots; used by Coach v2 to load returning-driver skill levels and tune cue density. Generate or refresh it with `python -m tools.ai_sidecar.driver_profile --lap-dir <journal/laps>`. When unset, Coach v2 tries `journal/driver/profile.json` under the sidecar's current working directory and otherwise keeps the baseline cue policy.
- **Voice phrase bank (M0 voice coaching):** `AC_COPILOT_VOICE_BANK` — path to a baked phrase-bank directory; used by `tools.ai_sidecar` and the Game Point launcher when no `--voice-bank` flag is passed. Requires `AC_COPILOT_REFERENCE_ARCHIVE` for live cue anchoring. Runtime routing is controlled by `AC_COPILOT_VOICE_BACKEND` (`rtmixer` or `sounddevice`), `AC_COPILOT_VOICE_DEVICE`, `AC_COPILOT_VOICE_HOST_API`, and `AC_COPILOT_VOICE_VERBOSITY`. Optional `AC_COPILOT_VOICE_TTS=1` enables the lightweight pyttsx3 fallback only when no phrase bank is configured; tune it with `AC_COPILOT_VOICE_RATE` (default `240`) and `AC_COPILOT_VOICE_VOLUME` (`0.0`–`1.0`).
- **Brake-cue lead (#522):** `AC_COPILOT_BRAKE_LEAD_S` — anticipatory brake-cue audibility budget in seconds (default `3.2`, clamped `1.0`–`6.0`): clip duration + audio-path latency + human reaction, so the heads-up finishes sounding with time to act. Raise slightly for the tablet audio path (adds ~0.35 s).
- **Rig-screen sidecar autostart (#86):** `AC_COPILOT_SIDECAR_TOKEN` — user-env token on the rig PC only; must match `firmware/screen/secrets/sidecar.h`, never commit or log a real value, and enables `start_sidecar.bat` to use an authenticated external bind. Optional overrides: `AC_COPILOT_SIDECAR_EXTERNAL_BIND` (default `0.0.0.0` when token is set) and `AC_COPILOT_SIDECAR_PORT` (default `8765`).
- **Game Point launcher (#363):** `tools.rig_launcher` is the canonical Windows entrypoint for driver-facing rig functions. New rig features the operator should start, monitor, or tune belong in the launcher UI/status/settings path rather than standalone desktop scripts. `AC_COPILOT_GAME_POINT_DIR` sets the optional per-user status/log/settings root for `python -m tools.rig_launcher` / the packaged launcher. Non-secret defaults can live in `%LOCALAPPDATA%\AC Copilot Trainer\GamePoint\settings.json`; secrets such as `AC_COPILOT_SIDECAR_TOKEN` stay in the user environment only. Build with `python -m tools.rig_launcher --build-exe`; create the Desktop link with `python -m tools.rig_launcher --install-shortcut`. The **Stable AC** action routes issue #624's resilient session loop through the launcher and its `AC Session` status row; configure `resilient_car`, `resilient_track`, optional `resilient_layout`, and optional `resilient_cm_exe` in `settings.json`, or override them with `AC_COPILOT_RESILIENT_CAR`, `AC_COPILOT_RESILIENT_TRACK`, `AC_COPILOT_RESILIENT_LAYOUT`, and `AC_COPILOT_RESILIENT_CM_EXE`. `AC_COPILOT_SIMHUB_EXE` points at `SimHubWPF.exe` when auto-discovery misses it; `AC_COPILOT_START_SIMHUB=1` (or the launcher's **Auto-start SimHub** checkbox, which persists `start_simhub` to `settings.json`, default off) lets the launcher start SimHub if installed, without modifying profiles or double-launching a running instance — SimHub is an optional haptics peer, never a blocking status row. Setup Exchange sidecar overrides: `AC_COPILOT_SE_ENDPOINT` for a proxy/test endpoint and `AC_COPILOT_USER_SETUPS_DIR` for the Assetto Corsa `setups` directory when Documents discovery is insufficient. See [docs/10_Development/14_Game_Point_Launcher.md](docs/10_Development/14_Game_Point_Launcher.md).
- **Tablet dashboard adb-reverse tunnel (#567):** the launcher can keep the tablet GT dashboard's USB `adb reverse tcp:<port> tcp:<port>` tunnel alive so a single launch brings the dash online (the sidecar starts on loopback; `adb reverse` bridges the tablet's loopback to it). Opt-in — off by default so CI/non-rig hosts never shell out to adb. `AC_COPILOT_MANAGE_TABLET_TUNNEL=1` enables the keeper (re-asserts the reverse on every status poll). `AC_COPILOT_ADB` sets an explicit `adb.exe` path when it isn't on `PATH` (the keeper also probes the Google.PlatformTools / scrcpy winget locations). `AC_COPILOT_ADB_SERIAL` selects the tablet's serial (from `adb devices`) when more than one authorized device/emulator is attached — otherwise the keeper reports `multiple-devices` rather than guessing. Requires a loopback or `0.0.0.0` sidecar bind (a concrete LAN bind is rejected as `bind-unreachable`, since `adb reverse` targets PC loopback).
- **Track Titan ingest (#353):** `TT_REFRESH_TOKEN` — the operator's **personal** TT refresh token for `python -m tools.tt_ingest`; source from Doppler / the shell (never commit), or omit to auto-discover from the TT desktop app's Local Storage on Windows. Optional public-identifier overrides: `TT_COGNITO_CLIENT_ID`, `TT_COGNITO_USER_POOL_ID`, `TT_COGNITO_IDENTITY_POOL_ID`, `TT_COGNITO_REGION` (defaults are the app's public ids, not secrets). Install the CLI's runtime dep with `pip install -e ".[tt-ingest]"`. **Sensitivity:** retained exports under `journal/tt/**` are **personal data** (the operator's own sessions) — gitignored, write-once immutable, never redistributed; tokens are personal secrets, never logged or committed (see the [TT coaching-oracle guardrail](docs/01_Vault/AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md)).

---

## Learned User Preferences

Stable operational principles derived from real usage across projects. Agents: read on session start; update when a durable preference is confirmed.

- **Group issues by files touched.** Never create separate issues that modify overlapping source files. Consolidate into one issue with labeled Parts. See AGENT_CORE_PRINCIPLES.md "Issue design."
- **Own every failure.** Never say "pre-existing." If it's broken, fix it now.
- **Preserve manual work.** Bulk operations and pipeline rebuilds must never delete user-created content (workbenches, curated notes, manual configs). Verify guards before running.
- **PR merge order matters.** Merge simpler PRs first, then rebase and merge complex ones. Check for CHANGELOG/docs overlaps.
- **Propagate universal improvements upstream.** When a domain-agnostic workflow principle is improved in any child repo, propagate it back to template-repo so all future projects inherit it. See AGENT_CORE_PRINCIPLES.md "Upstream template sync."

## Learned Workspace Facts
<!-- process-miner:learned:start -->
- (process-miner) New learned rule file(s): .claude/rules/learned/local/code-block-will-8ff22268.md, .claude/rules/learned/local/code-code-block-ensure-e69f49b0.md, .claude/rules/learned/local/code-extra-launcher-98a8d094.md, .claude/rules/learned/local/code-medium-code-block-8e8e0543.md, .claude/rules/learned/local/code-this-error-00bb1e7f.md, .claude/rules/learned/local/code-vault-paths-d532b711.md, .claude/rules/learned/local/code-will-medium-141c174b.md, .claude/rules/learned/local/failed-test-action-c6a4e01a.md, .claude/rules/learned/local/handoff-merge-vault-7cd266b3.md, .claude/rules/learned/local/investigation-handoff-next-42734e92.md, .claude/rules/learned/local/program-files-review-8075528a.md, .claude/rules/learned/local/prompt-copy-this-33f831d5.md, .claude/rules/learned/local/prompt-this-with-86d9871c.md, .claude/rules/learned/local/review-updated-latest-e5856fdf.md, .claude/rules/learned/local/token-prompt-this-50655dd2.md, .claude/rules/learned/local/tools-code-code-block-750ab553.md, .cursor/rules/learned/local/code-block-will-8ff22268.mdc, .cursor/rules/learned/local/code-code-block-ensure-e69f49b0.mdc, .cursor/rules/learned/local/code-extra-launcher-98a8d094.mdc, .cursor/rules/learned/local/code-medium-code-block-8e8e0543.mdc, .cursor/rules/learned/local/code-this-error-00bb1e7f.mdc, .cursor/rules/learned/local/code-vault-paths-d532b711.mdc, .cursor/rules/learned/local/code-will-medium-141c174b.mdc, .cursor/rules/learned/local/failed-test-action-c6a4e01a.mdc, .cursor/rules/learned/local/handoff-merge-vault-7cd266b3.mdc, .cursor/rules/learned/local/investigation-handoff-next-42734e92.mdc, .cursor/rules/learned/local/program-files-review-8075528a.mdc, .cursor/rules/learned/local/prompt-copy-this-33f831d5.mdc, .cursor/rules/learned/local/prompt-this-with-86d9871c.mdc, .cursor/rules/learned/local/review-updated-latest-e5856fdf.mdc, .cursor/rules/learned/local/token-prompt-this-50655dd2.mdc, .cursor/rules/learned/local/tools-code-code-block-750ab553.mdc
<!-- process-miner:learned:end -->


<!-- Append project-specific operational facts here after bootstrap. -->
<!-- Example: "Pipeline venv at .venv/bin/python", "Gmail expanded to N threads on DATE" -->

## Changelog (Tier 1)

<!-- CHANGELOG:START -->
- 2026-07-19: Rig launch reliability (#628/PR #629) — `acpmf_*` shared sections OUTLIVE `acs.exe` (measured PRESENT 14 s after `taskkill`) and stay mapped ~6 s INTO the next `acs.exe`'s lifetime, so a corpse reading is briefly both stale and live-correlated. **No `acpmf` field is trustworthy until the packet id ADVANCES while `acs.exe` is alive** — process liveness alone is not enough, and `is_live`/`is_in_pit` are exactly as stale as `packet_id` (a corpse reporting READY fired the Car0 handshake before AC existed → 6/6 attempts recorded as `froze`). Use `resilient_launch.SectionOwnershipGate`. Before trusting any rig freeze rate, confirm the launcher is on this fix. `QueryThreadCycleTime` gives a ~5 s spin-vs-block read without dumps, but a high cycle count is meaningless unless the graphics packet is simultaneously static — a healthy 67-thread `acs` burns a full core by design. `0x147B` in CSP's `accRenderingAdv.dll` is div-by-100 magic (base-100 bignum), NOT a hash multiplier — #627 §3.5 is wrong.
- 2026-03-30: Bootstrap ac-copilot-trainer from template-repo; domain extension for Assetto Corsa + CSP Lua runtime.
- 2026-03-27: v1.4 — Vault knowledge graph (`00_Graph_Schema.md`, `invariants/`, `glossary/`), `SESSION_LIFECYCLE.md`, agent/hook lifecycle wiring, expanded policy checks + root file allowlist warnings, `check_bootstrap_complete.py`, bootstrap doc refresh.
- 2026-03-27: v1.3 — Agent cohesion: orchestrator owns canonical Routing table; resolve-pr fixed loop numbering + exit/escalation + cross-links; dependency-review handoff to Task/pr-resolution; CLAUDE.md orchestration + skills table + delegation/context discipline; AGENTS.md agent mesh pointer.
- 2026-03-27: v1.2 — Multi-tool governance: TOOLCHAIN, OPTIONAL_CAPABILITIES, MAINTAINING_THE_TEMPLATE, GITHUB_SETUP; mandatory vault callout + maintainer link; CLAUDE.md quick start and Desktop/MCP/upstream-sync clarity; AGENT_CORE_PRINCIPLES child-vs-template upstream wording; README "keeping current"; Dependabot groups; gitignore `.claude.local.md`.
- 2026-03-26: v1.1 — Added issue-grouping-by-file-overlap, own-every-failure, preserve-manual-work, upstream-sync. (Source: example-doc-pipeline learnings)
<!-- CHANGELOG:END -->

<!-- memory-contract:start -->
<!-- DO NOT EDIT BY HAND. Re-render with: python3 scripts/merge_memory_contract.py -->

## Memory contract (pointer)

Per-agent substantive rules live in `.claude/agents/*.md` — each file opens with **`## Tier-3 Substrate Query (mandatory first step)`** before its procedure. The **Memory-first** section at the top of this file summarizes the unified requirement for all named agents.

References:

- Canonical contract: [`docs/00_Core/MEMORY_CONTRACT.md`](docs/00_Core/MEMORY_CONTRACT.md).
- Canonical invariant: [`memory-three-tiers.md`](docs/01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md).
- Runtime enforcement: `scripts/hook_memory_gate.py` (see contract doc).
- Kill switch: `CLAUDE_MEMORY_GATE=0` bypasses the gate; surface why in the vault SAVE so the next session can correct.

Originating postmortem: [template-repo#115](https://github.com/agorokh/template-repo/issues/115).

<!-- memory-contract:end -->
