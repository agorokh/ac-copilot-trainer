---
name: post-merge
description: After a PR merges — sync main, clean branch, classify diff, update vault handoff. Use after merging a PR or when local main is behind origin.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Post-Merge Steward (Codex)

Delegates to the `post-merge-steward` agent. Load and follow `.claude/agents/post-merge-steward.md`.

This is the Codex mirror of `.claude/skills/post-merge/SKILL.md`. Behaviour
is identical across Claude Code, Cursor, Codex, and Antigravity surfaces.
The canonical source is `.claude/agents/post-merge-steward.md` — edit there,
not in any mirror.

In Codex, where the dedicated `post-merge-steward` agent type may not be
available, execute the procedure from the canonical agent doc inline using
the `Task` tool with whatever subagent type is supported.
