---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: bdbc4d7bf20babbe
mined_from: 5 review comments across 2 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: guideline
---

# Code Push Function (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _🧹 Nitpick_ | _🔵 Trivial_

**Style color push/pop mismatch on early returns or exceptions.**

The `ui.pushStyleColor` at line 25 may succeed, but if any code between lines 28-46 throws an exception or...
- ### Style pop without confirming push succeeded

**Low Severity**

<!-- DESCRIPTION START -->
`ui.popStyleColor` is called whenever the function exists, regardless of whether `pcall(ui.pushStyleColor,...
- **suggestion (testing):** Font push/pop balancing is checked globally, not per draw function as the requirement states

The docstring requires each draw function to bracket fontMod.push()/fontMod.pop(...
- The docstring says this verifies “Every draw function … brackets font push/pop”, but the implementation only checks total `fontMod.push()`/`fontMod.pop()` counts across the whole file. This can produc...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
