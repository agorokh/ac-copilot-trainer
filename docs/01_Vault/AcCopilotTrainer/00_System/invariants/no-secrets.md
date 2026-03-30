---
type: invariant
status: active
created: 2026-03-27
updated: 2026-03-27
relates_to:
  - ProjectTemplate/00_System/invariants/_index.md
  - ProjectTemplate/00_System/invariants/data-immutability.md
part_of: ProjectTemplate/00_System/invariants/_index.md
---

# Invariant: no secrets in source

## Rule

No credentials, API keys, or private material in repository files. Use environment variables, secret managers, and `.env` **locally only** (never committed).

## Rationale

Secrets in git are effectively public; rotation and compliance become expensive.

## Enforcement

- `.claude/settings.json` PreToolUse **prompts** surface common secret patterns in new edits (non-blocking in the template; tighten to blocking hooks if your threat model requires it).
- `AGENTS.md` / `AGENT_CORE_PRINCIPLES.md` require no secrets in Issues or PRs.
- Review and bots flag credential-shaped strings.
