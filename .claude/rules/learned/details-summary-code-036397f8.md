---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
source: process-miner
rule_fingerprint: 036397f8c6000b5e
mined_from: 92 review comments across 31 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Details Summary Code (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _🧹 Nitpick_ | _🔵 Trivial_

**Parameters `car` and `sim` are now unused in `sessionKey`.**

The function signature still accepts `car` and `sim` parameters, but the implementation now derives all ident...
- _🧹 Nitpick_ | _🔵 Trivial_

**Consider splitting compound assertion for clearer failure messages.**

When this assertion fails, it's unclear which part failed. Splitting improves debuggability:

```dif...
- <!-- This is an auto-generated comment: summarize by coderabbit.ai -->
<!-- This is an auto-generated comment: review paused by coderabbit.ai -->

> [!NOTE]
> ## Reviews paused
> 
> It looks like this...
- <!-- This is an auto-generated comment: summarize by coderabbit.ai -->
No actionable comments were generated in the recent review. 🎉

<details>
<summary>ℹ️ Recent review info</summary>

<details>
<sum...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
