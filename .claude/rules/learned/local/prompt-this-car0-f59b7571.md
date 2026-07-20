---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "src/**/*"
source: process-miner
rule_fingerprint: f59b7571f84c1a75
mined_from: 5 review comments across 3 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: architecture
---

# Prompt This Car0 (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

1\. Stale <b><i>sessionlapscachevalue</i></b> reuse <code>📎 Requirement gap</code...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

3\. Taskkill missing /t <code>🐞 Bug</code> <code>☼ Reliability</code>

<pre>
<b><...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

1\. Car0 probe too short <code>🐞 Bug</code> <code>≡ Correctness</code>

<pre>
_pr...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

1\. Stale car0 cache <code>🐞 Bug</code> <code>≡ Correctness</code>

<pre>
In resi...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
