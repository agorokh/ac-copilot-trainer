---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "docs/**/*"
source: process-miner
rule_fingerprint: 8984ed4b97a8a0e2
mined_from: 5 review comments across 3 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: nit
preventability: guideline
---

# Code Timed With (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Make `--laps 1` wait for one timed lap**

With `--laps 1`, `_config_from_args` sets `target_laps` to 1, but this...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Fail --laps batches with zero timed laps**

Fresh evidence after the earlier `--laps 1` fix: the tap now waits f...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Include caller-side lap-window assertion in reason**

For `--laps N` runs that see only an untimed lap boundary,...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Require a timed lap in the verification recipe**

When a fresh launch emits an untimed out-lap/teleport boundary...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
