# template-repo

**Organization starter for issue-driven, agentic software development.** Copy this repository (or use GitHub **Use this template**) every time you spin up a new project so Cursor, Claude Code, Codex, and GitHub-native agents inherit the same workflow, memory model, and guardrails.

**GitHub:** [github.com/agorokh/template-repo](https://github.com/agorokh/template-repo) (private). After the first push from your machine, enable **Settings → General → Template repository** so new projects start from a clean copy ([GitHub: Creating a template repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository)).

## What you get

- **Canonical policy docs** enforced in CI: `AGENTS.md`, `CLAUDE.md`, `AGENT_CORE_PRINCIPLES.md`, `.cursorrules`
- **Two-tier memory**: durable bullets in `AGENTS.md` + **Obsidian vault** under `docs/01_Vault/ProjectTemplate/` (rename the folder to your project key on bootstrap)
- **Claude Code hooks** (`.claude/settings.json`): format-on-edit for Python, sensitive-file blocks, protected-branch bash checks, session-end reminders tied to the vault
- **Cursor rules** (`.cursor/rules/`) aligned with the same branch/PR/bot-review expectations
- **GitHub**: PR + issue templates, policy workflow, CI (`make ci-fast`), optional security scanning, Dependabot
- **Agent-proofing script** for top-level directory hygiene (customize allowlist for your layout)
- **MCP**: checked-in `.mcp.json` with Context7 (Claude Code–oriented); mirror to Claude Desktop if needed — see [docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md)
- **Multi-tool:** same workflow for **Cursor** and **Claude** (Code, Desktop chat, Cowork/Dispatch-style handoffs) — vault + `AGENTS.md` stay canonical

## First-time setup (after copying the template)

1. Read [docs/00_Core/BOOTSTRAP_NEW_PROJECT.md](docs/00_Core/BOOTSTRAP_NEW_PROJECT.md) and complete the checklist (rename vault folder, replace placeholders, set `pyproject` package name).
2. Create a virtualenv (recommended): `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`.
3. Run `make hooks-install` (pre-commit) and `make ci-fast` before the first PR.
4. **If this repository will be used as a template for other repos:** in GitHub, enable **Settings → General → Template repository** so teammates can use **Use this template** ([GitHub docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository)).

## Keeping the template (and children) current

Template repos do **not** auto-update downstream copies. See [docs/00_Core/MAINTAINING_THE_TEMPLATE.md](docs/00_Core/MAINTAINING_THE_TEMPLATE.md) for a lightweight cadence (Dependabot, periodic doc skim, child→template PRs). GitHub settings checklist: [docs/00_Core/GITHUB_SETUP.md](docs/00_Core/GITHUB_SETUP.md).

## Provenance

Patterns here were synthesized from internal projects that emphasized issue-driven delivery, vault-backed architecture memory, invariant hooks, and GitHub-centric review loops. See [docs/00_Core/PROVENANCE.md](docs/00_Core/PROVENANCE.md) for the source repository list and notes on what was generalized.

## License

Use and adapt internally as needed; set `LICENSE` when you publish a derived project.
