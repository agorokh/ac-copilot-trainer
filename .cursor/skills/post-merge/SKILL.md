---
name: post-merge
description: After a PR merges — sync main, clean branch, classify diff, update vault handoff. Use after merging a PR or when local main is behind origin.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Post-Merge Steward

Delegates to the `post-merge-steward` agent. Load and follow `.claude/agents/post-merge-steward.md`.

---

Keep aligned with `.claude/skills/post-merge/SKILL.md`. In Cursor, use `generalPurpose` Task per `.cursor/rules/cursor-task-delegation.mdc`.
