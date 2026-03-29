# Maintaining the canonical template

Use this when **`template-repo` itself** is the repo you are editing (not a child project).

## What “continuously up to date” means

GitHub **does not** push template changes into existing repos created earlier. The template is a **snapshot** at creation time. Staying current is a **process**:

1. **Merge improvements here first** — Any domain-agnostic workflow, hook, skill, or doc fix lands in `template-repo`.
2. **Child projects pull selectively** — Prefer **[Copier](https://copier.readthedocs.io/)** (`copier update`) for repos created with `copier copy` (see `copier.yml`, `docs/00_Core/BOOTSTRAP_NEW_PROJECT.md`). Alternatively use `git remote add template <url>` and `git cherry-pick` / manual file copy, or open tracking Issues in each product repo.
3. **Record governance deltas** — Add a dated bullet under [Changelog](#changelog) below (and optionally a one-liner in `PROVENANCE.md` when the narrative matters).

### Copier sync and tagging

- After meaningful governance changes, tag **`template-YYYY.MM`** (e.g. `template-2026.03`) so children can pin `--vcs-ref`.
- Child repos can copy `.github/workflows/template-sync.yml` from this template: scheduled / `workflow_dispatch` runs `copier update`, opens a PR labeled **`template-sync`**. Set repository variable **`TEMPLATE_REF`** (optional) for the default ref on schedule; override with the workflow input when dispatching.
- **`TEMPLATE_REPO` / source URL:** `copier update` uses `_src_path` stored in the child’s `.copier-answers.yml` from the original `copier copy`. Ensure that URL still points at this template (or a fork you control).

### Upstream feedback when child CI breaks

- Copy `.github/workflows/template-feedback.yml` into child repos that use template sync. It triggers on **`workflow_run`** for the workflow named **`CI`** (must match the child’s CI workflow `name:` exactly).
- Configure **`TEMPLATE_UPSTREAM_REPO`** (repository variable), e.g. `agorokh/template-repo`, as the **template** repository that should receive issues.
- Add secret **`TEMPLATE_REPO_TOKEN`**: a PAT or fine-grained token with **`issues: write`** on the **upstream template repo only** (minimal scope). Without it, the “file upstream issue” step skips. Never commit tokens; see `.env.example` for naming only.
- On the **template** repository, create the **feedback** label and the **template-sync** label once (Issues → Labels) so `gh issue create --label …` from the workflow succeeds.

### Cross-repo mining (optional)

- `.github/workflows/cross-repo-mining.yml` aggregates process-miner outputs across a comma-separated repo list (`CROSS_REPO_MINING_REPOS` variable or workflow input). **`GITHUB_TOKEN`** on the default repo is usually enough for **public** repos; **private** children need broader token scoping (open question — document org policy).

### Open questions

- GitHub App vs long-lived PAT for `TEMPLATE_REPO_TOKEN`.
- Whether monthly aggregation should run on this repo vs a dedicated meta-repo.
- Token scoping for private child repos in aggregation.

## Changelog

Template maintainers: append one bullet per governance-facing change.

- `YYYY-MM-DD` — Short description (optional PR link).
- 2026-03-29 — Template sync framework (#27): `copier.yml`, post-copy script, reference workflows (`template-sync`, `template-feedback`, `cross-repo-mining`), `tools/process_miner/aggregate.py`, docs + optional `[bootstrap]` extra (`copier`).
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

Optional: tag `template-YYYY.MM` after meaningful governance updates so child repos can reference “based on template-2026.03” and Copier can target that ref.
