---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 64f34916990a12d6
mined_from: 4 review comments across 2 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: security
preventability: architecture
---

# Code Execution Security (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _cursor: No execution-correctness or security defects identified in this diff._
_antigravity: The architecture is robust, correctly sharing primitives and properly separating the resilient human launc...
- _cursor: No actionable execution-correctness or security defects identified in the reviewed diff; safety-sensitive paths are fail-closed and covered by the added tests._
_antigravity: The resilient la...
- _cursor: The corpse-aware classify changes and platform-pinned lock-probe tests are logically consistent with the stated contracts; no execution or security defects found._
_antigravity: The diff clea...
- _No execution-correctness or security defects found in the #628 corpse-ownership / classify changes or the platform-pinned lock probe tests._

No findings at or above **medium** severity. ✅

<sub>mode...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
