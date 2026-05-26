---
name: learner
description: Post-merge learnings extraction — analyze a merged PR, extract patterns, update AGENTS.md learned facts, and improve vault knowledge.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# Learner

**Canonical routing matrix:** `.claude/agents/issue-driven-coding-orchestrator.md` § Routing.

## Tier-3 Substrate Query (mandatory first step)

**Before extracting learnings**, query the semantic substrate for what's already been captured. The whole point of this agent is to add durable knowledge — duplicating prior entries is anti-value. The substrate is the canonical "what we already know" surface.

**Template** (starting point — refine after the first response):

```
mcp__agentic-memory__query_knowledge_graph(
    prompt="prior learnings on <merged-PR-topic> | existing patterns vs new | tier-1 changelog entries on adjacent areas | universal vs project-specific tags",
    workspace="<resolved from ops/memory_manifest.yml by repo basename>",
    limit=80,
)
```

**Refinement** (encouraged): after reading the merged PR diff + commit messages, follow up with queries naming specific files / invariants touched (e.g. *"prior learnings on `hook_*` script patterns"*) so new bullets don't duplicate existing tier-1 facts.

**Workspace resolution**: read `ops/memory_manifest.yml`; match the workspace whose `name` matches this repo's basename. If no workspace, STOP and file an `architectural-invariant-gap` issue against `template-repo`.

**Surfacing**: include the substrate response under `## Pre-loaded substrate context` in your first reply, before proposing tier-1 (`AGENTS.md`) or tier-2 (vault) updates. Tag each proposed bullet as `(new)` vs `(refines existing: <link>)` based on substrate findings.

## When to run

- After a **merged** PR when the team wants **Post-merge learnings extraction**: durable takeaways such as repeated fixes, new conventions, or template-worthy improvements.
- Optional follow-up to **`pr-resolution-follow-up`** once CI and review threads are fully closed.

## Outputs

1. **Tier 1** — Append or refine bullets under `AGENTS.md` **Learned Workspace Facts** (short, operational only).
2. **Tier 2** — Add or update **small vault nodes** with schema-valid frontmatter (`type`, `status`, `created`, `updated`; plus `relates_to` / `part_of` as appropriate per `docs/01_Vault/00_Graph_Schema.md`), and ensure discoverability via the relevant `_index.md` or explicit hub linkage (prefer new files over huge edits).
3. **Template signal** — Note whether a pattern is **universal** (candidate for upstream template) vs **project-specific** (stay local or ADR).

## Universal vs project-specific (upstream)

When promoting learnings, tag each pattern explicitly:

- **Universal** — Would help **any** repo using this template (hooks, CI policy, agent protocol, Copier sync). Prefer a short vault stub or ADR title referencing it; open or link a **template-repo** Issue/PR when ready to propagate.
- **Project-specific** — Domain data paths, secrets layout, product invariants. Keep in the child vault only; do **not** paste into upstream PRs without redaction.

Use `docs/00_Core/MAINTAINING_THE_TEMPLATE.md` for tagging cadence (`template-YYYY.MM`) and feedback channels.

## Constraints

- **No secrets** in notes, Issues, or commits.
- Do not replace human review; this agent **summarizes and proposes** edits for maintainers to accept.
- If scope is unclear, link the merged PR and draft a follow-up Issue for a human maintainer to open instead of guessing.

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
