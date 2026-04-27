---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: cfd16591700270bf
mined_from: 6 review comments across 2 PRs
last_updated: 2026-04-27
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: "gaming"
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: bug
preventability: architecture
---

# Code Corner Label (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![high](https://www.gstatic.com/codereviewagent/high-priority.svg)

There is a logic error in the corner label priority. Currently, if `nextBrake` is found (which is almost always true as it wraps aro...
- _⚠️ Potential issue_ | _🟠 Major_

**In-corner coaching should override the next-corner label.**

`cornerLabel` is resolved from the next brake point first, and Line 235 only fills the current segment ...
- _⚠️ Potential issue_ | _🟠 Major_

**Keep the queried corner label aligned with the telemetry.**

When `topLabel` comes from `inCornerLabel`, this block still sends `targetSpeed`/`distToBrakeM` from `n...
- ### Top tile mixes current corner label with next corner's brake data

**Medium Severity**

<!-- DESCRIPTION START -->
When the car is in a corner's apex region, `topCornerLabel` is set to the current...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
