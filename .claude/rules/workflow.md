# Workflow

- **Issue → branch → PR → review → merge.** No direct commits to `main`.
- Run **`make ci-fast`** before requesting human review.
- Keep **Draft PRs** open early for long-running agent work so CI and bots can run.

Branch naming (pick one style per team and document in `AGENTS.md`):

- `feat/issue-123-short-slug`
- `fix/issue-456-short-slug`
- Tool-native: `cursor/issue-123_short_description_UTC`
