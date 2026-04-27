---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "scripts/**/*"
source: process-miner
rule_fingerprint: 537dd47d276740c4
mined_from: 4 review comments across 2 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: maintainability
preventability: guideline
---

# Branch Code Local (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Fail sync when local main is ahead of origin/main**

In `phase_sync`, `git pull --ff-only origin main` is treate...
- This deletes any existing local branch named `vault/post-merge-pr<PR>` and then force-pushes it. That’s potentially destructive if someone has local work on that branch name (or if a prior run created...
- `git push -u --force-with-lease origin "$VAULT_BRANCH"` can overwrite an existing remote branch if this script is rerun and the remote branch already exists (especially if the local repo hasn’t fetche...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Stop force-deleting unrelated local branches during sync**

This loop force-deletes every local branch whose ups...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
