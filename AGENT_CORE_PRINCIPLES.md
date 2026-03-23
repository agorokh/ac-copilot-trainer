# Agent Core Principles

**Status:** Template  
**Version:** 1.0  
**Category:** Core

---

## Purpose

Every AI assistant (Cursor, Claude Code, Codex, Warp, GitHub Copilot agents) working in this repository must follow these principles. They are intentionally **domain-agnostic** — extend them in `AGENTS.md` and in the vault `Architecture Invariants` note.

---

## Issue-driven delivery

1. **Issue before code** — Work is scoped by a GitHub Issue (or equivalent tracked ticket) unless the user explicitly waives this for a trivial fix.
2. **PR-first** — Push a branch early and open a Draft PR; avoid long-lived local-only work.
3. **Branch names** — Use a consistent prefix: `feat/issue-123-short-name`, `fix/issue-456-...`, or tool-native forms your team documents in `AGENTS.md` (e.g. `cursor/...`). Never commit directly to `main`.

---

## Repository hygiene

1. **Canonical locations only** — No random new top-level folders; see `docs/10_Development/11_Repository_Structure.md`.
2. **No secrets in git** — Use `.env` locally; commit only `.env.example`. Do not paste tokens into Issues or PR descriptions.
3. **Scratch space** — Ephemeral experiments go under `.scratch/` (gitignored), not the vault and not production paths.
4. **Archive, do not sprawl** — Retire old code into `archive/` with a pointer in docs; do not leave duplicate “v2” trees at the root.

---

## Quality bar

1. **CI parity** — Run `make ci-fast` (or the documented equivalent) before requesting review.
2. **Tests follow behavior** — New logic in `src/` gets tests under `tests/` in the same PR when feasible.
3. **Fail fast** — Prefer explicit errors over silent fallbacks that hide incomplete migrations.
4. **Small, reviewable diffs** — One concern per PR when possible.

---

## GitHub review culture

1. **Bots are part of CI** — Address inline comments from automated reviewers (CodeRabbit, Bugbot, Copilot, etc.) or reply with a clear reason.
2. **Human review** — Respect CODEOWNERS and requested reviewers when configured.
3. **Scope proof** — When an Issue demands it, link evidence in the PR body (commands run, screenshots, logs redacted).

---

## Memory model

1. **Tier 1 — `AGENTS.md`** — Short, durable facts (commands, ports, policy changes).
2. **Tier 2 — Obsidian vault** — Architecture invariants, ADRs, investigations, handoffs under `docs/01_Vault/ProjectTemplate/` (rename on bootstrap).

Promote stable facts from Tier 1 into the vault when they become architectural.

---

## Pre-commit checklist

- [ ] Issue linked (or waiver noted).
- [ ] `make ci-fast` passes locally.
- [ ] No new forbidden top-level dirs (see `scripts/check_agent_forbidden.py`).
- [ ] Vault handoff updated if the session changed focus or left loose ends (`Next Session Handoff.md`).
