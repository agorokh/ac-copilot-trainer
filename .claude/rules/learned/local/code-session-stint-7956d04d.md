---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
source: process-miner
rule_fingerprint: 7956d04d73c665a0
mined_from: 3 review comments across 2 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: reliability
preventability: guideline
---

# Code Session Stint (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Reset race status on same-session stint resets**

Fresh evidence beyond the prior replay concern: the Lua reset ...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Scope reviews beyond car and track**

When a tablet reconnects during a new stint/session on the same car and tr...
- Acknowledged as a real residual, deferred with tracking: reviews carry `session_uuid` while lifecycle `session` frames carry `car_id/track_id/session_index` — there is no shared per-session key today,...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
