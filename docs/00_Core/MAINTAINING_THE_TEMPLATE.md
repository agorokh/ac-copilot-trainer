# Maintaining the canonical template

Use this when **`template-repo` itself** is the repo you are editing (not a child project).

## What “continuously up to date” means

GitHub **does not** push template changes into existing repos created earlier. The template is a **snapshot** at creation time. Staying current is a **process**:

1. **Merge improvements here first** — Any domain-agnostic workflow, hook, skill, or doc fix lands in `template-repo`.
2. **Child projects pull selectively** — Use `git remote add template <url>` and `git cherry-pick` / manual file copy for specific commits, or open tracking Issues in each product repo.
3. **Record governance deltas** — Add a dated bullet under [Changelog](#changelog) below (and optionally a one-liner in `PROVENANCE.md` when the narrative matters).

## Changelog

Template maintainers: append one bullet per governance-facing change.

- `YYYY-MM-DD` — Short description (optional PR link).
- 2026-03-28 — Agent self-learning infra (#15): digest-pinned GitHub MCP in `.mcp.json` + `.cursor/mcp.json`; `make ci-fast` adds coverage floor + bandit.
- 2026-03-27 — PR #3 follow-up: README template-setting gated; vault file links in OPTIONAL_CAPABILITIES; MAINTAINING changelog section; AGENT_CORE_PRINCIPLES MD049 emphasis.

## Cadence (lightweight)

| When | Do |
|------|-----|
| Weekly | Glance at Dependabot PRs; merge or batch. |
| Monthly | Skim Anthropic / Cursor / GitHub docs for breaking changes to MCP, hooks, or Copilot agents; adjust `.mcp.json` / `.cursor/mcp.json` / `.claude/settings.json` / `.github/agents` as needed. Run `docker pull ghcr.io/github/github-mcp-server` and refresh the **digest pin** in both MCP JSON files when bumping the GitHub MCP image. |
| Per real incident | Add an invariant or script check; promote to vault ADR if architectural. |

## Propagation rule (child → template)

When a **spawned project** discovers a universal improvement, it should flow **back** here via PR (see `AGENT_CORE_PRINCIPLES.md` — *Upstream template sync*). Avoid copying project-specific paths or secrets.

## Mirror discipline

- **Skills:** edit `.claude/skills/<name>/SKILL.md` then mirror to `.cursor/skills/<name>/SKILL.md` (or vice versa) so Cursor and Claude Code stay aligned.
- **Vault path:** global find-replace when renaming `ProjectTemplate` only during **new** project bootstrap — do not rename casually on the canonical template unless intentional.

## Versioning

Optional: tag `template-YYYY.MM` after meaningful governance updates so child repos can reference “based on template-2026.03”.
