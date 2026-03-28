# Agent Core Principles

**Status:** Template
**Version:** 1.2
**Category:** Core

---

## Purpose

Every AI assistant (Cursor, Claude Code, Codex, Warp, GitHub Copilot agents) working in this repository must follow these principles. They are intentionally **domain-agnostic** — extend them in `AGENTS.md` and in the vault **invariants** graph (`00_System/invariants/_index.md`, via `Architecture Invariants.md`).

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

## Issue design — group by file overlap (mandatory)

**Rule:** When creating multiple issues for related work, **group by files touched**, not by feature concept.

- **Before creating issues:** Map out which source files each planned change will modify. If two features touch overlapping modules, they belong in **one issue** with labeled Parts (Part 1, Part 2, …).
- **Why:** Separate issues on overlapping files create merge conflicts, fragment code review context, and force coding agents to re-read the same modules. Code-review agents also lose the full picture when goals are split across PRs that touch the same code.
- **Decision:** "Should this be a separate issue?" → Only if the files touched are **disjoint** from all other planned issues. If files overlap, consolidate.

---

## Quality bar

1. **CI parity** — Run `make ci-fast` (or the documented equivalent) before requesting review.
2. **Tests follow behavior** — New logic in `src/` gets tests under `tests/` in the same PR when feasible.
3. **Fail fast** — Prefer explicit errors over silent fallbacks that hide incomplete migrations.
4. **Small, reviewable diffs** — One concern per PR when possible.

---

## Operational culture

1. **Own every failure** — Never characterize a bug or gap as "pre-existing" or blame the past. If it's broken in this repo, own it and fix it in the current session.
2. **Preserve manual work** — Pipeline rebuilds, code generation, and bulk operations must never delete or overwrite user-created content (workbenches, curated notes, manual configurations). Verify guards (e.g. `skip_if_unchanged`, protected directories) before bulk operations.
3. **PR merge order** — When multiple PRs are open, merge the simpler/lower-risk one first, then rebase and merge the next. Check for file overlaps (CHANGELOG, docs/) that need trivial conflict resolution.

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

---

## Upstream template sync

**If you are working in a project created *from* the organization template:** when you improve a **domain-agnostic** workflow (issue design, hooks, skills, agent protocol, CI policy), propagate it back to the **canonical template** repository:

1. **Decide:** Is this principle domain-specific (only this product) or universal (any new repo)?
2. **If universal:** After merge, remind the maintainer: *"Should we propagate this to the template?"*
3. **If yes:** Open an Issue/PR on the template with the generalized wording (no secrets, no product-only paths).
4. **Never propagate:** Domain data, credentials, customer info, proprietary business logic.

**If you are editing the template repository itself:** merge improvements directly here; record notable governance changes in [docs/00_Core/MAINTAINING_THE_TEMPLATE.md](docs/00_Core/MAINTAINING_THE_TEMPLATE.md) (optional tag, e.g. `template-YYYY.MM`).
