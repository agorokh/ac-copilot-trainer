---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
source: process-miner
rule_fingerprint: 5bf08ab35cd540bb
mined_from: 5 review comments across 3 PRs
last_updated: 2026-07-20
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: guideline
---

# Prompt With This (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

1\. Archive poll over-requires validity <code>🐞 Bug</code> <code>☼ Reliability</c...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

1\. Preset decode can crash <code>🐞 Bug</code> <code>☼ Reliability</code>

<pre>
...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

2\. Cm exit defers as failure <code>🐞 Bug</code> <code>☼ Reliability</code>

<pre...
- <img src="https://img.shields.io/badge/Action_required-634FD1?style=flat-square" height="20px" alt="Action required">

2\. Car0 probe exceptions abort <code>🐞 Bug</code> <code>☼ Reliability</code>

<p...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
