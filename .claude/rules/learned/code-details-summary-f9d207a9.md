---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: f9d207a90e2428f8
mined_from: 5 review comments across 1 PRs
last_updated: 2026-04-20
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Code Details Summary (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- **Actionable comments posted: 9**

> [!CAUTION]
> Some comments are outside the diff and can’t be posted inline due to platform limitations.
> 
> 
> 
> <details>
> <summary>⚠️ Outside diff range comme...
- **Actionable comments posted: 4**

<details>
<summary>♻️ Duplicate comments (2)</summary><blockquote>

<details>
<summary>src/ac_copilot_trainer/modules/ws_bridge.lua (1)</summary><blockquote>

`25-27...
- **Actionable comments posted: 2**

<details>
<summary>🤖 Prompt for all review comments with AI agents</summary>

```
Verify each finding against the current code and only fix it if needed.

Inline com...
- **Actionable comments posted: 2**

> [!CAUTION]
> Some comments are outside the diff and can’t be posted inline due to platform limitations.
> 
> 
> 
> <details>
> <summary>⚠️ Outside diff range comme...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
