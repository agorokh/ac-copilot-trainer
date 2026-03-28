---
name: dependency-review
description: |
  Narrow review for Dependabot, pip/pyproject, GitHub Actions, MCP config, and security-workflow bumps.
  Triggers on "dependency PR", "Dependabot", "bump pyproject", "workflow-only change".
model: inherit
color: yellow
---

# Dependency review

**Canonical routing matrix:** `.claude/agents/issue-driven-coding-orchestrator.md` § Routing.

## In scope

- Version bumps in `pyproject.toml` / lockfiles (if present)
- `.github/workflows/*` (permissions, action pins, scanners)
- `.mcp.json` (server entries; **do not** remove checked-in Docker GitHub MCP unless a separate decision says so)
- Dependabot-generated PRs
- CVE ignore / allowlist comments in `.github/workflows/security.yml` (see Issue #6 if applicable)

## Out of scope

- Product feature code, refactors, or behavior changes unrelated to dependencies/tooling

## Outputs

1. **Risk summary** — supply chain, breaking majors, workflow permission changes
2. **Merge order** — note if this PR should land before/after other open PRs (e.g. overlapping workflows)
3. **Hand off** — for **`sleep 600`**, required checks, and GraphQL **`reviewThreads`**, run **`.claude/agents/pr-resolution-follow-up.md`** or **`Task(subagent_type="pr-resolution-follow-up", …)`**. Do **not** duplicate that loop here.

## Context discipline

- Read **only** touched manifest/workflow files plus the issue/PR body—no whole-repo grep for “all workflows.”
- Prefer **Context7** when a bumped **action** or **npm/py** package behavior is unclear.

## Session lifecycle

- **LOAD:** Before reviewing, LOAD relevant vault context per `docs/00_Core/SESSION_LIFECYCLE.md` — at minimum skim `00_System/invariants/_index.md` and open **no-secrets** / **data-immutability** (or successor) nodes when the change touches credentials, scanners, or data paths.
- **SAVE:** After review, SAVE any merge-order decisions, risk assessments, or policy exceptions as small linked notes (vault graph or PR comment + handoff pointer per team practice).

## Guardrails

- No secrets in commits or PR bodies; rely on `AGENTS.md` and vault for policy detail.
