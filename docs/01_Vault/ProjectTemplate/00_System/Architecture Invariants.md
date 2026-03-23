---
type: architecture-invariants
status: active
memory_tier: canonical
last_validated: 2026-03-23
---

# Architecture invariants

Replace this stub with **numbered, testable rules** for your project.

## Template examples (delete when real)

1. **Single entrypoint** — Production behavior is invoked only through documented entrypoints (list them).
2. **Secrets** — No credentials in source; use environment variables and secret managers.
3. **Data immutability** — Raw evidence or regulated data paths are not agent-writable (list paths); enforce with hooks if needed.
4. **Persistence** — Choose one primary store for authoritative state (database, object store, etc.) and forbid parallel ad-hoc files.

## Enforcement

- Claude Code: optional PreToolUse prompts in `.claude/settings.json`.
- CI: custom scripts under `scripts/` + tests.
- Review: `.cursor/BUGBOT.md` and GitHub bots.
