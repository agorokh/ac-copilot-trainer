---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 0a0fce35cb570809
mined_from: 6 review comments across 4 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: nit
preventability: guideline
---

# Prompt This Copy (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

1\. <b><i>coachingholdseconds</i></b> set to 30s <code>📎 Requirement gap</code> <code>...
- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

2\. Timer freezes when car nil <code>🐞 Bug</code> <code>≡ Correctness</code>

<pre>
<b...
- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

1\. <b><i>coachingmaxvisiblehints</i></b> change untested <code>📘 Rule violation</code...
- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

1\. <b><i>fmforfilter</i></b> duplicates focus logic <code>📘 Rule violation</code> <co...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
