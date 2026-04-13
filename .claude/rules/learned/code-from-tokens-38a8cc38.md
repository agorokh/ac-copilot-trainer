---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 38a8cc3883e9163f
mined_from: 5 review comments across 1 PRs
last_updated: 2026-04-13
repository: agorokh/ac-copilot-trainer
severity: nit
preventability: automation
---

# Code From Tokens (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `tokens` table is imported from `coachingOverlay` but never used in this file. Furthermore, the `coachingOverlay` module its...
- `tokens` is imported from `coachingOverlay.tokens` but never used; instead this file duplicates the token values in local constants. That undermines the “single source of truth” intent and risks visua...
- `coachingOverlay.tokens` is assigned to `local tokens` but never used, while the file redefines “shadow” token constants that can drift from the canonical values (they already do: `PANEL_PAD_Y` is 18 ...
- Despite importing `coachingOverlay.tokens` as a “single source of truth”, `hud.lua` still defines its own panel constants (e.g., `PANEL_PAD_Y = 18`) that already diverge from `coaching_overlay.lua`’s ...

## Suggested enforcement

- Prefer lint/format or CI checks over manual review for this class of issue.
