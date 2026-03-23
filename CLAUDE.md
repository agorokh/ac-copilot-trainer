# CLAUDE.md

Guidance for **Claude Code** (claude.ai/code) in this repository.

**Status:** Template  
**Version:** 1.0  
**Category:** Core

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

---

## Orchestration

- **Issue-scoped delivery:** `.claude/agents/issue-driven-coding-orchestrator.md`
- **PR resolution loop (CI + bots):** `.claude/agents/pr-resolution-follow-up.md`

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
