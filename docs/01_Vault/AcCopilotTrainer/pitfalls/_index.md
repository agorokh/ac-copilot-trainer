---
type: index
status: active
created: 2026-04-10
updated: 2026-07-24
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/01_Decisions/shift-left-issue-creation.md
  - AcCopilotTrainer/pitfalls/epic-body-delivery-drift.md
  - AcCopilotTrainer/pitfalls/cross-issue-pointer-rot.md
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

## Project-curated (not fleet-mined)

Pitfalls observed locally (e.g. during `/backlog-steward` runs) rather than mined from the
fleet PR corpus — so they carry no cluster/comment counts. The issue-writer only injects nodes
with `scope_paths`; process pitfalls below deliberately omit them.

| Node | Severity | Source |
|------|----------|--------|
| [epic-body-delivery-drift.md](epic-body-delivery-drift.md) | maintainability | `/backlog-steward` sweep 2026-06-22 (canonical: #154); investigation-brief variant added 2026-07-24 (canonical: #627) |
| [cross-issue-pointer-rot.md](cross-issue-pointer-rot.md) | maintainability | `/backlog-steward` sweep 2026-07-24 (canonical: #534→#59/#119 phantom gates) |
