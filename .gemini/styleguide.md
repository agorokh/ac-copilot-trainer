# Code review style guide (Gemini Code Assist)

Official Gemini Code Assist reads **`styleguide.md`** in `.gemini/` for review tone and rules. **Canonical for Gemini:** edit this file when changing rules the bot must enforce; mirror the same substance into **`.gemini/review_instructions.md`** so operators and issue checklists stay aligned.

## Non-negotiables

- Follow **AGENTS.md**, **AGENT_CORE_PRINCIPLES.md**, **`docs/00_Core/SESSION_LIFECYCLE.md`**, and vault **invariants** (`docs/01_Vault/<ProjectKey>/00_System/invariants/_index.md`; template uses `AcCopilotTrainer` until bootstrap rename).
- **No secrets** — no API keys, tokens, or private keys in code or tests.
- **No commits to `main`** from agents without explicit human waiver — use a branch and pull request. **Exception:** vault-only post-merge handoff under `docs/01_Vault/` when direct push to `main` is allowed (see `docs/00_Core/SESSION_LIFECYCLE.md`); if protected, escalate.
- **Canonical paths only** — see `docs/10_Development/11_Repository_Structure.md`.

## Quality

- Prefer explicit errors over silent fallbacks that hide incomplete work.
- Keep diffs focused; defer scope creep to new GitHub Issues.
