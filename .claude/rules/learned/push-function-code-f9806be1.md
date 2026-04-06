---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tests/**/*"
  - "src/**/*"
source: process-miner
rule_fingerprint: f9806be145542b98
mined_from: 3 review comments across 2 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Push Function Code (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _🧹 Nitpick_ | _🔵 Trivial_

**Style color push/pop mismatch on early returns or exceptions.**

The `ui.pushStyleColor` at line 25 may succeed, but if any code between lines 28-46 throws an exception or...
- **suggestion (testing):** Font push/pop balancing is checked globally, not per draw function as the requirement states

The docstring requires each draw function to bracket fontMod.push()/fontMod.pop(...
- The docstring says this verifies “Every draw function … brackets font push/pop”, but the implementation only checks total `fontMod.push()`/`fontMod.pop()` counts across the whole file. This can produc...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
