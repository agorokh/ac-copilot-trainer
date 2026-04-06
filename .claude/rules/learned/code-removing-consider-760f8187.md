---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
  - "docs/**/*"
source: process-miner
rule_fingerprint: 760f81874c70fda0
mined_from: 6 review comments across 4 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: guideline
---

# Code Removing Consider (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `sim` is no longer used in this function after removing the billboard/rectangle path. To make the unused parameter intentional (and quiet linters), consider renaming it to `_sim` (or removing it if th...
- `state.coachingUntil` is now effectively unused for visibility/remaining time (coaching uses `coachingRemainSec`), but it’s still kept in state and updated on lap completion. Consider removing `coachi...
- `state.coachingUntil` is now only initialized/reset and updated on lap completion, but no longer used for any visibility logic (search shows no other reads). Keeping it updated alongside `coachingRema...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

Using `re.match` with a `^` anchor prevents matching EmmyLua tags that are indented. Switching to `re.search` (and removing the ...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
