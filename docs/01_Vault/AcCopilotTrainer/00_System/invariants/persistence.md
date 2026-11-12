---
type: invariant
status: active
created: 2026-03-27
updated: 2026-03-27
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
part_of: AcCopilotTrainer/00_System/invariants/_index.md
---

# Invariant: single persistence authority

## Rule

Choose **one primary store** for authoritative application state (database, object store, etc.). Avoid parallel ad-hoc files or competing sources of truth for the same domain.

## Rationale

Split-brain persistence causes migration pain, inconsistent backups, and bug classes around reconciliation.

## Enforcement

- ADR or vault note naming the primary store for each bounded context.
- Review challenges new long-lived state files that duplicate DB/object-store roles.
