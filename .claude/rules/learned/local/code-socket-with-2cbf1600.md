---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 2cbf1600b1c8f492
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

# Code Socket With (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Close failed WebSocket before clearing bridge handle**

When `reconnect = true`, this module intentionally keeps...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Re-send hello after loopback socket reconnects**

This `hello` is only sent during the initial `tryOpen` call, b...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Emit Lua hello without relying on params.onOpen**

Fresh evidence: the repo’s CSP socket API notes (`docs/01_Vau...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
