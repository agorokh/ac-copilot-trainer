# Repository Guidelines

**This file guides all AI agents and human operators working in this repository.**

**Status:** AC Copilot Trainer
**Version:** 1.4
**Category:** Core

---

## Mandatory reading

1. **[AGENT_CORE_PRINCIPLES.md](AGENT_CORE_PRINCIPLES.md)** — Non-negotiable workflow and hygiene.
2. **[docs/10_Development/10_Agent_Protocol.md](docs/10_Development/10_Agent_Protocol.md)** — Where files go and what is forbidden.
3. **[docs/00_Core/SESSION_LIFECYCLE.md](docs/00_Core/SESSION_LIFECYCLE.md)** — LOAD → OPERATE → SAVE; integrates with the vault graph.
4. **Vault (mandatory)** — Graph schema: [docs/01_Vault/00_Graph_Schema.md](docs/01_Vault/00_Graph_Schema.md); session files under `docs/01_Vault/AcCopilotTrainer/00_System/` (rename `AcCopilotTrainer` on bootstrap; see [docs/00_Core/BOOTSTRAP_NEW_PROJECT.md](docs/00_Core/BOOTSTRAP_NEW_PROJECT.md)).
5. **[docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md)** — Cursor, Claude Code, Claude Desktop, MCP — same rules across tools.
6. **Template maintainers:** [docs/00_Core/MAINTAINING_THE_TEMPLATE.md](docs/00_Core/MAINTAINING_THE_TEMPLATE.md) — how to keep the canonical template current.

**Agent mesh (Claude Code):** [CLAUDE.md](CLAUDE.md) § Orchestration gives the overview. **Cursor** users: the Task tool cannot use Claude Code agent names as `subagent_type`; use `generalPurpose` + `.claude/agents/*.md` checklists per [`.cursor/rules/cursor-task-delegation.mdc`](.cursor/rules/cursor-task-delegation.mdc). Key locations:

- **Routing table:** `.claude/agents/issue-driven-coding-orchestrator.md` § Routing
- **PR/bot loop:** `pr-resolution-follow-up` owns the `sleep 600` + GraphQL `reviewThreads` procedure (see `.claude/agents/pr-resolution-follow-up.md`)
- **Dependency/tooling PRs:** `dependency-review` fronts, then hands off to `pr-resolution-follow-up` (see `.claude/agents/dependency-review.md`)

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

## Persistent memory (two-tier)

| Tier | Location | Use |
|------|----------|-----|
| 1 | `AGENTS.md` (bottom) | Short operational facts, policy updates |
| 2 | `docs/01_Vault/AcCopilotTrainer/` (+ `docs/01_Vault/00_Graph_Schema.md`) | Linked graph: ADRs, invariants, glossary, investigations, session handoff |

Skill: `.claude/skills/vault-memory/SKILL.md` (mirrored under `.cursor/skills/`). Session protocol: `docs/00_Core/SESSION_LIFECYCLE.md`.

**Bootstrap (new copy of this template):** `.claude/skills/new-project-setup/SKILL.md` (mirrored under `.cursor/skills/`) — `/new-project-setup`.

---

## Local development

- **Install:** see `README.md` and `WARP.md`.
- **Checks:** `make ci-fast` (format, lint, tests, policy scripts).
- **Pre-commit:** `make hooks-install` once per clone.
- **Optional stacks:** DB, AWS, HF, Ollama, browser automation — [docs/00_Core/OPTIONAL_CAPABILITIES.md](docs/00_Core/OPTIONAL_CAPABILITIES.md).

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
- (process-miner) New learned rule file(s): details-summary-code-6d08d630.md, code-color-prefers-deae6990.md, details-summary-code-036397f8.md, code-copilot-instructions-95a635ed.md, code-summary-details-cf069955.md, codex-your-usage-4b2853cd.md, code-window-code-block-d78e9022.md, code-block-code-script-7676434f.md, code-this-comments-4f8a18eb.md, code-summary-details-bfa64abf.md, code-details-summary-ec81758f.md, code-that-alpha-c73bc368.md, code-sourcery-review-22bb2671.md, code-summary-details-58655b13.md, code-fallback-this-ee7626aa.md, code-summary-details-0178d5bf.md, code-segment-brake-83118140.md, details-summary-code-b4fdb928.md, code-missing-keys-a524e284.md, code-removing-consider-760f8187.md, speed-code-when-7e1de745.md, code-ranking-fastest-aaf0aedb.md, code-with-review-17e8d62d.md, code-summary-details-05f925ab.md, code-thanks-review-comment-addressed-77c881ec.md, code-callback-function-7cb5dcb0.md, code-details-summary-d1b4e45c.md, font-code-brand-0329a52e.md, code-this-consider-565ce7f5.md, current-code-speed-326b6027.md, code-textcolored-pull-c6d0e093.md, code-string-dash-848402d9.md, test-phases-phase-f65aca81.md, code-that-progress-878783fa.md, code-medium-being-54a1b4a1.md, code-reset-ac-copilot-trainer-c92cb325.md, push-function-code-f9806be1.md, code-coaching-logic-043bb05a.md, code-rules-debrief-3c1ec5c5.md, code-server-send-17e05ca3.md, code-call-redundant-87391ba9.md, code-flag-still-2ead46f9.md, heading-brake-nearby-83dbbc89.md
<!-- process-miner:learned:end -->


<!-- Append project-specific operational facts here after bootstrap. -->
<!-- Example: "Pipeline venv at .venv/bin/python", "Gmail expanded to N threads on DATE" -->

## Changelog (Tier 1)

<!-- CHANGELOG:START -->
- 2026-03-30: Bootstrap ac-copilot-trainer from template-repo; domain extension for Assetto Corsa + CSP Lua runtime.
- 2026-03-27: v1.4 — Vault knowledge graph (`00_Graph_Schema.md`, `invariants/`, `glossary/`), `SESSION_LIFECYCLE.md`, agent/hook lifecycle wiring, expanded policy checks + root file allowlist warnings, `check_bootstrap_complete.py`, bootstrap doc refresh.
- 2026-03-27: v1.3 — Agent cohesion: orchestrator owns canonical Routing table; pr-resolution-follow-up fixed loop numbering + exit/escalation + cross-links; dependency-review handoff to Task/pr-resolution; CLAUDE.md orchestration + skills table + delegation/context discipline; AGENTS.md agent mesh pointer.
- 2026-03-27: v1.2 — Multi-tool governance: TOOLCHAIN, OPTIONAL_CAPABILITIES, MAINTAINING_THE_TEMPLATE, GITHUB_SETUP; mandatory vault callout + maintainer link; CLAUDE.md quick start and Desktop/MCP/upstream-sync clarity; AGENT_CORE_PRINCIPLES child-vs-template upstream wording; README "keeping current"; Dependabot groups; gitignore `.claude.local.md`.
- 2026-03-26: v1.1 — Added issue-grouping-by-file-overlap, own-every-failure, preserve-manual-work, upstream-sync. (Source: court-fillings-processing learnings)
<!-- CHANGELOG:END -->
