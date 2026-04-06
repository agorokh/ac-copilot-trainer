---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tests/**/*"
  - "src/**/*"
source: process-miner
rule_fingerprint: 878783fade39527b
mined_from: 3 review comments across 2 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: test
---

# Code That Progress (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **suggestion (testing):** Also test that a mismatched `schema_version` is rejected with the expected error message

This currently only checks the constant value. Please also add a test that modifies ...
- **suggestion (testing):** Strengthen progress bar test to cover behavior around pct (0, 1, and out-of-range values), not just the existence of tokens.

PC-03 currently only checks that `drawProgressBa...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The minimum height of 180px for the approach panel is insufficient to prevent overlap between the progress bar and the branding ...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
