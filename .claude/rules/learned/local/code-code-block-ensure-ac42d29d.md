---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tests/**/*"
  - "scripts/**/*"
source: process-miner
rule_fingerprint: ac42d29dfe9b54be
mined_from: 69 review comments across 24 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: maintainability
preventability: test
---

# Code Code_Block Ensure (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _⚠️ Potential issue_ | _🟠 Major_

**Keep Draw3D diagnostics opt-in by default.**

With this set to `true`, all sessions emit periodic debug logs, which can quickly flood AC logs outside targeted debug...
- _🧹 Nitpick_ | _🔵 Trivial_

**Redundant nested pcall structure.**

The outer `pcall` on line 111 wraps an anonymous function that contains additional `pcall` calls for each render primitive. If any inn...
- _⚠️ Potential issue_ | _🟡 Minor_

**Handle non-finite delta values before rendering numeric/bar output.**

Line 117 handles `nil`, but not `NaN`/non-finite values. This can produce unstable HUD output...
- _⚠️ Potential issue_ | _🟡 Minor_

**Treat 80 km/h as mid-speed, not red.**

Line 32 uses `> 80`, so a segment at exactly 80 km/h falls into the red branch even though the issue `#35` thresholds define...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
