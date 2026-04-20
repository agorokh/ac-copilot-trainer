---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: 57e1a9be8d5ca700
mined_from: 16 review comments across 1 PRs
last_updated: 2026-04-20
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: guideline
---

# Details Summary Code (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _🧹 Nitpick_ | _🔵 Trivial_

**Consider extracting manifest sizes to a shared constant.**

The hardcoded window sizes must stay synchronized with `manifest.ini` per the comment. Consider defining these ...
- _🧹 Nitpick_ | _🔵 Trivial_

**Diagnostic logging may be verbose for normal use.**

The 3-second `[RT-DIAG]` logging is helpful for debugging issue `#75` but will generate continuous log output during n...
- _⚠️ Potential issue_ | _🟠 Major_

<details>
<summary>🧩 Analysis chain</summary>

🏁 Script executed:

```shell
cat -n src/ac_copilot_trainer/modules/coaching_font.lua
```

Repository: agorokh/ac-copilo...
- _⚠️ Potential issue_ | _🟠 Major_

**Wrap `ui.windowSize()` calls with `pcall` on the real layout path.**

The diagnostic block at Line 131 correctly uses `pcall(function() return ui.windowSize() end)`...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
