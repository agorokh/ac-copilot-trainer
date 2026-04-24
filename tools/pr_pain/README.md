# `tools/pr_pain` — PR pain detection → process-learning backlog

After a PR merges, this module scores how much *iteration* it required and,
when the score crosses a threshold, files a `process-learning` issue in
`agorokh/template-repo`. A future RMS / process-miner agent picks up those
issues and converts them into concrete skill / rule / hook improvements.

The score is a transparent linear combination — no ML, no surprises:

| Metric | Weight |
|---|---|
| `commits_after_first_review` | 1.0 |
| `fix_commits` (msg starts with `fix:` / `chore: address` / `chore(review)`) | 0.5 |
| `human_review_comments` | 0.3 |
| `bot_review_comments` | 0.1 |
| `ci_red_runs` (failure / timed_out on PR head; cancelled excluded — concurrency-cancel noise) | 2.0 |
| `days_open_after_first_ready_for_review` (proxy: first review → merge) | 1.0 |

Levels: `high ≥ 25`, `medium ≥ 12`, otherwise `low`. Tune from data after a
few real samples land — see investigation note
`docs/01_Vault/AcCopilotTrainer/02_Investigations/pr-pain-detection-workflow-2026-04.md`.

## Local usage

```bash
# Score a merged PR (requires gh auth)
python -m tools.pr_pain.pain_score --repo agorokh/template-repo --pr 88
python -m tools.pr_pain.pain_score --repo agorokh/template-repo --pr 88 --json > pain.json

# Decide and (optionally) file
python -m tools.pr_pain.file_issue --score-file pain.json --dry-run
```

## CI usage

The workflow `.github/workflows/pr-pain-detection.yml` runs on:

- `pull_request: closed` (only when `merged == true`) for `template-repo`'s own PRs
- `workflow_dispatch` with `pr_url` input for one-off scoring of any repo —
  **provided the target repo is listed in `dry_run_repos` or `enabled_repos`**;
  un-allowlisted repos hit the "Skipped" notice and produce no score
- `repository_dispatch` (event type `pr-pain-eval`) for child-repo dispatchers
  (added in a later template revision)

Both scoring AND filing are gated by `.github/pr-pain-config.yml`:
`dry_run_repos` allows score-only (no issue filed); `enabled_repos` allows the
full file-or-update path. Start with `agorokh/template-repo` only; expand
after the first cycle of real data.

### Known limitations

- `_fetch_commits` uses GitHub's REST `pulls/{pr}/commits` endpoint, which
  returns at most 250 commits per PR. Very large PRs (>250 commits) will be
  silently truncated, undercounting `commits_after_first_review` and
  `fix_commits` and *biasing the score downward exactly on the most painful
  PRs*. The script logs a warning to stderr when the cap is hit so you can
  spot affected scores. A future revision can switch to GraphQL
  `pullRequest.commits` (uncapped) or a base→head `git log` over a checkout.

## Bot detection (extensible)

`_is_bot` consults `_BUILTIN_KNOWN_BOTS` (built-in list in `pain_score.py`)
PLUS any logins listed under `extra_bot_logins:` in
`.github/pr-pain-config.yml`. New hosted reviewers without the literal
`[bot]` suffix in their login can be opted in **without a code change** —
just add the login to the YAML and the next score run picks it up.
Misclassifying a bot as a human costs a 3x weight inflation (0.1 → 0.3) on
every comment it posts.

## Dedup

The fingerprint is a 12-hex SHA-256 over the sorted top-3 changed
first-segment directories. PRs across different repos that touch the same
top-level area produce the same fingerprint and accumulate on a single issue
(new PRs append to the "Linked PRs" section + add a comment). Reduces noise
in the central backlog from large coordinated migrations.

When no OPEN `[fp:<hex>]` issue exists but CLOSED ones do, the create path
links the most recent closed peers under "Related closed issues" in the new
issue body. Closed issues are NOT auto-reopened — closing was an explicit
human decision; the new issue inherits the historical context instead.

## `gh` version

The script depends on `gh api --paginate --slurp`, which requires
`gh ≥ 2.28.0`. The CI workflow has a hard version-check step; locally,
`pain_score.py` re-frames the cryptic `unknown flag --slurp` stderr as a
clear "needs gh ≥ 2.28" message so a stale local CLI is obvious.

## Timeouts

Every `gh` invocation goes through `pain_score._run_gh`, which enforces a
process timeout (default 60s for single calls, 180s for `--paginate`
calls). On timeout it raises `RuntimeError` with the operation name and
the override knob — never a silent retry-or-zero. Override per run via:

- `PR_PAIN_GH_TIMEOUT_S` — single-call timeout (`gh issue view`, etc.)
- `PR_PAIN_GH_PAGINATED_TIMEOUT_S` — `--paginate --slurp` timeout

Worth raising for cross-org cold-cache lookups; do not lower below 30s.

## Why a separate module from `process_miner`

`tools/process_miner/` mines *patterns* across many PRs (recurring review
themes, CI failures) — it answers "what should we change?". `tools/pr_pain/`
detects *individual* PRs that warrant a closer look — it answers "which PRs
are worth mining?". They compose: the issue body suggests running
process_miner scoped to the painful PR.
