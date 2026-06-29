# Repository structure

**Status:** Template

## Allowed top-level paths (default)

These align with `scripts/check_agent_forbidden.py` for the unspecialized template:

| Path | Purpose |
|------|---------|
| `.github/` | Workflows, templates, GitHub agents |
| `.gemini/` | Gemini Code Assist repo review config (`config.yaml`, `styleguide.md`, `review_instructions.md`) |
| `.claude/` | Claude Code hooks, agents, skills, rules |
| `.cursor/` | Cursor rules, skills, Bugbot context |
| `docs/` | Human and agent documentation; vault under `docs/01_Vault/` |
| `ops/` | Workstation service catalog declaration (`ops/service.yaml`) consumed by [workstation-ops](https://github.com/agorokh/workstation-ops); see [BOOTSTRAP_NEW_PROJECT.md](../00_Core/BOOTSTRAP_NEW_PROJECT.md#workstation-service-catalog) |
| `reports/` | Optional generated or curated outputs (e.g. `process_miner/` markdown reports) — not secrets |
| `src/` | Application code |
| `tests/` | Automated tests |
| `scripts/` | Checked-in automation |
| `tools/` | Optional Python tooling (e.g. `process_miner`, `repo_knowledge`); extras `[mining]` / `[knowledge]` |
| `assets/` | Curated, version-controlled game-data assets — e.g. car setups at `assets/setups/<carID>/<track>/<name>.ini` registered into the data platform by `tools/setup_catalog`; the catalog index lives at `assets/setups/_catalog/registry.jsonl` |
| `.fleet-governance-vendor/` | Vendored inference-egress runtime (`runtime/inference_egress/`), SHA-256-pinned byte-identical to governance-hub; CI points `FLEET_GOVERNANCE_ROOT` here so this PUBLIC repo needs no private-hub checkout / `GH_PAT` for egress ([governance-hub#75](https://github.com/agorokh/governance-hub/issues/75)) |

When you add top-level directories (`apps/`, `data/`, etc.), update **both** this document and `ALLOWED_TOPLEVEL_DIRS` in `scripts/check_agent_forbidden.py`.

## Root-level files (allowlist warning)

`scripts/check_agent_forbidden.py` emits **warnings** (not CI failures) for tracked **root-level files** not in `ROOT_FILE_ALLOWLIST`. This catches accidental repo sprawl without blocking legitimate new files.

Default groups in code:

| Group | Examples |
|-------|----------|
| Config / build | `pyproject.toml`, `Makefile`, `.gitignore`, `.pre-commit-config.yaml`, `.secrets.baseline` |
| Governance / docs | `AGENTS.md`, `CLAUDE.md`, `AGENT_CORE_PRINCIPLES.md`, `.cursorrules`, `README.md`, `LICENSE` |
| Editor / toolchain | `.editorconfig`, `.python-version` |
| Template integration | `.mcp.json`, `.env.example`, `.markdownlint.json` |
| Review bot config | `.pr_agent.toml` (Qodo / PR-Agent), `.sourcery.yaml` (Sourcery) |

If you add a new tracked file at repository root, update **`ROOT_FILE_ALLOWLIST`** in `scripts/check_agent_forbidden.py` and add a row here so the next contributor knows it is intentional.

## Vault layout note

- **Graph schema:** `docs/01_Vault/00_Graph_Schema.md` (outside the renamed project vault folder).
- **Project vault:** `docs/01_Vault/<ProjectKey>/` (template: `ProjectTemplate/`).
- **Copier template:** root `copier.yml` plus `scripts/copier_post_copy.py` (see `BOOTSTRAP_NEW_PROJECT.md`).
