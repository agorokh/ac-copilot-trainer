---
name: dependency-review
description: Review Dependabot PRs, pip/pyproject bumps, GitHub Actions updates, MCP config changes, and security workflow bumps.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Dependency Review

This skill delegates to the `dependency-review` agent.

Load and follow the full agent definition at `.claude/agents/dependency-review.md`.

The agent handles: narrow review of dependency PRs (Dependabot, pip/pyproject, GitHub Actions, MCP config, security workflows), then hands off to `pr-resolution-follow-up`.
