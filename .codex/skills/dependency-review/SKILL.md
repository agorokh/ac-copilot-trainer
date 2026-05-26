---
name: dependency-review
description: Review Dependabot PRs, pip/pyproject bumps, GitHub Actions updates, MCP config changes, and security workflow bumps.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Dependency review

**Canonical routing matrix:** `.claude/agents/issue-driven-coding-orchestrator.md` § Routing.

## Tier-3 Substrate Query (mandatory first step)

**Before scoring the dependency PR**, query the semantic substrate for prior risk decisions on the bumped package(s) and known CVE/security patterns. Dependency review without prior context is just GitHub-page reading; the substrate is where past incident scars live.

**Template** (starting point — refine after the first response):

```
mcp__agentic-memory__query_knowledge_graph(
    prompt="dependency <package-name> prior risk assessments | CVE history | supply-chain patterns | breaking-major fallout in this repo",
    workspace="<resolved from ops/memory_manifest.yml by repo basename>",
    limit=80,
)
```

**Refinement** (encouraged): after surveying the diff, follow up with queries naming the actual workflow / action / lockfile changes (e.g. *"prior `.github/workflows/security.yml` decisions on CVE allowlist scope"*).

**Workspace resolution**: read `ops/memory_manifest.yml`; match the workspace whose `name` matches this repo's basename. If no workspace, STOP and file an `architectural-invariant-gap` issue against `template-repo`.

**Surfacing**: include the substrate response under `## Pre-loaded substrate context` in your first reply, before producing the Risk summary / Merge order outputs.

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
3. **Hand off** — for **`sleep 600`**, required checks, and GraphQL **`reviewThreads`**, run **`.claude/agents/pr-resolution-follow-up.md`** or **`Task(subagent_type="pr-resolution-follow-up", …)`** (Claude Code); in Cursor use **`generalPurpose`** + that file’s checklist (`.cursor/rules/cursor-task-delegation.mdc`). Do **not** duplicate that loop here.

## Context discipline

- Read **only** touched manifest/workflow files plus the issue/PR body—no whole-repo grep for “all workflows.”
- Prefer official docs and workflow logs when a bumped **action** or **npm/py** package behavior is unclear; use **Context7** only when installed (otherwise official docs and targeted web search—do not block on Context7).

## Session lifecycle

- **LOAD:** Before reviewing, LOAD relevant vault context per `docs/00_Core/SESSION_LIFECYCLE.md` — at minimum skim `00_System/invariants/_index.md` and open **no-secrets** / **data-immutability** (or successor) nodes when the change touches credentials, scanners, or data paths.
- **SAVE:** After review, SAVE any merge-order decisions, risk assessments, or policy exceptions as small linked notes (vault graph or PR comment + handoff pointer per team practice).

## Guardrails

- No secrets in commits or PR bodies; rely on `AGENTS.md` and vault for policy detail.

<!-- memory-contract:start -->
<!-- DO NOT EDIT BY HAND. Re-render with: python3 scripts/merge_memory_contract.py -->

## Memory contract (pointer)

The substantive memory rules for this skill live in the file's **`## Tier-3 Substrate Query (mandatory first step)`** section above. They are placed before the procedure on purpose, so the agent reads them in execution order.

References:

- Canonical contract: [`docs/00_Core/MEMORY_CONTRACT.md`](../../../docs/00_Core/MEMORY_CONTRACT.md).
- Canonical invariant: [`memory-three-tiers.md`](../../../docs/01_Vault/AgentFactory/00_System/invariants/memory-three-tiers.md).
- Runtime enforcement: `scripts/hook_memory_gate.py` (PreToolUse gate blocks code-path edits without a fresh, file-relevant Tier-3 stamp). Stop-hook drift audit removed 2026-05-20 per slim-down ADR (#205).
- Kill switch: `CLAUDE_MEMORY_GATE=0` bypasses the gate; surface why in the vault SAVE so the next session can correct.

Originating postmortem: [template-repo#115](https://github.com/agorokh/template-repo/issues/115).

<!-- memory-contract:end -->
