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

## Non-negotiables

1. Load issue context: `gh issue view <N> --json title,body,state,labels,comments`.
2. If closed or not found — stop.
3. Create a compliant branch (see `AGENTS.md`).
4. Open a **Draft PR** early; push frequently.
5. Follow `docs/10_Development/10_Agent_Protocol.md` for file placement.
6. Run `make ci-fast` before marking ready for review.
7. Invoke **`pr-resolution-follow-up`** (or execute the same loop yourself) until CI is green and bot threads are addressed.

## Planning

- Read vault `Architecture Invariants.md` before touching core modules.
- If scope is ambiguous, comment on the Issue with questions **before** large edits.

## Subagents / parallel exploration

Use repository exploration or specialized reviewers when the change crosses architectural boundaries. If a subagent name is unavailable in your tool, perform the same steps manually — **do not skip** invariant checks or PR hygiene.

## Done when

- CI passes on the PR
- Acceptance criteria in the Issue are met or explicitly deferred with a new Issue
- Vault handoff updated if work continues next session
