---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "docs/**/*"
source: process-miner
rule_fingerprint: 6e54ac1ea860bac2
mined_from: 5 review comments across 3 PRs
last_updated: 2026-07-13
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: nit
preventability: automation
---

# Code Finite Values (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The `_to_float` and `_to_int` helper functions do not guard against non-finite float values (such as `NaN` or `inf`). If a malfo...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

The documentation states that the non-finite INI guard protects `_parse_lut_pairs`. However, in `tools/ai_sidecar/tyre_specs.py`...
- **<sub><sub>![P2 Badge](https://img.shields.io/badge/P2-yellow?style=flat)</sub></sub>  Reject non-finite INI gains**

When a hand-edited or corrupt `user_ff.ini` has `VALUE=nan` or `VALUE=inf`, this ...
- Both addressed (`ddb79e4`): (1) `_parse_ini_sections` strips the inline comment from the whole line before the section-header regex, so `[FRONT] ; x` parses; (2) `_to_float`/`_to_int` reject NaN/inf (...

## Suggested enforcement

- Prefer lint/format or CI checks over manual review for this class of issue.
