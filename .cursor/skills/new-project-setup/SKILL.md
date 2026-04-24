---
name: new-project-setup
description: Run after copying this template into a new repo — bootstrap identity, vault, agent docs, GitHub MCP token, hooks, and CI verification. Use when the user says new project, bootstrap, from template, or /new-project-setup.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Edit, Bash
---

# New project setup

See `.claude/skills/new-project-setup/SKILL.md` — pointer pattern matching the rest of `.cursor/skills/`. Keep canonical content in the `.claude` copy; both must be edited together when the skill changes.

Includes a **Workstation service catalog** step that defers to [`docs/00_Core/BOOTSTRAP_NEW_PROJECT.md#workstation-service-catalog`](../../../docs/00_Core/BOOTSTRAP_NEW_PROJECT.md#workstation-service-catalog) (the single source of truth for the contract, schema, and `services: []` rule) and runs before the verify step.
