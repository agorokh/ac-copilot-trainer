---
paths:
  - ".claude/agents/**/*.md"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Orchestration (Claude Code agents)

**Canonical routing matrix:** `.claude/agents/issue-driven-coding-orchestrator.md` — issue type → primary agent → handoff → skills. Other agent files link there instead of duplicating the full table.

| Role | Agent file |
|------|------------|
| Issue → branch → Draft PR → implement → `make ci-fast` | `.claude/agents/issue-driven-coding-orchestrator.md` |
| Green CI + GraphQL `reviewThreads` + `sleep 600` | `.claude/agents/pr-resolution-follow-up.md` |
| Dependabot / workflows / `.mcp.json` risk + merge order | `.claude/agents/dependency-review.md` → then **pr-resolution-follow-up** for the bot loop |
| Post-merge pattern extraction (optional) | `.claude/agents/learner.md` |

**Delegation:** In **Claude Code**, use the **Task** tool with `subagent_type` set to the agent name (e.g. `pr-resolution-follow-up`, `dependency-review`, `learner`). Prose “invoke X” in agent markdown is the same contract. **In Cursor**, Task only allows `generalPurpose`, `explore`, `shell`, `best-of-n-runner` — use **`generalPurpose`** plus the checklist from the same agent markdown, or run steps inline (`.cursor/rules/cursor-task-delegation.mdc`).

**Skills (when to load)** — see `.claude/skills/*/SKILL.md` (mirrored under `.cursor/skills/` where present).

| Skill | Use |
|-------|-----|
| `vault-memory` | Session start/end, handoffs, ADRs, vault graph traversal |
| `project-conventions` | Ambiguous style/workflow; pointers to `AGENTS.md` / protocol |
| `ci-check` | Diagnosing CI / local check failures |
| `github-issue-creator` | Creating issues from templates |
| `new-project-setup` | After **Use this template** |
| `release-notes` | Maintainer release blurbs (user-invoked) |

**Context discipline:** Issue/PR **JSON from `gh` first**; then open only the files the task names. **Link** canonical docs instead of pasting them. Use **Context7** for third-party library facts; use the **vault** for *this* product’s decisions.
