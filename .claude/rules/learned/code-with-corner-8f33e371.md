---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: 8f33e3711ff02d0d
mined_from: 11 review comments across 1 PRs
last_updated: 2026-04-20
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: guideline
---

# Code With Corner (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Clear expired corner advisories from shared state**

`wsBridge.takeCornerAdvisory()` can return `nil` when an ad...
- `state.cornerAdvisories` is only updated when `wsBridge.takeCornerAdvisory()` returns a non-nil string, but entries are never removed when the bridge expires them. That means an expired hint can remai...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Gate background follow-up on successful coaching response**

The handler schedules `_send_ollama_followup()` for...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Send corner query with matching corner telemetry**

When `view.cornerLabel` is overridden to the in-corner label...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
