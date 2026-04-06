---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tools/**/*"
source: process-miner
rule_fingerprint: cf0699550bf06d22
mined_from: 29 review comments across 11 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: typecheck
---

# Code Summary Details (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

1\. Unguarded ui.getcursor deref <code>🐞 Bug</code> <code>☼ Reliability</code>

<pre>
...
- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

1\. <b><i>coachingholdseconds</i></b> set to 30s <code>📎 Requirement gap</code> <code>...
- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

2\. Timer freezes when car nil <code>🐞 Bug</code> <code>≡ Correctness</code>

<pre>
<b...
- <img src="https://www.qodo.ai/wp-content/uploads/2026/01/action-required.png" height="20" alt="Action required">

1\. <b><i>coachingmaxvisiblehints</i></b> change untested <code>📘 Rule violation</code...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
