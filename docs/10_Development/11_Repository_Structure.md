# Repository structure

**Status:** Template

## Allowed top-level paths (default)

These align with `scripts/check_agent_forbidden.py` for the unspecialized template:

| Path | Purpose |
|------|---------|
| `.github/` | Workflows, templates, GitHub agents |
| `.claude/` | Claude Code hooks, agents, skills, rules |
| `.cursor/` | Cursor rules, skills, Bugbot context |
| `docs/` | Human and agent documentation; vault under `docs/01_Vault/` |
| `src/` | Application code |
| `tests/` | Automated tests |
| `scripts/` | Checked-in automation |

Root files such as `README.md`, `Makefile`, `pyproject.toml`, and policy docs are expected.

When you add top-level directories (`apps/`, `ops/`, `data/`, etc.), update **both** this document and `ALLOWED_TOPLEVEL_DIRS` in `scripts/check_agent_forbidden.py`.
