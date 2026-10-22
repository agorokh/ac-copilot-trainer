---
paths:
  - "docs/01_Vault/**/*.md"
---

# Vault editing

When creating or editing vault markdown under `docs/01_Vault/`:

1. **Frontmatter** — Valid YAML per `docs/01_Vault/00_Graph_Schema.md` (`type`, `status`, `relates_to` / `part_of` as appropriate).
2. **Size** — Prefer **small files** (aim for under ~100 lines of body); split large narratives into linked nodes.
3. **Links** — A new node is reached through `relates_to` from an existing hub (a dated handoff node by its filename under `00_System/handoffs/`); do not edit an `_index.md` in a handoff (governance-hub#918).
4. **Paths** — `relates_to` / `part_of` use vault anchors from `docs/01_Vault/` (see graph schema); avoid broken relative links after bootstrap renames.
