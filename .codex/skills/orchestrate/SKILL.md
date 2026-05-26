---
name: orchestrate
description: End-to-end issue delivery — branch, draft PR, implement, tests, CI, then hand off to PR resolution. Use when asked to implement an issue or given an issue number.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Issue-Driven Coding Orchestrator

**Input:** one GitHub issue number for **this** repository.

**Canonical routing matrix:** this file owns § **Routing** below. Other agents link here instead of duplicating the full table.

## Tier-3 Substrate Query (mandatory first step)

**Before any other action** — before reading the issue, before routing, before branch creation — query the semantic substrate for prior context. The runtime gate (`scripts/hook_memory_gate.py`) blocks code-path edits without a fresh substrate stamp, but the gate fires AFTER the agent has internalized the issue. Without this explicit step the agent pattern-matches the issue cold and drifts before the gate has anything to enforce against.

**Template** (starting point — refine after the first response):

```
mcp__agentic-memory__query_knowledge_graph(
    prompt="issue #<N>: <issue title> | <key terms from body> | prior decisions on touched modules",
    workspace="<resolved from ops/memory_manifest.yml by repo basename>",
    limit=80,
)
```

**Refinement** (encouraged): the template above is the floor, not the ceiling. After the first response, issue follow-up queries naming the specific architectural concerns the issue surfaces — invariants touched, related investigations, similar past issues. Each query refreshes the gate stamp.

**Workspace resolution**: read `ops/memory_manifest.yml`; find the workspace whose `name` matches this repo's basename (e.g. `template_repo` for `template-repo/`; `agent_factory_steward` for `agent-factory/`). If no workspace is registered, **STOP** and file an `architectural-invariant-gap` issue against `template-repo` before proceeding — the substrate gap is itself a propagation invariant.

**Surfacing**: include the substrate response (verbatim, or summarized when long) under a `## Pre-loaded substrate context` heading in your first substantive reply, **before** routing decisions or branch creation. This makes Tier-3 context visible to operators and to any Task-spawned subagents you spawn later.

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
4. **Third-party APIs:** prefer official docs and targeted web search; use **Context7** MCP only when installed (otherwise do not block on it—see `.claude/rules/context7.md`, [workstation-reference.md](../../docs/01_Vault/AgentFactory/00_System/workstation-reference.md)).

## Non-negotiables

1. **Tier-3 memory query** (mandatory first step): execute the call template from § **Tier-3 Substrate Query** above. The vault LOAD per `docs/00_Core/SESSION_LIFECYCLE.md` (handoff → `relates_to` subgraph → invariants index) is the **second** step — Tier-3 substrate query and vault LOAD are complementary, not alternatives. SAVE (update `Next Session Handoff.md`, add/update small linked vault nodes as needed) after completion **or failure**.
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
13. **Fresh file reads before edits:** before substantive **Edit**/**Write** on paths you will change, load current contents for those targets (in Claude Code use **`query_file_patterns`** with those paths; in other tools use an equivalent bulk read) so patches apply to the latest revisions.

## Planning

- If scope is ambiguous, load **`project-conventions`** or read **`AGENTS.md`** + **`docs/10_Development/10_Agent_Protocol.md`**, or comment on the Issue with questions **before** large edits.

## Subagents / parallel exploration

Use repository exploration or specialized reviewers when the change crosses architectural boundaries. If a subagent name is unavailable in your tool, perform the same steps manually — **do not skip** invariant checks or PR hygiene.

### Subagent memory propagation (mandatory)

Subagents spawned via the `Task` tool **do not auto-load** `CLAUDE.md` — the orchestrator MUST embed memory context in the Task prompt. Otherwise the subagent operates blind to the vault and Tier-3 substrate, and the gate (`scripts/hook_memory_gate.py`) blocks any code-path edit it attempts. Concrete template for every `Task(prompt=…)`:

```
## Pre-loaded memory context

Vault handoff: <one-paragraph summary or verbatim from SessionStart hook output>
Tier-3 prefetch (workspace: <name>): <verbatim from hook_session_start_memory_prefetch.py stdout>
Memory contract: docs/00_Core/MEMORY_CONTRACT.md (loaded contract authoritative)

## Your task

<the actual task here>
```

If the prefetch was empty or the workspace was missing, **say so explicitly** in the subagent's prompt (`Tier-3 prefetch: empty — see CLAUDE_MEMORY_GATE degraded mode`) so the subagent doesn't waste turns re-querying a known-empty workspace.

## Done when

- PR is **not** in draft state (marked ready via `gh pr ready <P> --repo <owner/repo>`)
- CI passes on the PR
- Acceptance criteria in the Issue are met or explicitly deferred with a new Issue
- Vault handoff updated if work continues next session

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
