---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-03-28
relates_to:
  - ProjectTemplate/00_System/Current Focus.md
  - ProjectTemplate/00_System/Project State.md
  - ProjectTemplate/00_System/invariants/_index.md
  - ProjectTemplate/00_System/glossary/_index.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here

- **PR #29** (`feat/issue-15-agent-self-learning`, **open**, not draft): confirm **`headRefOid`** on GitHub. As of last pr-resolution pass: required checks + CodeRabbit + Bugbot green; GraphQL **`reviewThreads`**: **0** blocking (`isResolved: false` ∧ `isOutdated: false`). **`learner`** agent uses **`model: inherit`** (Bugbot: shorthand `haiku` breaks spawned agents); CodeRabbit thread on pinning `haiku` **replied + resolved** with rationale. Next: human merge when satisfied; optional **`learner`** post-merge per #15.
- Next parallel track per graph: **#21** (Tier 1+2), **#27** (template sync); **#26** after #21.

## What was delivered

- #15 scope: project memory on orchestration agents, `learner` agent, skill `allowed-tools`, SessionStart / Stop / PostToolUse Bash hooks, vault + orchestration rules, shorter `CLAUDE.md`, digest-pinned GitHub MCP (`.mcp.json` + `.cursor/mcp.json`), pytest-cov + bandit in `ci-fast`, docs (WARP, TOOLCHAIN, MAINTAINING, GITHUB_SETUP, glossary `ci-fast`). **PR:** https://github.com/agorokh/template-repo/pull/29

## What remains

- Merge **#29** for #15 when maintainer marks ready; optionally run **`learner`** post-merge for template-wide notes.
- Continue #14 children (#21, #26, #27) as separate issues/branches.

## Blockers

- None. If Stop hook `timeout: 60000` behaves incorrectly in Claude Code (seconds vs ms), confirm against upstream hook docs and adjust.
