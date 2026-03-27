---
name: issue-driven-coding-orchestrator
description: |
  End-to-end delivery from a single GitHub issue number: branch, draft PR, implementation, tests/docs,
  make ci-fast, then hand off to PR resolution until green. Triggers on "implement issue #N",
  "orchestrate issue N", or a lone issue number after asking for the orchestrator.
model: inherit
color: blue
---

# Issue-Driven Coding Orchestrator

**Input:** one GitHub issue number for **this** repository.

**Canonical routing matrix:** this file owns § **Routing** below. Other agents link here instead of duplicating the full table.

## Routing

| Trigger / issue type | Primary agent | Secondary (handoff) | Skills & tools (load as needed) |
|----------------------|---------------|---------------------|-----------------------------------|
| Implement feature / docs / refactor from an Issue | **This orchestrator** | `.claude/agents/pr-resolution-follow-up.md` once a PR exists | `vault-memory` (session + handoff); `project-conventions` when workflow/style is ambiguous; else `AGENTS.md` + `10_Agent_Protocol.md`; explore/review subagents for cross-cutting unknowns |
| Green CI + resolve bot/human review threads on an open PR | `pr-resolution-follow-up` | — | Same PR agent doc; optional `ci-check` skill when diagnosing failures |
| Dependabot / deps-only / workflows / `.mcp.json` / `security.yml` bumps | `dependency-review` | `pr-resolution-follow-up` for `sleep 600` + GraphQL `reviewThreads` loop | Read touched files only; do not duplicate the PR loop in `dependency-review` |
| New repo from template | Human or `new-project-setup` skill | — | `new-project-setup` |
| Maintainer release blurb / tag notes | Human | — | `release-notes` skill; see `docs/00_Core/MAINTAINING_THE_TEMPLATE.md` § Versioning |

**Rules**

- One **primary** owner per goal; secondaries are **handoffs**, not parallel owners of the same branch.
- **Skills** are shortcuts—link `.claude/skills/<name>/SKILL.md` rather than pasting long procedures into chat.
- **Delegate** explicitly: use the **Task** tool with `subagent_type` **`pr-resolution-follow-up`** or **`dependency-review`** when the host supports it; otherwise follow the linked agent markdown step-for-step.

## Context discipline (tokens)

1. **`gh issue view <N> --json title,body,state,labels,comments`** first—contract is title/body/comments before codebase search.
2. **Pointer over paste:** link `AGENTS.md`, `10_Agent_Protocol.md`, vault paths; do not dump whole files into the prompt.
3. **Search after scope:** use targeted search/semantic exploration only once you know subsystem (package, workflow name); avoid repo-wide grep loops with tiny query variants.
4. **Third-party APIs:** prefer **Context7** MCP (see `.mcp.json`, `.claude/rules/context7.md`) over guessing library behavior.

## Non-negotiables

1. Load issue context: `gh issue view <N> --json title,body,state,labels,comments`.
2. If closed or not found — stop.
3. If the issue is **dependency/tooling-only** (Dependabot, “bump X”, workflow-only), prefer spawning **`dependency-review`** (Task or manual follow) before treating it as a feature build.
4. Create a compliant branch (see `AGENTS.md`).
5. Open a **Draft PR** early; push frequently.
6. Follow `docs/10_Development/10_Agent_Protocol.md` for file placement.
7. Read vault `Architecture Invariants.md` before touching core modules.
8. Run `make ci-fast` before marking ready for review.
9. Hand off to **PR resolution**: invoke **`Task(subagent_type="pr-resolution-follow-up", …)`** or execute `.claude/agents/pr-resolution-follow-up.md` until CI is green and bot threads are addressed.

## Planning

- If scope is ambiguous, load **`project-conventions`** or read **`AGENTS.md`** + **`docs/10_Development/10_Agent_Protocol.md`**, or comment on the Issue with questions **before** large edits.

## Subagents / parallel exploration

Use repository exploration or specialized reviewers when the change crosses architectural boundaries. If a subagent name is unavailable in your tool, perform the same steps manually — **do not skip** invariant checks or PR hygiene.

## Done when

- CI passes on the PR
- Acceptance criteria in the Issue are met or explicitly deferred with a new Issue
- Vault handoff updated if work continues next session
