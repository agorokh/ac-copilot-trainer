# Bootstrap a new project from this template

Complete these steps once per new repository.

## 1. Identity

- [ ] Choose a **project key** (short, filesystem-safe, e.g. `AcmePlatform`). You will rename the vault folder to match.
- [ ] Update `pyproject.toml`: `name`, `description`, and `[tool.setuptools.packages.find]` / package layout if you change `src/project_template`.
- [ ] Replace the Python package `src/project_template/` with your package name (or keep and rename in one commit).

## 2. Vault (Obsidian)

- [ ] Rename `docs/01_Vault/ProjectTemplate` → `docs/01_Vault/<YourProjectKey>`.
- [ ] Global find-replace `ProjectTemplate` → `<YourProjectKey>` in:
  - `CLAUDE.md`
  - `.claude/skills/vault-memory/SKILL.md` and `.cursor/skills/vault-memory/SKILL.md`
  - `.claude/rules/memory.md`, `.claude/settings.json` (Stop / commit reminder paths)
- [ ] Open the vault in Obsidian (optional: tune `.obsidian/` plugins — keep REST API off unless you intend to use it).

## 3. Agent docs

- [ ] Edit `AGENTS.md` **Core Principles** and **Repository Layout** for your domain.
- [ ] Edit `AGENT_CORE_PRINCIPLES.md` **Architecture Overview** and **What NOT to Do** for your stack.
- [ ] Edit `docs/10_Development/10_Agent_Protocol.md` file-placement table and forbidden actions.
- [ ] Edit `docs/10_Development/11_Repository_Structure.md` and `scripts/check_agent_forbidden.py` `ALLOWED_TOPLEVEL_DIRS`.
- [ ] Optional: add `CODEX.md` / `WARP.md` project-specific sections.

## 4. Hooks and invariants

- [ ] Fill `docs/01_Vault/<YourProjectKey>/00_System/Architecture Invariants.md` with real rules.
- [ ] Adjust `.claude/settings.json` PreToolUse prompts if your code lives outside `src/` or you need different string guards (gateways, DDL location, etc.).
- [ ] If raw evidence or large data must never be agent-written, add a shell hook (see disclosures-style `block-data-edits.sh`) and wire it in `settings.json`.

## 5. GitHub

- [ ] Set repository **Settings → Template repository** if this copy should be the next template.
- [ ] Update `.github/pull_request_template.md` and issue templates for your team.
- [ ] Replace `.github/agents/*.agent.md` with a real custom agent or delete if unused (avoid stale third-party names in prompts).

## 6. MCP and local LLMs

- [ ] Edit `.mcp.json`: add database or browser servers as needed; keep Context7 for library docs.
- [ ] Document API keys and local inference (Ollama, OpenRouter, HF caches) in `.env.example` and `WARP.md` / `CLAUDE.md` — never commit secrets.

## 7. Verify

```bash
make hooks-install
make ci-fast
```

Open a test PR to confirm policy + CI workflows pass.

## See also

- [TOOLCHAIN.md](TOOLCHAIN.md) — Cursor, Claude Code, Desktop, MCP.
- [OPTIONAL_CAPABILITIES.md](OPTIONAL_CAPABILITIES.md) — DB, AWS, HF, Ollama, browser tooling.
- [GITHUB_SETUP.md](GITHUB_SETUP.md) — branch protection, Dependabot, Copilot agents.
