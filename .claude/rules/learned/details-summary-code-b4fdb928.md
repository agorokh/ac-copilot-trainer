---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
  - "tools/**/*"
  - "docs/**/*"
source: process-miner
rule_fingerprint: b4fdb92801185244
mined_from: 8 review comments across 5 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: maintainability
preventability: automation
---

# Details Summary Code (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- _⚠️ Potential issue_ | _🟠 Major_

**Coaching hint logic appears inverted for high entry speed.**

When `en > bn + 5` (driver entering faster than reference), the hint suggests "try braking slightly la...
- _🧹 Nitpick_ | _🔵 Trivial_

**Minor: Docstring says "echo server" but the server only logs, doesn't echo.**

The server receives and logs messages but doesn't send responses back. Consider updating the...
- _🧹 Nitpick_ | _🔵 Trivial_

**Clarify helper scope to avoid over-constraining valid direct field reads.**

Line 20 currently implies all `sim`/`car` accesses should be helper-wrapped. In practice, this...
- _⚠️ Potential issue_ | _🟠 Major_

**Keep Draw3D diagnostics opt-in by default.**

With this set to `true`, all sessions emit periodic debug logs, which can quickly flood AC logs outside targeted debug...

## Suggested enforcement

- Prefer lint/format or CI checks over manual review for this class of issue.
