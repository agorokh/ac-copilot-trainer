---
name: new-project-setup
description: Run after copying this template into a new repo — bootstrap identity, vault, agent docs, GitHub MCP token, hooks, and CI verification. Use when the user says new project, bootstrap, from template, or /new-project-setup.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Edit, Bash
---

# New project setup

Execute in order. Pause for human decisions where noted.

## 1. Identity and Python package

1. Pick a **project key** (short, filesystem-safe).
2. Update `pyproject.toml`: `name`, `description`, package layout.
3. Rename `src/ac_copilot_trainer/` → your package name (or keep and align imports).

## 2. Vault (Obsidian)

Follow **`docs/00_Core/BOOTSTRAP_NEW_PROJECT.md`** §2: rename `docs/01_Vault/AcCopilotTrainer`, global replace `AcCopilotTrainer` in the listed files.

## 3. Agent docs and repo layout

Follow **BOOTSTRAP_NEW_PROJECT.md** §3–4: `AGENTS.md`, `AGENT_CORE_PRINCIPLES.md`, `docs/10_Development/*`, `check_agent_forbidden.py`, invariants.

## 4. GitHub (repository settings)

Follow **`docs/00_Core/GITHUB_SETUP.md`**: template flag (if applicable), branch protection, Dependabot, labels, Copilot agents, `workflow` OAuth scope when editing Actions.

## 5. Claude Code — GitHub MCP

Repo **`.mcp.json`** runs the **official GitHub MCP Server** via **Docker** (`ghcr.io/github/github-mcp-server`). The deprecated npm package `@modelcontextprotocol/server-github` is **not** used. See GitHub’s [Install in Claude applications](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-claude.md).

**Prerequisites:** Docker installed and running (for the checked-in config). **No Docker?** Use the same doc’s **remote Streamable HTTP** option (`claude mcp add-json` with the PAT in the `Authorization` header) or another host-specific setup — do not commit tokens.

1. Create a token in **GitHub → Settings → Developer settings** (minimal scopes for your workflow — see `docs/00_Core/GITHUB_SETUP.md`).
2. Export before starting Claude Code so the container receives the variable:

   ```bash
   export GITHUB_PERSONAL_ACCESS_TOKEN="<your-token>"   # classic or fine-grained PAT; never commit
   ```

3. Periodically refresh the image (e.g. monthly): `docker pull ghcr.io/github/github-mcp-server`.
4. Verify **Context7** answers a simple library-docs query (e.g. in `/mcp` or your host’s MCP panel); add DB/browser MCP only if needed (**`docs/00_Core/OPTIONAL_CAPABILITIES.md`**).

Details: **`docs/00_Core/TOOLCHAIN.md`** and **`.env.example`**.

## 6. Workstation service catalog

Follow [`docs/00_Core/BOOTSTRAP_NEW_PROJECT.md#workstation-service-catalog`](../../../docs/00_Core/BOOTSTRAP_NEW_PROJECT.md#workstation-service-catalog) — that section is the canonical contract (rules, schema, registration). Operationally for this skill: prompt the user — "Does this project expose any long-lived services on the local workstation (launchd, Docker, brew services, process-compose)?" — and follow the linked section either way (a "no" answer still commits `ops/service.yaml` with `services: []`).

## 7. Hooks and verify

```bash
make hooks-install
make ci-fast
```

Open a test PR to confirm **CI**, **Policy**, and **Security** workflows.

## Optional (from automation review)

- **`project-conventions` skill:** add a Claude-only skill that references `AGENTS.md` + ruff defaults if the team wants a consolidated conventions reference.
- **PostToolUse `pre-commit`:** extend `.claude/settings.json` to run `pre-commit run --files <path>` on edited non-Python files if policy failures are common — keep timeouts reasonable.
