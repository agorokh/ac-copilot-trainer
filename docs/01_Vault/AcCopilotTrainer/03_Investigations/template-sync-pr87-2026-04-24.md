---
type: investigation
status: active
memory_tier: canonical
last_updated: 2026-04-24
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
---

# Template-sync PR #87 (2026-04-24)

**Resolution:** PR #87 MERGED 2026-04-24T22:12Z as squash commit `ab13a71`. Upstream tracker [`agorokh/template-repo#97`](https://github.com/agorokh/template-repo/issues/97) carries 17+ deferred items (3× P1, 2× P2). See `Next Session Handoff.md` for follow-up summary and post-merge classifier output.


## What

Sync canonical template from `template-repo@76e62d2` (pinned Apr 4) to `template-repo@061d9ab` (Apr 24), propagating **52 commits** including the root-cause fix for orchestrator hook-drift on this machine.

## Why

The `issue-driven-coding-orchestrator` skill stopped reaching `git push` / `gh pr create` on EPIC #86 (second occurrence). Root cause: template-repo `PostToolUse:Bash` hook was a `type: "prompt"` expecting the small model to emit literal `PASS` — prose drift halted continuation after every successful bash.

**Fix upstream (template-repo PR #92):** Replaced with deterministic command hooks + test contract preventing recurrence.

## What changed

### Hook delivery (the unblock)
- `.claude/settings.base.json` + regenerated `.claude/settings.json` use **command hooks** for flow control
- New scripts:
  - `scripts/hook_protect_main.sh` + `scripts/hook_protect_main_impl.py` — blocks git commit/push on protected branches
  - `scripts/hook_sensitive_file_guard.sh` — blocks edits to `.env`, lockfiles, private keys, `archive/`, `secrets/`
  - `scripts/hook_bash_pre_tool.sh` — unified bash pre-tool hook
  - `tests/test_hook_scripts.py` — 97/101 tests pass locally (4 failures are Windows-only path-parsing edge cases, pre-existing upstream)

### Skill updates
- `.claude/skills/` directory enriched with new agent types (dependency-review, learner, orchestrate, post-merge, etc.)
- `.claude/agents/` documentation expanded
- `.claude/rules/` learned patterns structure initialized

### Minor agent fixes
- `github-issue-creator`, `new-project-setup`, `project-conventions` and others touched for template sync

## Commits in this PR

1. **e5b85d8** — chore: sync template to template-repo@061d9ab (template-2026.04) — main sync
2. **2e4943c** — chore(template-sync): fix CI failures and address review feedback — hook test gaps
3. **53bf74f** — fix(process-miner): enforce base64 validation in get_contents_text — guardrail for existing issue

## PR status (as of stop signal)

- **Number:** 87
- **State:** OPEN
- **Head:** 53bf74f (2026-04-24T20:49Z)
- **Reviewers:** Copilot (AI), chatgpt-codex-connector, cursor, gemini-code-assist, sourcery-ai — all commented

## Session work (2026-04-24)

1. Drafted PR summary explaining sync + root-cause fix
2. Pushed all 3 commits
3. Started cooldown timer (620s, deadline ~21:09Z) to allow CI to settle
4. **Session stopped before cooldown completed** — agent was waiting for background Monitor to signal completion

## Next steps for next session

1. **Wait for cooldown to complete** (deadline 2026-04-24T21:09:21Z, ~10 min after push watermark)
2. **Check CI status** on PR #87 via `gh pr checks 87`
3. If all checks pass: merge via auto-merge or manual merge if bot is blocked
4. If any check fails: diagnose and push fix commits
5. Once merged: run `post-merge` skill to update vault handoff (see SESSION_LIFECYCLE.md)

## Known issues

- Template-repo had pre-existing hook-test Windows path-parsing failures (non-blocking, upstream follow-up)
- 4 of 101 tests in `tests/test_hook_scripts.py` fail on Windows; all others pass

## Blockers / dependencies

- Cooldown timer was still running when session stopped
- CI status unknown (didn't get to check it)
