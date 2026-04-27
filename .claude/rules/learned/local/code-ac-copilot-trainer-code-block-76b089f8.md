---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: 76b089f8a1f991ad
mined_from: 4 review comments across 4 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: automation
---

# Code Ac_Copilot_Trainer Code_Block (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- 

> [!CAUTION]
> Some comments are outside the diff and can’t be posted inline due to platform limitations.
> 
> 
> 
> <details>
> <summary>⚠️ Outside diff range comments (1)</summary><blockquote>
> 
...
- 

<details>
<summary>♻️ Duplicate comments (3)</summary><blockquote>

<details>
<summary>src/ac_copilot_trainer/modules/session_journal.lua (3)</summary><blockquote>

`24-60`: _⚠️ Potential issue_ | _...
- 

> [!CAUTION]
> Some comments are outside the diff and can’t be posted inline due to platform limitations.
> 
> 
> 
> <details>
> <summary>⚠️ Outside diff range comments (1)</summary><blockquote>
> 
...
- 

<details>
<summary>♻️ Duplicate comments (1)</summary><blockquote>

<details>
<summary>src/ac_copilot_trainer/modules/lap_archive.lua (1)</summary><blockquote>

`360-371`: _⚠️ Potential issue_ | _🟡 ...

## Suggested enforcement

- Prefer lint/format or CI checks over manual review for this class of issue.
