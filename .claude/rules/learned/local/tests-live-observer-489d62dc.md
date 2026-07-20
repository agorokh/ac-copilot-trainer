---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 489d62dc7a580cbf
mined_from: 3 review comments across 3 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: typecheck
---

# Tests Live Observer (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <h3>PR Summary by Qodo</h3>

Harness observer class to capture telemetry_tick and report TC/ABS intervention

<code>🐞 Bug fix</code> <code>✨ Enhancement</code> <code>🧪 Tests</code> <code>🕐 40+ Minutes...
- <h3>PR Summary by Qodo</h3>

Fix launch classification against shared-memory corpse packet regressions

<code>🐞 Bug fix</code> <code>🧪 Tests</code> <code>🕐 40+ Minutes</code>

<img src="https://www.qo...
- <h3>PR Summary by Qodo</h3>

Docs: add Tier-1 changelog fact on acpmf shared-memory lifetime and launch gating

<code>📝 Documentation</code> <code>🕐 Less than 10 minutes</code>

<img src="https://www....

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
