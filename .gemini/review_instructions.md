# Repository code review instructions

This aligns with `.cursor/BUGBOT.md` so automated reviewers share the same bar as Cursor Bugbot.

**Sync with Gemini:** Gemini Code Assist loads **`styleguide.md`** as the custom review guide. When you change review policy, update **`.gemini/styleguide.md` first**, then mirror the same substance here so humans and acceptance checks stay aligned.

## Non-negotiables

- Follow **AGENTS.md**, **AGENT_CORE_PRINCIPLES.md**, **`docs/00_Core/SESSION_LIFECYCLE.md`**, and vault **invariants** (`docs/01_Vault/<ProjectKey>/00_System/invariants/_index.md`; template uses `AcCopilotTrainer` until bootstrap rename).
- **No secrets** — no API keys, tokens, or private keys in code or tests.
- **No commits to `main`** from agents without explicit human waiver — use a branch and pull request. **Exception:** vault-only post-merge handoff under `docs/01_Vault/` when direct push to `main` is allowed (see `docs/00_Core/SESSION_LIFECYCLE.md`); if protected, escalate.
- **Canonical paths only** — see `docs/10_Development/11_Repository_Structure.md`.

## Quality

- Prefer explicit errors over silent fallbacks that hide incomplete work.
- Keep diffs focused; defer scope creep to new GitHub Issues.
