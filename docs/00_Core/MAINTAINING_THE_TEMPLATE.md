# Maintaining the canonical template

Use this when **`template-repo` itself** is the repo you are editing (not a child project).

## Fleet registry and propagation

- **Known children:** [CHILD_REPOS.md](CHILD_REPOS.md) — tier, Copier status, notes (quarterly review).
- **How to push changes safely:** [PROPAGATION_STRATEGY.md](PROPAGATION_STRATEGY.md) — especially `.claude/settings.json` via `settings.base.json` + `settings.local.json` and `make merge-settings`.
- **Scripts index:** [scripts/INVENTORY.md](../../scripts/INVENTORY.md).

### Claude settings merge (template canonical)

- Edit **hooks** in `.claude/settings.base.json` (tracked). Per-machine overlays live in `.claude/settings.local.json` (gitignored here; children may choose to track it).
- Regenerate **`.claude/settings.json`** with `make merge-settings` (merges local overlay when present).
- When committing **only** template output (no local overlay), run `python3 scripts/merge_settings.py --no-local` so generated `settings.json` matches `base` exactly.
- **`copier.yml`** lists `.claude/settings.json` under `_skip_if_exists` so Copier never overwrites the generated file.

### Quarterly review cadence

1. Update [CHILD_REPOS.md](CHILD_REPOS.md) for new or archived repos.
2. Skim [PROPAGATION_STRATEGY.md](PROPAGATION_STRATEGY.md) execution order + tier checklists after major template PRs.
3. Tag **`template-YYYY.MM`** after governance-facing changes (see below).

### Template release tags

After meaningful workflow, hook, or policy changes, tag **`template-YYYY.MM`** (e.g. `template-2026.04`) so children can pin `--vcs-ref` and document “based on template-2026.04”.

### Reverse flow (child → template)

When a child finds a **domain-agnostic** improvement, open a PR here first (see `AGENT_CORE_PRINCIPLES.md` — *Upstream template sync*). Do not copy product-specific paths, secrets, or proprietary prompts. Tier **B** children (e.g. Alpaca_trading) may contribute **richer** hooks via this path before you forward-port template-only changes manually.

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
- 2026-04-23 — Deterministic flow-control hooks (#91): removed the `PostToolUse:Bash` PASS prompt hook (was halting continuation on every successful bash call and silently aborting the issue-driven-coding-orchestrator in child repos). Replaced `PreToolUse:Bash` protected-branch and `PreToolUse:Edit|Write` sensitive-file-guard prompt hooks with `type: "command"` hooks backed by `scripts/hook_protect_main.sh` and `scripts/hook_sensitive_file_guard.sh`. Added `tests/test_hook_scripts.py` smoke tests and `docs/00_Core/HOOK_DESIGN.md` convention so this class of bug fails at CI instead of silently in children. Child propagation: next `copier update` plus rerun of `scripts/merge_settings.py` — inspect no prompt hooks remain on `PostToolUse:Bash` or `PreToolUse:Bash`.
- 2026-04-20 — Post-merge steward made deterministic: `scripts/post_merge_sync.sh` split into `sync` / `vault` phases with explicit exit-code contract; agent never pushes to `main` directly — vault SAVE goes through `vault/post-merge-pr<N>` branch + `vault-only` label + `.github/workflows/vault-automerge.yml`. WIP is auto-stashed under named ref. Propagate to children via `copier update` (next `template-YYYY.MM` tag); requires `vault-only` label to exist in each child repo (one-time `gh label create vault-only --description "post-merge handoff PR; auto-merged by bot"`).
- 2026-04-03 — Child repo registry, propagation strategy, `settings.base.json` + `merge_settings.py`, `scripts/INVENTORY.md`, Copier skip for generated `settings.json` (#40).
- 2026-03-29 — Template sync framework (#27): `copier.yml`, post-copy script, reference workflows (`template-sync`, `template-feedback`, `cross-repo-mining`), `tools/process_miner/aggregate.py`, docs + optional `[bootstrap]` extra (`copier`).
- 2026-03-28 — Agent self-learning infra (#15): digest-pinned GitHub MCP in `.mcp.json` + `.cursor/mcp.json`; `make ci-fast` adds coverage floor + bandit.
- 2026-03-27 — PR #3 follow-up: README template-setting gated; vault file links in OPTIONAL_CAPABILITIES; MAINTAINING changelog section; AGENT_CORE_PRINCIPLES MD049 emphasis.

## Cadence (lightweight)

| When | Do |
|------|-----|
| Weekly | Glance at Dependabot PRs; merge or batch. |
| Monthly | Skim Anthropic / Cursor / GitHub docs for breaking changes to MCP, hooks, or Copilot agents; adjust `.mcp.json` / `.cursor/mcp.json` / `.claude/settings.base.json` then run `make merge-settings` (or `merge_settings.py --no-local` for committed output) / `.github/agents` as needed. Run `docker pull ghcr.io/github/github-mcp-server` and refresh the **digest pin** in both MCP JSON files when bumping the GitHub MCP image. |
| Per real incident | Add an invariant or script check; promote to vault ADR if architectural. |

## Propagation rule (child → template)

When a **spawned project** discovers a universal improvement, it should flow **back** here via PR (see `AGENT_CORE_PRINCIPLES.md` — *Upstream template sync*). Avoid copying project-specific paths or secrets.

## Mirror discipline

- **Skills:** edit `.claude/skills/<name>/SKILL.md` then mirror to `.cursor/skills/<name>/SKILL.md` (or vice versa) so Cursor and Claude Code stay aligned.
- **Vault path:** global find-replace when renaming `AcCopilotTrainer` only during **new** project bootstrap — do not rename casually on the canonical template unless intentional.

## Versioning

Optional: tag `template-YYYY.MM` after meaningful governance updates so child repos can reference “based on template-2026.03” and Copier can target that ref.
