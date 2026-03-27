# WARP.md

Long-form **operator guide** for humans and agents (Warp terminal and others). Keep `README.md` short; put depth here.

## Project intent

_Describe what this software does after you specialize the template._

## Environment

- Python version: see `pyproject.toml` classifiers / CI.
- Create venv or use `uv` per team preference.
- Copy `.env.example` → `.env` for local secrets.

## Common commands

```bash
make ci-fast          # format, lint, tests, policy checks
make test             # pytest
make lint             # ruff check
make format           # ruff format
make hooks-install    # pre-commit install
```

## Layout

- Application code: `src/project_template/` (rename on bootstrap).
- Tests: `tests/`.
- Docs: `docs/`; durable architecture memory: `docs/01_Vault/ProjectTemplate/`.
- Automation: `scripts/`, `.github/workflows/`.

## Branching and memory

- Branch from `main`; open PRs early.
- **Tooling:** [docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md) (Cursor, Claude Code, Desktop, MCP).
- Update vault handoff notes when ending a session that will resume later.
- Optional: maintain a short tail in `CLAUDE.md` between `SESSION` markers for Claude Code; keep detailed narrative in archived session files under `docs/90_Archive/sessions/` if you use that pattern.

## Security and data

- No secrets in the repo; use secret managers in deployment.
- If the project handles PII or evidence files, document allowed paths and **agent write bans** in the vault invariants and enforce with hooks.

## Local ML / heavy dependencies

_If applicable: document HF cache dirs, GPU/MPS usage, air-gapped constraints._

## Troubleshooting

_Add project-specific debugging tips as you learn them._
