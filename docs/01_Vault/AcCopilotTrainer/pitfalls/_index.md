---
type: index
status: active
created: 2026-04-10
updated: 2026-04-10
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/01_Decisions/shift-left-issue-creation.md
---

# Pitfalls (index)

Recurring implementation mistakes mined from fleet-wide PR review comments (semantic clustering, April 2026). The issue writer agent reads this directory to inject "Known pitfalls" into new issues.

**Source:** 597 semantic clusters (fleet scan: 13 repos scanned; 9 contributed active PR signals), 231 PRs, 8,546 comments. See [corpus analysis](../02_Investigations/process-miner-corpus-analysis-2026-04.md).

**Hub-spoke:** This directory lives in `template-repo` (the hub). Child repos fetch pitfalls at issue-creation time via `gh api`. See `.claude/pitfalls-hub.json`.

| Node | Severity | Clusters | Comments | Repos |
|------|----------|----------|----------|-------|
| [silent-exception-swallowing.md](silent-exception-swallowing.md) | bug | 8 | 109 | 3 |
| [missing-input-validation.md](missing-input-validation.md) | bug | 9 | 77 | 3 |
| [injection-risks.md](injection-risks.md) | security | 2 | 9 | 2 |
| [state-consistency.md](state-consistency.md) | bug | 4 | 44 | 3 |
| [vault-path-integrity.md](vault-path-integrity.md) | reliability | 6 | 73 | 2 |
| [secret-credential-handling.md](secret-credential-handling.md) | security | 4 | 41 | 3 |
| [redundant-code-drift.md](redundant-code-drift.md) | maintainability | 4 | 36 | 3 |
