# Workflow

- **Issue → branch → PR → review → merge.** No direct commits to `main`.
- **Group issues by files touched.** Never create separate issues that modify overlapping source files. Consolidate into one issue with labeled Parts.
- Run **`make ci-fast`** before requesting human review.
- Keep **Draft PRs** open early for long-running agent work so CI and bots can run.
- **Own every failure.** Never characterize bugs as "pre-existing." Fix it now.
- **Preserve manual work.** Pipeline rebuilds and bulk ops must never delete user content.
- **PR merge order:** Merge simpler PRs first, then rebase and merge complex ones.

Branch naming (pick one style per team and document in `AGENTS.md`):

- `feat/issue-123-short-slug`
- `fix/issue-456-short-slug`
- Tool-native: `cursor/issue-123_short_description_UTC`

## Upstream template sync

When you improve a **domain-agnostic** workflow principle in this repo, it may belong in `template-repo` too. After the PR merges, ask the user: _"This improvement is universal — should I propagate to template-repo?"_ Never propagate domain data, secrets, or project-specific configs.
