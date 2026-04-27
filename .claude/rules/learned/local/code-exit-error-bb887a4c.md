---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - ".claude/**/*"
  - "scripts/**/*"
source: process-miner
rule_fingerprint: bb887a4cd8abe144
mined_from: 3 review comments across 2 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: guideline
---

# Code Exit Error (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ### Unknown exit code resets nonzero streak counter

**Low Severity**

<!-- DESCRIPTION START -->
In the `runConsoleProcess` exit callback, when `result` is not a table or lacks `exitCode`, `codeNum` ...
- The documented exit code meanings don’t match the script: `scripts/post_merge_sync.sh` uses exit code `10` for failures like `git checkout main` / `git pull --ff-only` and a failed `git commit`, not o...
- ### Missing error handler on `git add` in vault phase

**Low Severity**

<!-- DESCRIPTION START -->
`git add docs/01_Vault/` on line 145 lacks `|| { fail "..."; exit N; }` error handling, unlike every...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
