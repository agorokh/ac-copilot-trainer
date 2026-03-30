# Bugbot context (template)

Cursor Bugbot can include this file during review.

## Non-negotiables

- Follow **AGENTS.md**, **AGENT_CORE_PRINCIPLES.md**, **`docs/00_Core/SESSION_LIFECYCLE.md`**, and vault **invariants** (`docs/01_Vault/AcCopilotTrainer/00_System/invariants/_index.md`).
- **No secrets** — no API keys, tokens, or private keys in code or tests.
- **No commits to `main`** from agents — branch + PR only.
- **Canonical paths only** — see `docs/10_Development/11_Repository_Structure.md`.

## Quality

- Prefer explicit errors over silent fallbacks that hide incomplete work.
- Keep diffs focused; defer scope creep to new Issues.

Customize this file when you specialize the template for your domain.
