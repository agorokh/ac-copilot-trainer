---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: 54a1b4a12dbe3277
mined_from: 3 review comments across 3 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: guideline
---

# Code Medium Being (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

If `io.open` fails (e.g., due to permission issues or the directory not being created correctly), the function returns `false` s...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `float(regret)` call is redundant as `regret` is already a float.

```suggestion
                "priority": round(regret, 4...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `ui.textWrapped` function might not be available in all versions of CSP/ImGui. It is safer to check for its existence or use...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
