---
type: index
status: active
created: 2026-03-27
updated: 2026-03-27
relates_to:
  - ProjectTemplate/00_System/invariants/_index.md
  - ProjectTemplate/00_System/glossary/_index.md
---

# Vault knowledge graph schema

This file lives **outside** the `ProjectTemplate/` folder so it survives renaming the vault to a project-specific key.

**Path anchor for `relates_to` / `part_of`:** use paths relative to **`docs/01_Vault/`** (no `..` segments). Examples: `00_Graph_Schema.md` (this file), `ProjectTemplate/00_System/Next Session Handoff.md`. After bootstrap, replace `ProjectTemplate` with your project key in every anchored path.

Narrative docs below still describe the **project vault** as `docs/01_Vault/<ProjectKey>/` for human orientation.

## Node constraints

- **Single focus** — One concept, decision, entity, or investigation per file. Do not mix unrelated topics.
- **Size** — Target **under ~100 lines** of body text so a node fits comfortably within Claude Code-style injection limits (order-of **200 lines / ~25KB** per injected file). Split when a note grows.
- **Stable IDs** — Use descriptive filenames (`entrypoint.md`, `no-secrets.md`); rename rarely and update `relates_to` / `supersedes` when you do.

## Required frontmatter

Every graph node SHOULD include:

| Field | Description |
|-------|-------------|
| `type` | One of: `decision`, `entity`, `investigation`, `state`, `index`, `invariant`, `handoff`, `current-focus`, `project-state`, `workflow-os`, `library-map` |
| `status` | One of: `active`, `superseded`, `draft` |
| `created` | ISO date `YYYY-MM-DD` |
| `updated` | ISO date `YYYY-MM-DD` |

`index` is for directory summaries (`_index.md`) and thin entrypoints. **`invariant`** is for single architecture rules under `00_System/invariants/`. **`handoff`** / **`current-focus`** map to `Next Session Handoff.md` and `Current Focus.md`. Use **`entity`** for glossary terms and similar definitions. Tier-1 operational bullets stay in `AGENTS.md` per existing practice.

## Relationship frontmatter (optional)

| Field | Description |
|-------|-------------|
| `relates_to` | List of paths relative to **`docs/01_Vault/`**, e.g. `ProjectTemplate/00_System/invariants/no-secrets.md` |
| `supersedes` | Single path with the same anchor rules |
| `part_of` | Single path with the same anchor rules |

Do not use `..` in `relates_to` / `part_of`. Link to `docs/00_Core/*` and other areas **outside** `docs/01_Vault/` using normal Markdown in the body only, not as graph edges. Agents parse YAML frontmatter to build traversal edges.

## Linking convention

- Prefer **wikilinks or Markdown links** that match the same relative paths as `relates_to` where possible.
- **`_index.md`** in each curated directory lists child nodes and short summaries — start traversal there.

## Index nodes

Each directory that holds multiple graph nodes SHOULD include **`_index.md`**:

- Short purpose of the folder
- Bullet list of contained nodes with one-line summaries
- Key `relates_to` links outward (e.g. to sibling indexes or parent `part_of`)

## See also

- Session protocol: [SESSION_LIFECYCLE.md](../00_Core/SESSION_LIFECYCLE.md)
- Skill: `.claude/skills/vault-memory/SKILL.md`
