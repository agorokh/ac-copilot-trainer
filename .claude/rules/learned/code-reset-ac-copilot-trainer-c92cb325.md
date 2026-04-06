---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: c92cb325133ec53b
mined_from: 3 review comments across 3 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: guideline
---

# Code Reset Ac_Copilot_Trainer (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `segDrawn` is set to `true` before the render call result is known, but it’s later used to decide whether to reset `prevTiltH` (to prevent tilt leaking across gaps). If drawing fails (`okDraw` stays f...
- Diagnostic state is module-global and never resets. After `diagActive` becomes false at 60s, there’s no way to restart diagnostics for a new session (the main script resets its own state on leaving tr...
- ## Code Review

This pull request updates AC Copilot Trainer to version 0.4.2, transitioning the coaching countdown timer from simulation time to wall-clock time to resolve visibility issues. Key chan...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
