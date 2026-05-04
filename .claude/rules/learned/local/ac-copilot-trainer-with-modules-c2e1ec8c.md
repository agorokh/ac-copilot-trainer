---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: c2e1ec8c0184e03f
mined_from: 5 review comments across 5 PRs
last_updated: 2026-05-04
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: reliability
preventability: typecheck
---

# Ac_Copilot_Trainer With Modules (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <h3>Review Summary by Qodo</h3>

Add Ollama post-lap debrief with HUD display and rules fallback (issue #46)

<code>✨ Enhancement</code> <code>🧪 Tests</code>

<img src="https://www.qodo.ai/wp-content/...
- <h3>Code Review by Qodo</h3>

<code>🐞 Bugs (1)</code>  <code>📘 Rule violations (3)</code>  <code>📎 Requirement gaps (0)</code>  <code>🎨 UX Issues (0)</code>

<img src="https://www.qodo.ai/wp-content/u...
- <h3>Code Review by Qodo</h3>

<code>🐞 Bugs (1)</code>  <code>📘 Rule violations (0)</code>  <code>📎 Requirement gaps (0)</code>  <code>🎨 UX Issues (0)</code>

<img src="https://www.qodo.ai/wp-content/u...
- <h3>Code Review by Qodo</h3>

<code>🐞 Bugs (0)</code>  <code>📘 Rule violations (1)</code>  <code>📎 Requirement gaps (0)</code>  <code>🎨 UX Issues (0)</code>

<img src="https://www.qodo.ai/wp-content/u...

## Suggested enforcement

- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.
