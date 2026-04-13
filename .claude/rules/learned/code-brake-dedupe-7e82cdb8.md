---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: 7e82cdb87b68a4d5
mined_from: 4 review comments across 1 PRs
last_updated: 2026-04-13
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: typecheck
---

# Code Brake Dedupe (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **suggestion (testing):** Live-frame engine tests don’t exercise all documented priority rules (PREPARE TO BRAKE, EASE OFF, approach labeling, and dedupe).

ETE-02..04 cover BRAKE NOW and the slower-t...
- ![high](https://www.gstatic.com/codereviewagent/high-priority.svg)

The dedupe key is too coarse and can suppress critical coaching updates. Since the key only consists of `kind` and `cornerLabel`, a ...
- **<sub><sub>![P1 Badge](https://img.shields.io/badge/P1-orange?style=flat)</sub></sub>  Include hint text/state in realtime dedupe key**

The dedupe key only uses `kind` and `cornerLabel`, so distinct...
- The 600 ms dedupe key is only `(kind, cornerLabel)`, so different messages of the same kind for the same corner (e.g., `PREPARE TO BRAKE` → `BRAKE NOW`) will be suppressed for up to `DEDUP_HOLD_SEC`, ...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
