---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: 7cb5dcb0eea26ffc
mined_from: 4 review comments across 4 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: architecture
---

# Code Callback Function (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _⚠️ Potential issue_ | _🔴 Critical_

<details>
<summary>🧩 Analysis chain</summary>

🌐 Web query:

`Does CSP (Content Manager Shaders Patch) Assetto Corsa Lua API ui.treeNode accept a callback function...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The logic in `visibleHintCount` for normalizing `maxVisible` (including `tonumber` conversion, NaN checks, rounding, and clampin...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The regex for `push` is inconsistent with `pop` and overly restrictive by requiring empty parentheses. Since `push` is called as...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

This test only verifies that the module loads. Expanding it to call `draw(vm)` would exercise the UI logic and help catch issues...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
