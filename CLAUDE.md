# CLAUDE.md

Guidance for **Claude Code** (claude.ai/code) in this repository.

**Status:** Template
**Version:** 1.4
**Category:** Core

---

## Quick start (copy-paste)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make ci-fast
```

Optional: `make hooks-install` once per clone. See [WARP.md](WARP.md) for operator detail.

---

## Tool surfaces (Cursor, Desktop, Code)

**Read [docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md)** — how Cursor, Claude Code, Claude Desktop (chat / team apps), and MCP configs relate. Repo `.mcp.json` is primarily for **Claude Code**; Desktop uses its own config file unless you mirror servers manually.

Personal overrides: root **`.claude.local.md`** (gitignored) for preferences not shared with the team.

---

## Persistent memory (two-tier)

See `.claude/skills/vault-memory/SKILL.md` and **`docs/00_Core/SESSION_LIFECYCLE.md`** for LOAD/SAVE.

- **Tier 1** — `AGENTS.md` (quick facts, changelog block at bottom).
- **Tier 2** — Obsidian vault graph: `docs/01_Vault/ProjectTemplate/` (rename on bootstrap); schema at `docs/01_Vault/00_Graph_Schema.md` (outside the renamed folder).

**Session start (LOAD):** `Next Session Handoff.md` → follow `relates_to` / `_index.md` for needed subgraph → `Current Focus.md` → `Project State.md` as needed.

**Session end (SAVE):** update `Next Session Handoff.md`; add or update **small linked nodes** (not only monolithic edits). See `SESSION_LIFECYCLE.md`.

@docs/00_Core/SESSION_LIFECYCLE.md
@docs/01_Vault/00_Graph_Schema.md
@docs/01_Vault/ProjectTemplate/00_System/Project State.md
@docs/01_Vault/ProjectTemplate/00_System/Current Focus.md
@docs/01_Vault/ProjectTemplate/00_System/Next Session Handoff.md
@docs/01_Vault/ProjectTemplate/00_System/Architecture Invariants.md
@docs/01_Vault/ProjectTemplate/00_System/invariants/_index.md
@docs/01_Vault/ProjectTemplate/00_System/Workflow OS.md
@docs/01_Vault/ProjectTemplate/00_System/Library Map.md
@docs/01_Vault/ProjectTemplate/00_System/Glossary.md
@docs/01_Vault/ProjectTemplate/00_System/glossary/_index.md

---

## Universal rules

All agents: **[AGENTS.md](AGENTS.md)** and **[AGENT_CORE_PRINCIPLES.md](AGENT_CORE_PRINCIPLES.md)**.

Operational detail: **[docs/10_Development/10_Agent_Protocol.md](docs/10_Development/10_Agent_Protocol.md)**.

### Key workflow reminders

1. **Issue first.** No significant work without a GitHub Issue.
2. **Group issues by files touched.** Never create separate issues for overlapping source files — consolidate with labeled Parts. See AGENT_CORE_PRINCIPLES.md.
3. **Own every failure.** Never blame the past. Fix it now.
4. **Preserve manual work.** Rebuilds must never delete user content. Verify guards first.
5. **Upstream sync.** If this repo is a **child project** spawned from the org template, propose propagating universal improvements back to the template (see [AGENT_CORE_PRINCIPLES.md](AGENT_CORE_PRINCIPLES.md) — *Upstream template sync*). If you are editing **the template repository itself**, merge changes here and note them in [docs/00_Core/MAINTAINING_THE_TEMPLATE.md](docs/00_Core/MAINTAINING_THE_TEMPLATE.md).

---

## Orchestration

Routing tables, agent roles, skills map, and delegation patterns live in **`.claude/rules/orchestration.md`** (loaded when working under `.claude/agents/` or agent docs). The canonical matrix remains **`.claude/agents/issue-driven-coding-orchestrator.md`**.

### Delegation (Cursor)

In **Cursor**, the **Task** tool only allows `subagent_type` values **`generalPurpose`**, **`explore`**, **`shell`**, and **`best-of-n-runner`**. Handoffs that name Claude Code agents (`pr-resolution-follow-up`, `dependency-review`, `learner`, etc.) should be executed by calling **`Task` with `generalPurpose`** and embedding the checklist from the linked **`.claude/agents/*.md`** file in the prompt, or by running those steps **inline** in the current session. Full detail: **`.cursor/rules/cursor-task-delegation.mdc`**.

---

## Hooks

Project hooks live in `.claude/settings.json`. They run on Edit/Write/Bash/Stop — do not bypass with unsafe workarounds.

---

## External docs vs vault

- Prefer **Context7** (see `.mcp.json` and `.claude/rules/context7.md`) for third-party library API facts.
- Prefer the **vault** for decisions and architecture that belong to this product.

---

## Local LLMs and API keys

Document provider endpoints, model names, and env vars in `.env.example` and `WARP.md`. Never commit real keys. For local inference (Ollama, HF, etc.), note cache directories and offline constraints here when relevant.

---

## Session log (optional short tail)

<!-- SESSION:START -->
<!-- Keep last ~3 timestamped lines; archive detail under docs/01_Vault/.../05_Sessions/ or docs/90_Archive/sessions/ -->
<!-- SESSION:END -->
