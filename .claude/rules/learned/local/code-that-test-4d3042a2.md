---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: 4d3042a2e4f2473f
mined_from: 7 review comments across 3 PRs
last_updated: 2026-05-04
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: maintainability
preventability: guideline
---

# Code That Test (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ### Exported `M.activeHint()` function is never called

**Low Severity**

<!-- DESCRIPTION START -->
`M.activeHint()` is exported but never called anywhere in the codebase. The active hint is already ...
- ### Exported `M.phase()` function is never called

**Low Severity**

<!-- DESCRIPTION START -->
`M.phase()` is exported from `realtime_coaching.lua` but never called anywhere in the runtime codebase. ...
- ### Dead code kept solely for test string matching

**Low Severity**

<!-- DESCRIPTION START -->
The `_pe07Touch` variable reads `vm.debriefText` into a local that is never used, followed by a no-op `...
- ### Test PC-07 asserts dead `approachHudData` function presence

**Low Severity**

<!-- DESCRIPTION START -->
Test `PC-07` asserts that `"approachHudData"` appears in the entry script. The function de...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
