---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 83dbbc893343a172
mined_from: 3 review comments across 1 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: architecture
---

# Heading Brake Nearby (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- By design: brake events are sparse point samples without stored heading data. Using car.look is the best available proxy since only nearby walls are rendered and the driver is typically heading the sa...
- Acknowledged as a known limitation. Brake events are sparse point samples with no stored heading — car.look is the best available proxy. Only nearby walls are rendered (FADE_FAR culling), minimizing t...
- `@agorokh`, understood — thanks for the context. Using `car.look` as a proxy makes sense given that brake point records don't carry heading data and only nearby walls (where the car's facing direction...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
