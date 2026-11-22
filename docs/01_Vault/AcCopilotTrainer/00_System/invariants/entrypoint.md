---
type: invariant
status: active
created: 2026-03-27
updated: 2026-03-27
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/invariants/persistence.md
part_of: AcCopilotTrainer/00_System/invariants/_index.md
---

# Invariant: single entrypoint

## Rule

Production behavior is invoked only through **documented entrypoints** (CLI commands, services, jobs — list them in your specialized vault or README).

## Rationale

Hidden entrypoints make security, observability, and refactors unpredictable.

## Enforcement

- Document entrypoints in vault or `README.md` after bootstrap.
- Code review rejects new implicit `if __name__ == "__main__"` production paths unless listed.
- CI may add smoke tests that exercise declared entrypoints only.
