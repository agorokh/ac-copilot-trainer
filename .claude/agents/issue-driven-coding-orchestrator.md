---
name: issue-driven-coding-orchestrator
description: |
  End-to-end delivery from a single GitHub issue number: branch, draft PR, implementation, tests/docs,
  make ci-fast, then hand off to PR resolution until green. Triggers on "implement issue #N",
  "orchestrate issue N", or a lone issue number after asking for the orchestrator.
model: inherit
color: blue
memory: project
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
| Post-merge learnings extraction (optional) | `learner` | — | `vault-memory`; updates `AGENTS.md` tier-1 + small vault nodes |
| Post-merge: sync, classify, vault update | `post-merge-steward` | — | `vault-memory`; `scripts/post_merge_sync.sh`, `scripts/post_merge_classify.py` |

**Rules**

- One **primary** owner per goal; secondaries are **handoffs**, not parallel owners of the same branch.
- **Skills** are shortcuts—link `.claude/skills/<name>/SKILL.md` rather than pasting long procedures into chat.
- **Delegate** explicitly: in **Claude Code**, use the **Task** tool with `subagent_type` **`pr-resolution-follow-up`**, **`dependency-review`**, or **`learner`** when the host supports it. **In Cursor**, Task only accepts **`generalPurpose`**, **`explore`**, **`shell`**, **`best-of-n-runner`** — use **`generalPurpose`** with the same checklist embedded from the linked `.claude/agents/*.md`, or follow that markdown step-for-step inline (see `.cursor/rules/cursor-task-delegation.mdc`).

## Context discipline (tokens)

1. **`gh issue view <N> --json title,body,state,labels,comments`** first—contract is title/body/comments before codebase search.
2. **Pointer over paste:** link `AGENTS.md`, `10_Agent_Protocol.md`, vault paths; do not dump whole files into the prompt.
3. **Search after scope:** use targeted search/semantic exploration only once you know subsystem (package, workflow name); avoid repo-wide grep loops with tiny query variants.
4. **Third-party APIs:** prefer **Context7** MCP (see `.mcp.json`, `.claude/rules/context7.md`) over guessing library behavior.

## Non-negotiables

1. **Session lifecycle:** LOAD vault context per `docs/00_Core/SESSION_LIFECYCLE.md` before routing or implementation decisions; SAVE (update `Next Session Handoff.md`, add/update small linked vault nodes as needed) after completion **or failure**.
2. Load issue context: `gh issue view <N> --json title,body,state,labels,comments`.
3. If closed or not found — stop.
4. If the issue is **dependency/tooling-only** (Dependabot, “bump X”, workflow-only), prefer spawning **`dependency-review`** (Task or manual follow) before treating it as a feature build.
5. Create a compliant branch (see `AGENTS.md`).
6. Open a **Draft PR** early; push frequently.
7. Follow `docs/10_Development/10_Agent_Protocol.md` for file placement.
8. Read vault `00_System/invariants/_index.md` and load targeted invariant nodes before touching core modules.
9. Run `make ci-fast` before marking ready for review.
10. **Mark the PR ready for review:** use pull request number **P** (from the PR you opened; it can differ from issue **N**): `gh pr ready <P> --repo <owner/repo>` (exits draft state so reviewers and bots are notified).
11. **Wait for async bots before handoff:** follow **§ Mandatory wait after each push** in `.claude/agents/pr-resolution-follow-up.md`—use the same **`sleep 600`** cooldown after `gh pr ready` as after a `git push` (that section owns the normative wait; do not skip it).
12. Hand off to **PR resolution** using the same pull request number **P** as in step 10: in Claude Code invoke **`Task(subagent_type="pr-resolution-follow-up", …)`**; in Cursor use **`Task(subagent_type="generalPurpose", …)`** with the **pr-resolution-follow-up** checklist from `.claude/agents/pr-resolution-follow-up.md`, or execute that file’s steps inline until CI is green and bot threads are addressed.

## Planning

- If scope is ambiguous, load **`project-conventions`** or read **`AGENTS.md`** + **`docs/10_Development/10_Agent_Protocol.md`**, or comment on the Issue with questions **before** large edits.

## Subagents / parallel exploration

Use repository exploration or specialized reviewers when the change crosses architectural boundaries. If a subagent name is unavailable in your tool, perform the same steps manually — **do not skip** invariant checks or PR hygiene.

## Done when

- PR is **not** in draft state (marked ready via `gh pr ready <P> --repo <owner/repo>`)
- CI passes on the PR
- Acceptance criteria in the Issue are met or explicitly deferred with a new Issue
- Vault handoff updated if work continues next session
