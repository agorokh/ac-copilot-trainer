---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 7fe1248a1753fc5d
mined_from: 5 review comments across 4 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: nit
preventability: guideline
---

# Code Exported Never (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ### Exported diagnostic functions are never called anywhere

**Low Severity**

<!-- DESCRIPTION START -->
`setEnabled`, `isActive`, `getProbeResults`, and `getDrawStats` are exported from `render_diag...
- ### Exported `decodeJson` function is never used

**Low Severity**

<!-- DESCRIPTION START -->
`persistence.decodeJson` is newly exported but has zero callers anywhere in the codebase. The internal `j...
- ### Exported function duplicates existing local helper

**Low Severity**

<!-- DESCRIPTION START -->
`M.labelFromWorstRow` in `focus_practice.lua` is logic-identical to the existing `labelFromConsiste...
- ### Exported `M.activeHint()` function is never called

**Low Severity**

<!-- DESCRIPTION START -->
`M.activeHint()` is exported but never called anywhere in the codebase. The active hint is already ...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
