---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "scripts/**/*"
source: process-miner
rule_fingerprint: b3a20273fcec06e3
mined_from: 19 review comments across 2 PRs
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

# Code Commit Unstaged (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Detect commit -a changes in vault follow-up guard**

This guard exits when `git diff --cached` is empty, but the...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Detect pathspec/include commits in vault follow-up guard**

`FILES_TO_CHECK` only includes unstaged tracked file...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Parse long commit options before scanning short flags**

In `commit_may_include_unstaged_tracked`, any token sta...
- ### Long options parsed as short flags cause false blocks

**Medium Severity**

<!-- DESCRIPTION START -->
The embedded Python parser in `commit_may_include_unstaged_tracked` does not distinguish `--l...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
