---
name: vault-memory
description: Manage persistent memory for this repo — Obsidian vault at docs/01_Vault/ProjectTemplate/ plus AGENTS.md tier-1 facts. Use when starting/ending sessions, after architecture changes, investigations, or when the user says vault, handoff, ADR, or project state.
---

# Vault Memory

Two-tier model:

| Tier | Location | Purpose |
|------|----------|---------|
| 1 | `AGENTS.md` | Short operational facts |
| 2 | `docs/01_Vault/ProjectTemplate/` | Structured notes, ADRs, handoffs |

Rename `ProjectTemplate` during project bootstrap (see `docs/00_Core/BOOTSTRAP_NEW_PROJECT.md`).

## Session start

1. `00_System/Next Session Handoff.md`
2. `00_System/Current Focus.md`
3. `00_System/Project State.md`

## Session end

Update `Next Session Handoff.md` with resume instructions, delivered work, remaining work, blockers.

## When to add an ADR

Use `99_Templates/Decision.md` in `01_Decisions/` when a design choice has alternatives and long-term consequences.

## When to add an investigation note

Use `99_Templates/Investigation.md` in `06_Investigations/` after non-trivial debugging or incident response.
