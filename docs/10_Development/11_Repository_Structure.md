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

When you add top-level directories (`apps/`, `ops/`, `data/`, etc.), update **both** this document and `ALLOWED_TOPLEVEL_DIRS` in `scripts/check_agent_forbidden.py`.

## Root-level files (allowlist warning)

`scripts/check_agent_forbidden.py` emits **warnings** (not CI failures) for tracked **root-level files** not in `ROOT_FILE_ALLOWLIST`. This catches accidental repo sprawl without blocking legitimate new files.

Default groups in code:

| Group | Examples |
|-------|----------|
| Config / build | `pyproject.toml`, `Makefile`, `.gitignore`, `.pre-commit-config.yaml` |
| Governance / docs | `AGENTS.md`, `CLAUDE.md`, `CODEX.md`, `WARP.md`, `AGENT_CORE_PRINCIPLES.md`, `.cursorrules`, `README.md`, `LICENSE` |
| Editor / toolchain | `.editorconfig`, `.python-version` |
| Template integration | `.mcp.json`, `.env.example`, `.markdownlint.json` |

If you add a new tracked file at repository root, update **`ROOT_FILE_ALLOWLIST`** in `scripts/check_agent_forbidden.py` and add a row here so the next contributor knows it is intentional.

## Vault layout note

- **Graph schema:** `docs/01_Vault/00_Graph_Schema.md` (outside the renamed project vault folder).
- **Project vault:** `docs/01_Vault/<ProjectKey>/` (template: `ProjectTemplate/`).
