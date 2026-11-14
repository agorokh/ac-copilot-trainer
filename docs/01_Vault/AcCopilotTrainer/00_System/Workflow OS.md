---
type: workflow-os
status: active
memory_tier: canonical
last_validated: 2026-03-27
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/glossary/ci-fast.md
  - AcCopilotTrainer/00_System/invariants/_index.md
---

# Workflow OS

Document how work flows from Issue → PR → deploy → monitoring for **your** team.

## Roles

- **Author** — implements on a feature branch.
- **Reviewer** — human + bots.
- **Releaser** — tags/releases or deployment owner.

## cadence

- Standups / async updates — _customize_.

## Links

- CI: `.github/workflows/ci.yml`
- Local parity: `make ci-fast`
