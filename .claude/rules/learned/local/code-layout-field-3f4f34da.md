---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 3f4f34da287d3922
mined_from: 3 review comments across 2 PRs
last_updated: 2026-05-04
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: guideline
---

# Code Layout Field (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _⚠️ Potential issue_ | _🟠 Major_

**`rotate()` silently no-ops when file sizes are unavailable — cap is not enforced.**

If `io.fileSize` is missing (or any pcall on it fails), every entry has `size =...
- _⚠️ Potential issue_ | _🟡 Minor_

**`bestForSetup` ignores layout despite doc claim — wrong BEST for multi-layout tracks.**

The docstring at lines 138–140 says the BEST is computed for "the current c...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Record layout before enforcing layout-only BEST matching**

When an active track layout is present, this branch ...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
