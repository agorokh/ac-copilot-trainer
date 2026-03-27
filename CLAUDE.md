# CLAUDE.md

Guidance for **Claude Code** (claude.ai/code) in this repository.

**Status:** Template
**Version:** 1.3
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

See `.claude/skills/vault-memory/SKILL.md` for the full protocol.

- **Tier 1** — `AGENTS.md` (quick facts, changelog block at bottom).
- **Tier 2** — Obsidian vault: `docs/01_Vault/ProjectTemplate/` (rename on bootstrap).

**Session start:** read `Next Session Handoff.md`, then `Current Focus.md`, then `Project State.md` under `00_System/`.

**Session end:** update `Next Session Handoff.md` with resume instructions and open blockers.

@docs/01_Vault/ProjectTemplate/00_System/Project State.md
@docs/01_Vault/ProjectTemplate/00_System/Current Focus.md
@docs/01_Vault/ProjectTemplate/00_System/Next Session Handoff.md
@docs/01_Vault/ProjectTemplate/00_System/Architecture Invariants.md
@docs/01_Vault/ProjectTemplate/00_System/Workflow OS.md
@docs/01_Vault/ProjectTemplate/00_System/Library Map.md
@docs/01_Vault/ProjectTemplate/00_System/Glossary.md

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

**Routing (canonical table):** `.claude/agents/issue-driven-coding-orchestrator.md` § **Routing** — issue type → primary agent → handoff → skills. Other agent files link there so the graph stays in one place.

| Role | Agent file |
|------|------------|
| Issue → branch → Draft PR → implement → `make ci-fast` | `.claude/agents/issue-driven-coding-orchestrator.md` |
| Green CI + GraphQL `reviewThreads` + `sleep 600` | `.claude/agents/pr-resolution-follow-up.md` |
| Dependabot / workflows / `.mcp.json` risk + merge order | `.claude/agents/dependency-review.md` → then **pr-resolution-follow-up** for the bot loop |

**Delegation:** Where the host supports it, use the **Task** tool with `subagent_type` set to the agent name (e.g. `pr-resolution-follow-up`, `dependency-review`). Prose “invoke X” in agent markdown is the same contract. **`@agent` mentions** (if your UI supports them) force a focused run. Agents do not hard-link at load time—descriptions drive matching.

**Skills (when to load)** — see `.claude/skills/*/SKILL.md` (mirrored under `.cursor/skills/` where present).

| Skill | Use |
|-------|-----|
| `vault-memory` | Session start/end, handoffs, ADRs |
| `project-conventions` | Ambiguous style/workflow; pointers to `AGENTS.md` / protocol |
| `ci-check` | Diagnosing CI / local check failures |
| `github-issue-creator` | Creating issues from templates |
| `new-project-setup` | After **Use this template** |
| `release-notes` | Maintainer release blurbs (user-invoked) |

**Context discipline:** Issue/PR **JSON from `gh` first**; then open only the files the task names. **Link** canonical docs instead of pasting them. Use **Context7** for third-party library facts; use the **vault** for *this* product’s decisions.

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
