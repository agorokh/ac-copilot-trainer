---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
  - "docs/**/*"
source: process-miner
rule_fingerprint: aa41f86dff4d7ef0
mined_from: 8 review comments across 3 PRs
last_updated: 2026-04-13
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Code Test That (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `hud.lua` calls UI functions like `ui.drawRectFilled`, `ui.drawRect`, `ui.setCursor`, and `ui.windowSize()` without any availability/type checks. Other modules in this repo guard UI APIs (and sometime...
- **suggestion (testing):** There’s no test for the HUD’s behavior when `realtimeView` is nil, even though always-visible tiles are part of the contract.

ETE-01 currently always passes a non-nil `realt...
- **suggestion (testing):** autoPlaceOnce is only validated via grepping source; behavior (one-time move and persisted flag) is not exercised via Lua.

Given the existing `ac.storage`, `ac.getAppWindows...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

This line appears to be redundant. The `state._cachedApproachData` variable is calculated here using the legacy `approachHudData...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
