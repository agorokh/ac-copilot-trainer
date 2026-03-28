---
name: project-conventions
description: Pointer to repo non-negotiables — use when workflow or style is ambiguous, or at session start for a quick orientation.
user-invocable: false
---

# Project conventions (pointer)

Do **not** duplicate long policy here. Read these paths as needed:

- `AGENTS.md` — branch/PR naming, `make ci-fast`, bot expectations, tier-1 changelog
- `AGENT_CORE_PRINCIPLES.md` — issue design, upstream sync, hygiene
- `pyproject.toml` — `[tool.ruff]`, package metadata, dev optional deps
- `Makefile` — targets; **`make ci-fast`** before claiming work is done
- `docs/10_Development/10_Agent_Protocol.md` — where files belong, forbidden paths

Vault and architecture: `docs/01_Vault/00_Graph_Schema.md` + `docs/01_Vault/ProjectTemplate/00_System/` (see **`vault-memory`** skill, **`SESSION_LIFECYCLE.md`**).
