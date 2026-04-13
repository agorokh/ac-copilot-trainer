---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: 562978636f79e051
mined_from: 3 review comments across 1 PRs
last_updated: 2026-04-13
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: architecture
---

# Corner Code Label (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- ![high](https://www.gstatic.com/codereviewagent/high-priority.svg)

There is a logic error in the corner label priority. Currently, if `nextBrake` is found (which is almost always true as it wraps aro...
- _⚠️ Potential issue_ | _🟠 Major_

**In-corner coaching should override the next-corner label.**

`cornerLabel` is resolved from the next brake point first, and Line 235 only fills the current segment ...
- ### In-corner label override misattributes BRAKE NOW hints

**Medium Severity**

<!-- DESCRIPTION START -->
When the car is inside a corner segment, `cornerLabel` is overridden to the current corner's...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
