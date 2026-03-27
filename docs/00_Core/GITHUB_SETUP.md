# GitHub setup (recommended)

Apply on the **template** repo and reuse as a checklist for important **child** repos.

## Template repository

Enable **Settings → General → Template repository** so others use **Use this template** ([docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository)).

CLI: `gh repo create my-app --template owner/template-repo` ([CLI manual](https://cli.github.com/manual/gh_repo_create)).

## Branch protection / rulesets

- Protect `main`: require PR, required status checks (**CI**, **Policy**), no force-push ([protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) or [rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)).

## Security features

- Enable **Dependabot alerts**, **secret scanning** where available ([repository best practices](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories)).
- Keep workflow `permissions:` minimal (already scoped in this template’s workflows).

## Dependabot noise

- Use **grouping** in `.github/dependabot.yml` (see current file), **weekly** schedule, and low `open-pull-requests-limit`.
- Tune with [Optimizing PR creation](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/optimizing-pr-creation-version-updates) when volume grows.

## Labels (optional)

Define a small set: `bug`, `enhancement`, `docs`, `chore`, `blocked`, `agent`. [Managing labels](https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/managing-labels).

## Custom Copilot agents

- Definitions in `.github/agents/*.agent.md` ([custom agents](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/create-custom-agents)).
- Keep prompts **short** and point to repo docs instead of duplicating policy.

## OAuth / `workflow` scope

Pushes that touch `.github/workflows/` need a token with **`workflow`** scope (e.g. `gh auth refresh -s workflow`).

## Claude Code: GitHub MCP

The repo ships **`.mcp.json`** with the **official** [GitHub MCP Server](https://github.com/github/github-mcp-server) via **Docker** (`docker run … ghcr.io/github/github-mcp-server`). The image reference is **unpinned**, matching upstream examples (Docker resolves to the current default tag). Pin by **digest** in a fork if your org requires immutable image refs. Set **`GITHUB_PERSONAL_ACCESS_TOKEN`** in your environment before starting Claude Code so the container receives it — never commit the token; see `.env.example` and [TOOLCHAIN.md](TOOLCHAIN.md). Skill **`.claude/skills/new-project-setup`** walks through bootstrap including this step.

**Deprecation note:** Do not use the npm package `@modelcontextprotocol/server-github` (deprecated as of April 2025 per upstream).

**Image updates:** Occasionally run `docker pull ghcr.io/github/github-mcp-server` (e.g. with your monthly template skim in [MAINTAINING_THE_TEMPLATE.md](MAINTAINING_THE_TEMPLATE.md)).

**No Docker:** Use GitHub’s documented **remote Streamable HTTP** or `claude mcp add-json` flow instead ([install guide](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-claude.md)).

**Fine-grained PAT (per repository):** grant the smallest set that matches what you will do — for typical Issues + PRs + repo file tools, that usually means **Contents** (read, or read/write if tools mutate files), **Issues**, and **Pull requests** (read/write as needed). Add **Metadata** (read) if the server requires it. **Classic PAT:** choose scopes that mirror the same surface area (e.g. `repo` vs narrower scopes).
