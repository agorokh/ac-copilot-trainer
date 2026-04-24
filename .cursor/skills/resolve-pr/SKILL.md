---
name: resolve-pr
description: Loop until a PR's CI is green and all review threads (human + bot) are resolved. Use after opening a PR or when asked to fix review comments.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# PR Resolution Follow-Up

Delegates to the `pr-resolution-follow-up` agent. Load and follow `.claude/agents/pr-resolution-follow-up.md`.

---

Keep aligned with `.claude/skills/resolve-pr/SKILL.md`. In Cursor, use `generalPurpose` Task per `.cursor/rules/cursor-task-delegation.mdc`.
