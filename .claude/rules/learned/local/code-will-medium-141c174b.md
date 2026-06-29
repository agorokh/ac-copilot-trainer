---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
source: process-miner
rule_fingerprint: 141c174b15ec2c1c
mined_from: 3 review comments across 3 PRs
last_updated: 2026-06-29
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: maintainability
preventability: architecture
---

# Code Will Medium (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `_make_wheels` method currently assumes `specs` is always a Python sequence of dictionaries. If `specs` is `None`, `enumerat...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

If the reference archive JSON is valid but structurally malformed (e.g., missing expected keys or having incorrect types), `lap_...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

Defensive programming: If `track_length_m` is `None` (e.g., if the reference archive is missing the track length or it fails to ...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
