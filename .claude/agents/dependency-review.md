---
name: dependency-review
description: |
  Narrow review for Dependabot, pip/pyproject, GitHub Actions, MCP config, and security-workflow bumps.
  Triggers on "dependency PR", "Dependabot", "bump pyproject", "workflow-only change".
model: inherit
color: yellow
---

# Dependency review

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
3. **Follow-up loop** — for CI + bot threads and the `sleep 600` / GraphQL `reviewThreads` workflow, use **`.claude/agents/pr-resolution-follow-up.md`** (do not duplicate that doc here)

## Guardrails

- No secrets in commits or PR bodies; rely on `AGENTS.md` and vault for policy detail.
