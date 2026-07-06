---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 630d72f4e4bd34f8
mined_from: 3 review comments across 3 PRs
last_updated: 2026-07-06
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: architecture
---

# Setup With Tests (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <h3>PR Summary by Qodo</h3>

feat(harness): one-command launch, setup verify, evidence bundle, stall recovery

<code>✨ Enhancement</code> <code>🧪 Tests</code> <code>📝 Documentation</code> <code>🕐 40+ ...
- <h3>PR Summary by Qodo</h3>

Compose harness setup runs with autonomous drive via transient CSP FORCE_START

<code>✨ Enhancement</code> <code>🧪 Tests</code> <code>📝 Documentation</code> <code>🕐 40+ Mi...
- <h3>PR Summary by Qodo</h3>

Add degradation/lap-feature grains and Parquet ML surface to coaching lake

<code>✨ Enhancement</code> <code>🧪 Tests</code> <code>📝 Documentation</code> <code>🕐 40+ Minute...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
