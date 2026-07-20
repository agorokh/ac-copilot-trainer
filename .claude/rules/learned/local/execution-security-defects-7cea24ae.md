---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 7cea24ae59b78f6c
mined_from: 6 review comments across 2 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: security
preventability: guideline
---

# Execution Security Defects (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _No execution-correctness or security defects found in the fixed-layout voice recovery change._

No findings at or above **medium** severity. ✅

<sub>model `auto` · 0 raw finding(s) · 256.7s · EPIC #8...
- _No execution-correctness or security defects identified in this diff; fixed-layout negotiation, channel mapping, and failure/status wiring are consistent with the covered paths._

No findings at or a...
- _No clear execution or security defects introduced by this diff; the new lock-probe, verdict, cleanup, and Game Point dispatch paths match the stated fail-closed contracts and are covered by the added...
- _No actionable execution-correctness or security defects found in this diff; the new resilient-launch and Game Point ownership paths look consistently fail-closed under the behaviors the added tests l...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
