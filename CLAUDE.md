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
make init-knowledge   # local SQLite for repo-knowledge MCP (idempotent)
make ci-fast
```

Optional: `make hooks-install` once per clone. See `AGENTS.md` § Local development for operator detail.

---

## Tool surfaces (Cursor, Desktop, Code)

**Read [docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md)** — how Cursor, Claude Code, Claude Desktop (chat / team apps), and MCP configs relate. Repo `.mcp.json` is primarily for **Claude Code**; Desktop uses its own config file unless you mirror servers manually.

Personal overrides: root **`.claude.local.md`** (gitignored) for preferences not shared with the team.

---

## Persistent memory (two-tier)

See `~/~/.agents/skills/vault-memory/SKILL.md` and **`docs/00_Core/SESSION_LIFECYCLE.md`** for LOAD/SAVE.

- **Tier 1** — `AGENTS.md` (quick facts, changelog block at bottom).
- **Tier 2** — Obsidian vault graph: `docs/01_Vault/AcCopilotTrainer/` (rename on bootstrap); schema at `docs/01_Vault/00_Graph_Schema.md` (outside the renamed folder).

**Session start (LOAD):** `Next Session Handoff.md` → follow `relates_to` / `_index.md` for needed subgraph → `Current Focus.md` → `Project State.md` as needed.

**Session end (SAVE):** update `Next Session Handoff.md`; add or update **small linked nodes** (not only monolithic edits). See `SESSION_LIFECYCLE.md`.

### Memory architecture (three tiers, no side channels)

Persistent memory in this project lives in **exactly one** of three tiers — write to the right one, **read all three**:

| Tier | Substrate | Write | Read |
|---|---|---|---|
| **1** | `AGENTS.md` (operational facts + changelog) | Direct `Edit` for short facts (versions, ports, learned preferences) | Auto-loaded at session start |
| **2** | Vault at `docs/01_Vault/AcCopilotTrainer/` (rename on bootstrap) — Obsidian markdown graph per [`docs/01_Vault/00_Graph_Schema.md`](docs/01_Vault/00_Graph_Schema.md) | Direct `Write` of small linked nodes (decisions, investigations, invariants, glossary, handoffs) | `@`-included by this `CLAUDE.md`; indirectly via Tier-3 query |
| **3** | Per-workspace semantic substrate declared in [`ops/memory_manifest.yml`](ops/memory_manifest.yml). **Canonical backend: LightRAG (online).** Graphiti retained for offline entity-resolution + bi-temporal metadata only — see the [Graphiti sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md) maintained in agent-factory. Substrate detail: [`docs/00_Core/MEMORY_SUBSTRATE.md`](docs/00_Core/MEMORY_SUBSTRATE.md). | **Indirect** — built by re-ingesting Tier-2; agents do not write directly | `mcp__agentic-memory__query_knowledge_graph(prompt, workspace=…)`. **Read at LOAD is mandatory** for substantive sessions and is enforced by `scripts/hook_memory_gate.py`. |

**Side channels are forbidden.** The Claude Code per-user auto-memory directory (`~/.claude/projects/.../memory/`) is **deprecated for this project** — `scripts/hook_session_start_memory_redirect.py` writes a deprecation marker there on every SessionStart so an agent that tries to write sees the warning. Scratch databases, per-user notes, ad-hoc files outside the three tiers — same: invisible to other agents, other sessions, teammates, and the Tier-3 ingest pipelines.

Canonical invariant: [`docs/01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md`](docs/01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md). Full contract: [`docs/00_Core/MEMORY_CONTRACT.md`](docs/00_Core/MEMORY_CONTRACT.md). Postmortem driving this rule: [issue #115](https://github.com/agorokh/template-repo/issues/115).

@docs/00_Core/MEMORY_CONTRACT.md
@docs/00_Core/SESSION_LIFECYCLE.md
@docs/01_Vault/00_Graph_Schema.md
@docs/01_Vault/AcCopilotTrainer/00_System/Project State.md
@docs/01_Vault/AcCopilotTrainer/00_System/Current Focus.md
@docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md
@docs/01_Vault/AcCopilotTrainer/00_System/Architecture Invariants.md
@docs/01_Vault/AcCopilotTrainer/00_System/invariants/_index.md
@docs/01_Vault/AcCopilotTrainer/00_System/Workflow OS.md
@docs/01_Vault/AcCopilotTrainer/00_System/Library Map.md
@docs/01_Vault/AcCopilotTrainer/00_System/Glossary.md
@docs/01_Vault/AcCopilotTrainer/00_System/glossary/_index.md

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

Routing tables, agent roles, skills map, and delegation patterns live in **`.claude/rules/orchestration.md`** (loaded when working under `.claude/agents/` or agent docs). The canonical matrix remains **`~/~/.agents/skills/orchestrate/SKILL.md`**.

### Delegation (Cursor)

In **Cursor**, the **Task** tool only allows `subagent_type` values **`generalPurpose`**, **`explore`**, **`shell`**, and **`best-of-n-runner`**. Handoffs that name Claude Code agents (`/resolve-pr`, `dependency-review`, `learner`, etc.) should be executed by calling **`Task` with `generalPurpose`** and embedding the checklist from the linked **`.claude/agents/*.md`** file in the prompt, or by running those steps **inline** in the current session. Full detail: **`.cursor/rules/cursor-task-delegation.mdc`**.

---

## Hooks

Project hooks live in `.claude/settings.json`. They run on Edit/Write/Bash/Stop — do not bypass with unsafe workarounds.

---

## External docs vs vault

- Prefer **Context7** (see `.mcp.json` and `.claude/rules/context7.md`) for third-party library API facts.
- Prefer the **vault** for decisions and architecture that belong to this product.

---

## Local LLMs and API keys

Document provider endpoints, model names, and env vars in `.env.example` and `AGENTS.md` § Local development. Never commit real keys. For local inference (Ollama, HF, etc.), note cache directories and offline constraints here when relevant.

---

## Session log (optional short tail)

<!-- SESSION:START -->
<!-- Keep last ~3 timestamped lines; archive detail under docs/01_Vault/.../05_Sessions/ or docs/90_Archive/sessions/ -->
<!-- SESSION:END -->

<!-- BEGIN MEMORY KICKOFF (rendered by tools/render_repo_memory_kickoff.py) -->

## Tier-3 memory contract (auto-generated)

**Canonical workspace:** `ac_copilot`  
**Backend:** `lightrag`  
**Endpoint (local on `mac-mini-dev`):** `http://localhost:8045`  
**From a non-central host (M5 / remote):** set `AGENTIC_MEMORY_BRIDGE_HOST=mac-mini-dev` in your agent environment so loopback endpoints in `~/.config/agentic-memory/fleet_registry.toml` rewrite to the Tailscale name. See [`agent-factory/docs/00_Core/HOSTS.md`](https://github.com/agorokh/agent-factory/blob/main/docs/00_Core/HOSTS.md).

**Query before any code edit:**

```python
mcp__agentic-memory__query_knowledge_graph(
    prompt="Assetto Corsa copilot training pipeline",
    workspace="ac_copilot",
)
```

The SessionStart hook in this repo runs `scripts/hook_session_start_memory_prefetch.py` (stdlib-only when PyYAML is absent) and stamps `.scratch/.last_memory_query` so the PreToolUse `hook_memory_gate.py` allows code edits. If the substrate is unreachable, write a one-line bypass rationale to `.scratch/.memory_bypass_rationale` — the gate logs the bypass instead of silently passing.

**Do not** write to `~/.claude/projects/.../memory/`, do not create new workspaces without a manifest row, do not edit `~/Library/LaunchAgents/ai.lightrag.*.plist` by hand. See [`agent-factory/docs/00_Core/ANTI_PATTERNS.md`](https://github.com/agorokh/agent-factory/blob/main/docs/00_Core/ANTI_PATTERNS.md).

Re-render this block: `python3 ~/Projects/agent-factory/tools/render_repo_memory_kickoff.py --repo-root . --apply`

<!-- END MEMORY KICKOFF -->
