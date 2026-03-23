# Repository Guidelines

**This file guides all AI agents and human operators working in this repository.**

**Status:** Template — customize per project  
**Version:** 1.0  
**Category:** Core

---

## Mandatory reading

1. **[AGENT_CORE_PRINCIPLES.md](AGENT_CORE_PRINCIPLES.md)** — Non-negotiable workflow and hygiene.
2. **[docs/10_Development/10_Agent_Protocol.md](docs/10_Development/10_Agent_Protocol.md)** — Where files go and what is forbidden.
3. **Vault** — `docs/01_Vault/ProjectTemplate/00_System/` (rename `ProjectTemplate` on bootstrap; see [docs/00_Core/BOOTSTRAP_NEW_PROJECT.md](docs/00_Core/BOOTSTRAP_NEW_PROJECT.md)).

---

## Core principles (customize)

1. **Architecture-first** — Read existing modules and docs before adding parallel patterns.
2. **Issue-driven** — Default: GitHub Issue → branch → PR → review → merge.
3. **Single source of truth** — Prefer one obvious home for logic, config, and docs; link instead of duplicating.
4. **Observable changes** — Tests or scripted checks that prove behavior changed as intended.
5. **Security-first** — No secrets in repo; least privilege for tokens; document data sensitivity in the vault.

**Add domain-specific rules below** (service entry points, forbidden APIs, storage layout, etc.).

### Domain extension area

_Replace this subsection with your project’s real constraints (e.g. “all DB writes go through repository X”, “no writes under `data/raw/`”)._

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
| 2 | `docs/01_Vault/ProjectTemplate/` | ADRs, invariants, investigations, session handoff |

Skill: `.claude/skills/vault-memory/SKILL.md` (mirrored under `.cursor/skills/`).

---

## Local development

- **Install:** see `README.md` and `WARP.md`.
- **Checks:** `make ci-fast` (format, lint, tests, policy scripts).
- **Pre-commit:** `make hooks-install` once per clone.

---

## Learned facts (Tier 1 changelog)

<!-- CHANGELOG:START -->
<!-- Append concise bullets when durable behavior or policy changes. -->
<!-- CHANGELOG:END -->
