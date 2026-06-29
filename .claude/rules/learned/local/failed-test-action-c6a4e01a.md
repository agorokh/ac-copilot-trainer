---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "**/*"
source: process-miner
rule_fingerprint: c6a4e01a62ffbdfd
mined_from: 3 review comments across 3 PRs
last_updated: 2026-06-29
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: test
---

# Failed Test Action (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ## CI Feedback 🧐

A test triggered by this PR failed. Here is an AI-generated analysis of the failure:

<table><tr><td>

**Action:** guard-and-automerge</td></tr>
<tr><td>

**Failed stage:** [Set up j...
- ## CI Feedback 🧐

A test triggered by this PR failed. Here is an AI-generated analysis of the failure:

<table><tr><td>

**Action:** build</td></tr>
<tr><td>

**Failed stage:** [make ci-fast](https://...
- ## CI Feedback 🧐

A test triggered by this PR failed. Here is an AI-generated analysis of the failure:

<table><tr><td>

**Action:** build</td></tr>
<tr><td>

**Failed stage:** [make ci-fast](https://...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
