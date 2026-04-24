---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: reliability
scope_paths:
  - "docs/01_Vault/**"
  - "docs/00_Core/**"
  - ".claude/**"
  - "scripts/copier*"
  - "scripts/bootstrap*"
domains: [infra, trading, legal, gaming]
canonical_prs:
  - repo: agorokh/template-repo
    prs: [69, 66]
    note: Canonical vault paths not used in LOAD steps causing ambiguous file resolution
  - repo: agorokh/template-repo
    prs: [76]
    note: Bootstrap find-replace omits Graph Schema frontmatter containing AcCopilotTrainer
relates_to:
  - AcCopilotTrainer/00_System/invariants/persistence.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# Vault path integrity

**6 clusters, 73 comments, 2 repos** (template-repo, ac-copilot-trainer)

## Pattern

Vault wikilinks, `relates_to` frontmatter, and file references break after renames, bootstrap, or directory moves. The implementing agent creates or moves vault nodes without grep-checking all references, leaving dangling links that break traversal and confuse session LOAD.

Most common forms:
- `relates_to` paths still reference `AcCopilotTrainer/` after bootstrap renamed to project key
- `_index.md` not updated when new nodes are added to a directory
- Markdown links use title-only references instead of explicit file paths
- Bootstrap `find-replace` misses files outside the main vault directory (e.g., Graph Schema)

## Preventive rule

When touching vault nodes or docs:
1. **Grep for all references** to the file being modified: `grep -r "filename" docs/`
2. **Update `relates_to`** in frontmatter of all files that link to the changed file
3. **Update `_index.md`** entries in the parent directory
4. **Use full relative paths** from `docs/01_Vault/` in all `relates_to` fields, never title-only
5. **After bootstrap/rename:** run `grep -r "AcCopilotTrainer" docs/` to find missed replacements

## Canonical damage

In `template-repo` PR #76, the bootstrap `find-replace` list excluded `docs/01_Vault/00_Graph_Schema.md`, which contains `AcCopilotTrainer` in its `relates_to` examples. Child repos bootstrapped from this version had broken graph schema references until manually patched.
