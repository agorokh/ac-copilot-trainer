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
