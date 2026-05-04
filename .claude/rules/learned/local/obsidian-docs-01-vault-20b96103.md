---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 20b961036b74b7ee
mined_from: 3 review comments across 2 PRs
last_updated: 2026-05-04
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: maintainability
preventability: automation
---

# Obsidian Docs 01_Vault (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <h3>Review Summary by Qodo</h3>

Post-merge vault handoff for PR #91 with Obsidian config and rig documentation

<code>📝 Documentation</code>

<img src="https://www.qodo.ai/wp-content/uploads/2025/11/...
- <h3>Review Summary by Qodo</h3>

Remove Obsidian config and accidental draft from vault

<code>🐞 Bug fix</code>

<img src="https://www.qodo.ai/wp-content/uploads/2025/11/light-grey-line.svg" height="1...
- ## Code Review

This pull request removes local Obsidian configuration files and a rig setup documentation file. The reviewer recommends updating the .gitignore file to exclude the .obsidian/ director...

## Suggested enforcement

- Prefer lint/format or CI checks over manual review for this class of issue.
