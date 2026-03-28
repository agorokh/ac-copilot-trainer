---
name: vault-memory
description: Manage persistent memory for this repo — Obsidian vault at docs/01_Vault/ProjectTemplate/ plus AGENTS.md tier-1 facts. Use when starting/ending sessions, after architecture changes, investigations, or when the user says vault, handoff, ADR, or project state.
allowed-tools: Read, Grep, Glob, Write, Edit
---

# Vault Memory

**Governing schema:** [`docs/01_Vault/00_Graph_Schema.md`](../../../docs/01_Vault/00_Graph_Schema.md) — node types, frontmatter, `relates_to`, and `_index.md` conventions (survives vault folder rename).

Two-tier model:

| Tier | Location | Purpose |
|------|----------|---------|
| 1 | `AGENTS.md` | Short operational facts |
| 2 | `docs/01_Vault/ProjectTemplate/` | Structured graph of markdown nodes |

Rename `ProjectTemplate` during project bootstrap (see `docs/00_Core/BOOTSTRAP_NEW_PROJECT.md`).

## Graph traversal

When loading context:

1. Open **`docs/01_Vault/ProjectTemplate/00_System/Next Session Handoff.md`** (after bootstrap, replace `ProjectTemplate` with your vault folder name).
2. Start from **`_index.md`** files under `00_System/` (`invariants/`, `glossary/`, etc.) and follow **`relates_to`** in YAML frontmatter to pull in only the subgraph you need.
3. Open **`docs/01_Vault/ProjectTemplate/00_System/Current Focus.md`**.
4. Prefer the thin entry **`Architecture Invariants.md`** → **`invariants/_index.md`** over loading every invariant unless the task requires it.

Agents should parse frontmatter (or read indexes) to build traversal paths. **`relates_to` / `part_of`** use the `docs/01_Vault/` anchor (no `..`); see `00_Graph_Schema.md`.

## Bounded loading

- Prefer **3–5 focused nodes** over one large file or whole-directory slurp.
- Use frontmatter **`type`** to filter (see `00_Graph_Schema.md`: e.g. `index`, `invariant`, `handoff`, `current-focus`, `entity`, `decision`, …).
- Target **&lt; ~100 lines** per node body; split if a note grows.

## Session start (LOAD)

Align with **`docs/00_Core/SESSION_LIFECYCLE.md`**: handoff → linked subgraph → current focus → relevant invariant nodes for the active area.

## Session end (SAVE)

Update **`Next Session Handoff.md`** with resume instructions, delivered work, remaining work, blockers.

Update **`Current Focus.md`** if the active branch, PR, or focus changed.

When recording learnings, **prefer new small nodes** with `relates_to` / `part_of` links instead of appending long sections to existing files. Promote drafts from **`.scratch/`** into the vault when stable.

## When to add an ADR

Use `99_Templates/Decision.md` in `01_Decisions/` when a design choice has alternatives and long-term consequences.

## When to add an investigation note

Use `99_Templates/Investigation.md` in `06_Investigations/` after non-trivial debugging or incident response.

---

Keep this file aligned with `.claude/skills/vault-memory/SKILL.md` when editing.
