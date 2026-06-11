---
paths:
  - ".claude/agents/**/*.md"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Orchestration (Claude Code agents)

**Canonical routing matrix:** `~/.agents/skills/orchestrate/SKILL.md` — issue type → primary agent → handoff → skills. Other agent files link there instead of duplicating the full table.

| Role | Agent file |
|------|------------|
| Issue → branch → Draft PR → implement → `make ci-fast` | `~/.agents/skills/orchestrate/SKILL.md` |
| Green CI + GraphQL `reviewThreads` + `sleep 600` | `~/.agents/skills/resolve-pr/SKILL.md` |
| Dependabot / workflows / `.mcp.json` risk + merge order | `~/.agents/skills/dependency-review/SKILL.md` → then **resolve-pr** for the bot loop |
| Post-merge pattern extraction (optional) | `~/.agents/skills/learner/SKILL.md` |
| After merge: sync main, classify diff, vault handoff | `~/.agents/skills/post-merge/SKILL.md` |

**Delegation:** In **Claude Code**, use the **Task** tool with `subagent_type` set to the agent name (e.g. `/resolve-pr`, `dependency-review`, `learner`). Prose “invoke X” in agent markdown is the same contract. **In Cursor**, Task only allows `generalPurpose`, `explore`, `shell`, `best-of-n-runner` — use **`generalPurpose`** plus the checklist from the same agent markdown, or run steps inline (`.cursor/rules/cursor-task-delegation.mdc`).

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
