---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - ".github/**/*"
source: process-miner
rule_fingerprint: e69f49b0872db8d2
mined_from: 3 review comments across 2 PRs
last_updated: 2026-06-29
repository: agorokh/ac-copilot-trainer
scope: S3
domain_tag: ""
frequency_across_repos: 1
source_repos:
  - "agorokh/ac-copilot-trainer"
severity: maintainability
preventability: test
---

# Code Code_Block Ensure (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _🗄️ Data Integrity & Integration_ | _🟠 Major_ | _⚡ Quick win_

**Allow the disarm path to run when `vault-only` is removed.**

Line 21 skips the entire job once the label is gone, so an `unlabeled` ev...
- _🩺 Stability & Availability_ | _🟠 Major_ | _⚡ Quick win_

**Always close the controller if the drive thread raises.**

`await drive_task` can raise before `controller.close()` runs, leaking the contro...
- _🎯 Functional Correctness_ | _🟠 Major_ | _⚡ Quick win_

**Veto success when sim-death was detected.**

`rig_drive` can set `sim_dead=True` after the car already exceeded the distance/speed thresholds,...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
