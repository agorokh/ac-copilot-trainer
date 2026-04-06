---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 05f925abf1b3a77f
mined_from: 5 review comments across 3 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: automation
---

# Code Summary Details (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- <!-- This is an auto-generated comment: summarize by coderabbit.ai -->
<!-- This is an auto-generated comment: review paused by coderabbit.ai -->

> [!NOTE]
> ## Reviews paused
> 
> It looks like this...
- <h3>Review Summary by Qodo</h3>

Add session journal export with schema v1 validation

<code>✨ Enhancement</code>

<img src="https://www.qodo.ai/wp-content/uploads/2025/11/light-grey-line.svg" height=...
- ## Code Review

This pull request introduces a session journal system that exports driving stint data as JSON files when returning to the main menu. The changes include a new Lua module for generating...
- ## Code Review

This pull request introduces a `coachingMaxVisibleHints` configuration setting to limit the number of coaching hints displayed in the HUD to a range of 1–3. The changes include a norma...

## Suggested enforcement

- Prefer lint/format or CI checks over manual review for this class of issue.
