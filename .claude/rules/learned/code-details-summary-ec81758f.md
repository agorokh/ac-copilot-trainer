---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "scripts/**/*"
source: process-miner
rule_fingerprint: ec81758f92b7be6e
mined_from: 19 review comments across 13 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: perf
preventability: test
---

# Code Details Summary (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _🧹 Nitpick_ | _🔵 Trivial_

**`getTrace()` returns a mutable reference to internal buffer.**

The comment warns "do not mutate," but returning the internal `lapBuf` table directly allows callers to acc...
- _🧹 Nitpick_ | _🔵 Trivial_

**Defensive trim is unreachable given early break.**

The `while `#out` > 3` loop at lines 73-75 can never execute because the loop at line 35 breaks when `#out >= 3`, and t...
- _🛠️ Refactor suggestion_ | _🟠 Major_

**Consolidate ID/sanitization logic through `csp_helpers` to avoid drift.**

`M.sessionKey` currently reimplements guarded `ac.get*` access and local sanitization...
- _🧹 Nitpick_ | _🔵 Trivial_

**Redundant nested pcall structure.**

The outer `pcall` on line 111 wraps an anonymous function that contains additional `pcall` calls for each render primitive. If any inn...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
