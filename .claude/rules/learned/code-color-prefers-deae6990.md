---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: deae6990f090e1b7
mined_from: 182 review comments across 30 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: guideline
---

# Code Color Prefers (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ### Persist on session exit always exits early, losing data

**High Severity**

<!-- DESCRIPTION START -->
`persistSnapshot` is called inside the `sim.isInMainMenu` branch of `script.update`, but `per...
- ### Silent fallback discards data when JSON unavailable

**Medium Severity**

<!-- DESCRIPTION START -->
`jsonEncode` silently returns `"{}"` when the `JSON` global is missing, causing `persistence.sa...
- ### Session state not reset when car/track changes

**High Severity**

<!-- DESCRIPTION START -->
With `LAZY=PARTIAL`, the script persists across session changes. When transitioning to the main menu, ...
- ### Session restart causes stale brake data contamination

**Medium Severity**

<!-- DESCRIPTION START -->
When a player restarts a session without going through the main menu, `car.lapCount` drops fr...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
