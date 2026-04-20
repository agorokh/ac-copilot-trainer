---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: f82dc67439923fe9
mined_from: 7 review comments across 1 PRs
last_updated: 2026-04-20
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: guideline
---

# Code Corner With (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Re-send corner queries when revisiting the same turn**

This query gate only sends when `prev == nil` (first tim...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Debounce corner queries only after successful send**

This block records `lastQueryState[topLabel]` before attem...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Gate corner queries to approach distance**

The `corner_query` sender is currently enabled whenever `distToBrake...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Coalesce queued corner_query tasks per connection**

Each `corner_query` unconditionally spawns a new background...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
