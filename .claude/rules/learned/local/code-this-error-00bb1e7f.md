---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "tests/**/*"
  - "src/**/*"
  - "firmware/**/*"
source: process-miner
rule_fingerprint: 00bb1e7faa70b827
mined_from: 9 review comments across 3 PRs
last_updated: 2026-06-29
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: guideline
---

# Code This Error (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

In `_ingest_lap`, if `with_wheels` is `True` but a frame in `car_frames` does not contain the `"wheels"` key, accessing `spec["w...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

In `writeTextFile`, `pcall` is used to wrap `f:write(text)`. If `pcall` fails (i.e., `ok` is `false`), the error message is retu...
- ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)

If the PowerShell hotspot probe script fails (which is extremely common on Ethernet-only desktop gaming PCs where tethering is u...
- ![high](https://www.gstatic.com/codereviewagent/high-priority.svg)

In `on_row_delete`, accessing `ctx` when the entire screen is being deleted results in a Use-After-Free (UAF) vulnerability. When `s...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
