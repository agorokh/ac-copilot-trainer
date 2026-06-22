---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "tools/**/*"
  - "tests/**/*"
  - "docs/**/*"
source: process-miner
rule_fingerprint: 5aa72c5bf1ac4f6d
mined_from: 7 review comments across 5 PRs
last_updated: 2026-06-22
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

- _🧹 Nitpick_ | _🔵 Trivial_ | _💤 Low value_

**Inconsistent path resolution compared to `ColdRestartActuator`.**

`ColdRestartActuator` calls `.resolve(strict=False)` on `acs_exe` and `race_ini` (lines ...
- _⚠️ Potential issue_ | _🟡 Minor_ | _⚡ Quick win_

**Make the optimizer regression test fail on no-op output.**

`k1 <= k0 + 1e-9` passes if `min_curvature_line()` returns the input unchanged, so this ...
- _⚠️ Potential issue_ | _🟠 Major_ | _⚡ Quick win_

**Normalize `relates_to` paths to vault-root form required by graph schema.**

On Lines 8-11, the `relates_to` entries omit the required `docs/01_Vaul...
- _⚠️ Potential issue_ | _🟡 Minor_ | _⚡ Quick win_

**Guard `lap_archive` type consistently in `from_lap_archive`.**

Line 393 and Line 394 call `lap_archive.get(...)` without first ensuring `lap_archiv...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
