# Bootstrap a new project from this template

Complete these steps once per new repository.

## 1. Identity

- [ ] Choose a **project key** (short, filesystem-safe, e.g. `AcmePlatform`). You will rename the vault folder to match.
- [ ] Update `pyproject.toml`: `name`, `description`, and `[tool.setuptools.packages.find]` / package layout if you change `src/project_template`.
- [ ] Replace the Python package `src/project_template/` with your package name (or keep and rename in one commit).

## 2. Vault (Obsidian knowledge graph)

- [ ] Rename `docs/01_Vault/ProjectTemplate` → `docs/01_Vault/<YourProjectKey>`.
- [ ] Keep **`docs/01_Vault/00_Graph_Schema.md`** at vault **parent** level (it is intentionally outside the renamed folder).
- [ ] Global find-replace `ProjectTemplate` → `<YourProjectKey>` in:
  - `CLAUDE.md`
  - `docs/01_Vault/00_Graph_Schema.md` (especially `relates_to` entries such as `ProjectTemplate/00_System/...`)
  - `.claude/skills/vault-memory/SKILL.md` and `.cursor/skills/vault-memory/SKILL.md`
  - `.claude/rules/memory.md`, `.claude/rules/invariants.md`
  - `.claude/settings.json` (Stop / hook reminder paths)
  - `.cursor/rules/invariants.mdc`, `.cursor/BUGBOT.md`
  - `AGENTS.md`, `.cursorrules` (if they reference the old path)
  - **GitHub custom agents:** `.github/agents/issue-refiner.agent.md` — replace `docs/01_Vault/ProjectTemplate/...` with `docs/01_Vault/<YourProjectKey>/...` (see HTML comment in that file).
- [ ] **Restructure nodes** for your domain: add invariant nodes, glossary terms, and ADRs as small linked files; update `_index.md` files accordingly (see `00_Graph_Schema.md`).
- [ ] Update **`relates_to` / `part_of`** in vault YAML: replace the `ProjectTemplate/` prefix with `<YourProjectKey>/` in every anchored path (paths are relative to `docs/01_Vault/`; no `..` segments — see `00_Graph_Schema.md`).
- [ ] Open the vault in Obsidian (optional: tune `.obsidian/` plugins — keep REST API off unless you intend to use it).

## 3. Agent docs

- [ ] Edit `AGENTS.md` **Core Principles** and **Repository Layout** for your domain.
- [ ] Edit `AGENT_CORE_PRINCIPLES.md` **Architecture Overview** and **What NOT to Do** for your stack.
- [ ] Edit `docs/10_Development/10_Agent_Protocol.md` file-placement table and forbidden actions.
- [ ] Edit `docs/10_Development/11_Repository_Structure.md` and `scripts/check_agent_forbidden.py` `ALLOWED_TOPLEVEL_DIRS` (and root file allowlist if you add new top-level files).
- [ ] Optional: add `CODEX.md` / `WARP.md` project-specific sections.

## 4. Hooks, invariants, and lifecycle

- [ ] Replace template **invariant** stubs under `docs/01_Vault/<YourProjectKey>/00_System/invariants/` with your real rules (or add nodes); keep `invariants/_index.md` current.
- [ ] Adjust `.claude/settings.json` PreToolUse prompts if your code lives outside `src/` or you need different string guards (gateways, DDL location, etc.).
- [ ] If raw evidence or large data must never be agent-written, add a shell hook (see disclosures-style `block-data-edits.sh`) and wire it in `settings.json`.
- [ ] Read **`docs/00_Core/SESSION_LIFECYCLE.md`** and align team practice (LOAD → OPERATE → SAVE).

## 5. GitHub

- [ ] Set repository **Settings → Template repository** if this copy should be the next template.
- [ ] Update `.github/pull_request_template.md` and issue templates for your team.
- [ ] Replace `.github/agents/*.agent.md` with a real custom agent or delete if unused (avoid stale third-party names in prompts).

## 6. MCP and local LLMs

- [ ] Confirm `.mcp.json`: **Context7** (library docs) and **GitHub** MCP are present; set **`GITHUB_PERSONAL_ACCESS_TOKEN`** for Claude Code (see `.env.example`, [TOOLCHAIN.md](TOOLCHAIN.md), skill **`new-project-setup`**).
- [ ] Add database or browser servers only when the project needs them.
- [ ] Document API keys and local inference (Ollama, OpenRouter, HF caches) in `.env.example` and `WARP.md` / `CLAUDE.md` — never commit secrets.

## 7. Verify

```bash
make hooks-install
make ci-fast
```

**Manual bootstrap validation (not CI):** after renames and `pyproject` edits, run:

```bash
python3 scripts/check_bootstrap_complete.py
```

It warns if the vault folder, package directory, or `pyproject.toml` name still match template defaults. Intended for **local** use only. The script is **advisory**: it **always exits with code 0**; messages go to **stderr** when checks fail so you can use it in scripts without breaking pipelines.

## Post-bootstrap reading (agents and humans)

- [ ] [00_Graph_Schema.md](../01_Vault/00_Graph_Schema.md) — vault knowledge graph node schema and linking.
- [ ] [SESSION_LIFECYCLE.md](SESSION_LIFECYCLE.md) — mandatory session LOAD → OPERATE → SAVE protocol.
- [ ] [TOOLCHAIN.md](TOOLCHAIN.md) — Cursor, Claude Code, Desktop, MCP.

## Verification complete

Use this checklist before you call the repo “bootstrapped”:

- [ ] `docs/01_Vault/ProjectTemplate` renamed to your project key; `00_Graph_Schema.md` still at `docs/01_Vault/00_Graph_Schema.md`.
- [ ] `src/project_template/` renamed; imports and `pyproject.toml` package discovery updated.
- [ ] `[project].name` in `pyproject.toml` is not `project-template`.
- [ ] `python3 scripts/check_bootstrap_complete.py` prints no warnings.
- [ ] `.github/agents/issue-refiner.agent.md` (and any copied agent prompts) point at `docs/01_Vault/<YourProjectKey>/...`, not `ProjectTemplate`.
- [ ] `make ci-fast` passes; test PR confirms policy + CI workflows.
- [ ] Invariants and glossary indexes reflect your domain; new knowledge uses small linked nodes per `00_Graph_Schema.md`.

## See also

- [TOOLCHAIN.md](TOOLCHAIN.md) — Cursor, Claude Code, Desktop, MCP.
- [OPTIONAL_CAPABILITIES.md](OPTIONAL_CAPABILITIES.md) — DB, AWS, HF, Ollama, browser tooling.
- [GITHUB_SETUP.md](GITHUB_SETUP.md) — branch protection, Dependabot, Copilot agents.
