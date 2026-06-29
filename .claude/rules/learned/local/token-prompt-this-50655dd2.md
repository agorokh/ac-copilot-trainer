---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "firmware/**/*"
source: process-miner
rule_fingerprint: 50655dd2bf123d2a
mined_from: 4 review comments across 3 PRs
last_updated: 2026-06-29
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: guideline
---

# Token Prompt This (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

5\. Wrong jwe offset tracking <code>🐞 Bug</code> <code>≡ Correctness</code>

<pre...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

3\. Sidecar env vars undocumented <code>📘 Rule violation</code> <code>✧ Quality</...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

4\. Token rotation docs missing <code>📎 Requirement gap</code> <code>⚙ Maintainab...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

1\. <b><i>external_bind</i></b> defaults to <b><i>0.0.0.0</i></b> <code>📎 Require...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
