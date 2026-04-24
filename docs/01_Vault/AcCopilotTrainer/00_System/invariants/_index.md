---
type: index
status: active
created: 2026-03-27
updated: 2026-03-27
part_of: AcCopilotTrainer/00_System/Architecture Invariants.md
relates_to:
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/invariants/persistence.md
  - 00_Graph_Schema.md
---

# Architecture invariants (index)

Focused, testable rules for this project. Read only the nodes relevant to your task (see [00_Graph_Schema.md](../../../00_Graph_Schema.md)).

| Node | Summary |
|------|---------|
| [entrypoint.md](entrypoint.md) | Production behavior only through documented entrypoints. |
| [no-secrets.md](no-secrets.md) | No credentials in source; env and secret managers only. |
| [data-immutability.md](data-immutability.md) | Raw or regulated paths are not agent-writable. |
| [persistence.md](persistence.md) | One primary store for authoritative state. |

**Legacy entry:** [Architecture Invariants.md](../Architecture%20Invariants.md) (overview pointer).

## Enforcement (summary)

- Hooks: `.claude/settings.json` (optional PreToolUse prompts).
- CI: `scripts/` checks + tests.
- Review: `.cursor/BUGBOT.md` and GitHub bots.
