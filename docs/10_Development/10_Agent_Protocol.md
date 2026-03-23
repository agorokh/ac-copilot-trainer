# Agent Behavior Protocol

**Status:** Template  
**Version:** 1.0  
**Category:** Development

---

## Goals

- **Predictable structure** — agents and humans know where files belong.
- **Issue-driven delivery** — scope is anchored in tracked work.
- **Reviewable changes** — small PRs, CI green, bot threads addressed.
- **Durable memory** — vault + `AGENTS.md`, not one-off root markdown dumps.

---

## File placement

| Need | Location | Notes |
|------|----------|-------|
| Application code | `src/project_template/` | Rename package on bootstrap |
| Tests | `tests/` | Mirror package structure |
| Long-form docs | `docs/` | Follow numbering convention if you adopt one |
| Architecture memory | `docs/01_Vault/ProjectTemplate/` | Obsidian vault |
| One-off experiments | `.scratch/` | Gitignored |
| Automation | `scripts/` | Review before adding — prefer modules |
| CI | `.github/workflows/` | Keep fast paths for docs-only PRs if needed |

Customize this table when you specialize the repository.

---

## Forbidden actions

- Creating random **top-level directories** without updating `scripts/check_agent_forbidden.py` and this doc together.
- Committing **secrets** or production `.env`.
- **Direct commits to `main`** (use PRs).
- Leaving **failing CI** without explanation when handing off to another agent.
- Storing large generated artifacts in git unless explicitly part of your artifact policy.

---

## Session hygiene

- Update vault **`Next Session Handoff.md`** when context will be needed later.
- Prefer linking Issues/PRs in handoff notes.

---

## References

- [11_Repository_Structure.md](11_Repository_Structure.md)
- [../00_Core/BOOTSTRAP_NEW_PROJECT.md](../00_Core/BOOTSTRAP_NEW_PROJECT.md)
