---
type: invariant
status: active
created: 2026-05-17
updated: 2026-05-17
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/invariants/secrets-from-doppler.md
part_of: AcCopilotTrainer/00_System/invariants/_index.md
issue: "https://github.com/agorokh/template-repo/issues/115"
supersedes: AcCopilotTrainer/00_System/invariants/vault-is-only-memory.md
---

# Invariant: memory lives in three tiers

## Rule

All persistent project memory lives in **exactly one** of three declared tiers. **No side channels** (Claude Code per-user auto-memory, scratch databases, ad-hoc files that survive a session unless promoted into a tier).

| Tier | Substrate | Agent write path | Agent read path |
|---|---|---|---|
| **1** | [`AGENTS.md`](../../../../../AGENTS.md) + tier-1 changelog block | Direct `Edit` for short operational facts (commands, ports, learned preferences, policy updates) | Auto-loaded by Claude Code / Cursor at session start |
| **2** | [Vault](../../) at `docs/01_Vault/<ProjectKey>/` (Obsidian markdown graph; see [`00_Graph_Schema.md`](../../../../00_Graph_Schema.md)) | Direct `Write` / `Edit` of small linked nodes (decisions, investigations, invariants, glossary, handoffs) | `@`-included by `CLAUDE.md`; also indirectly via Tier-3 query (the substrate is built by re-ingesting Tier-2) |
| **3** | Per-workspace semantic substrate declared in [`ops/memory_manifest.yml`](../../../../../ops/memory_manifest.yml). Backend: `graphiti` (canonical) or `lightrag` (legacy). See [`MEMORY_SUBSTRATE.md`](../../../../00_Core/MEMORY_SUBSTRATE.md). | **Indirect.** The substrate ingests new vault notes on its cadence (`stale_after_hours` per workspace). Agents do **not** write to the substrate directly. | `mcp__agentic-memory__query_knowledge_graph(prompt, workspace=…)` + `mcp__agentic-memory__search_*`. **Read at LOAD is mandatory** for substantive sessions. |

## What is forbidden (side channels)

The following are NOT tiers and must not receive persistent writes:

- **Claude Code per-user auto-memory** (`~/.claude/projects/<slug>/memory/`) — disabled for this project. `scripts/hook_session_start_memory_redirect.py` writes a deprecation `README.md` + `DEPRECATED.txt` into that directory on every SessionStart so an agent that tries to write there sees the warning.
- **Scratch databases, per-user notes**, or ad-hoc files anywhere outside the three tiers — these are invisible to other agents, other sessions, teammates, and the Tier-3 ingest pipelines that consume vault content. `.scratch/` is **gitignored** and is for draft notes only; promote stable content into Tier 2 before ending the session.
- **Direct writes to the substrate's graph store** (Neo4j, vector indexes, etc.) bypassing the vault → ingest pipeline. The vault is the source of truth; the substrate is the queryable derivative.

## Why three tiers, not "vault only"

Three different access patterns, three different substrates:

1. **Tier 1** is for facts an agent must see *immediately* in turn 1 (versions, paths, learned preferences, fleet inventory pointers). Vault auto-includes are too long for this.
2. **Tier 2** is for *structured* knowledge with explicit graph edges (`relates_to`, `part_of`, `supersedes`). Investigations, ADRs, glossary, invariants.
3. **Tier 3** is for *semantic* retrieval — the agent doesn't know which vault node has the answer, only the prompt. A graph database + vector index over Tier-2 content gives sub-second recall across thousands of nodes.

Collapsing Tier 3 into "vault" misses the point. The vault is human-readable markdown. The substrate is what makes that markdown queryable at agent-loop speed. Dropping Tier 3 means agents re-discover the same context every session.

## Enforcement

- **`CLAUDE.md` override block** explicitly deprecates the auto-memory directory and enumerates all three tiers as the only sanctioned channels.
- **`scripts/hook_session_start_memory_redirect.py`** physically marks the auto-memory directory as deprecated on every session start.
- **`scripts/hook_session_start_memory_prefetch.py`** stamps `.scratch/.last_memory_query` after a Tier-3 query (HTTP to the workspace endpoint resolved from `ops/memory_manifest.yml`).
- **`scripts/hook_memory_gate.py`** (`PreToolUse` on `Edit | Write | Bash`) blocks code-path edits when the Tier-3 stamp is missing or stale. This is what catches **prompt-drift** (an agent that ignores the LOAD requirement in its system prompt cannot bypass the runtime check).
- **`scripts/hook_stop_save_reminder.py`** appends per-session records to `.scratch/memory_audit.jsonl` and surfaces an advisory when the stamp was never refreshed during a substantive session.
- **Routing rule** in [`AGENT_CORE_PRINCIPLES.md`](../../../../../AGENT_CORE_PRINCIPLES.md) § Architectural invariant gap: agents that catch themselves writing to a side channel must stop, file an `architectural-invariant-gap` issue against `template-repo`, and migrate the content to the appropriate tier.

## Rationale (postmortem)

A 2026-05-16 postmortem ([issue #115](https://github.com/agorokh/template-repo/issues/115); see also [`memory-enforcement-postmortem-2026-05-16.md`](../../02_Investigations/memory-enforcement-postmortem-2026-05-16.md)) catalogued an agent that wrote 6 "memories" to the auto-memory directory and consequently re-derived a credential strategy that already existed in the vault — and got it wrong. The substrate (Graphiti) was reachable but never queried. Documentation alone did not prevent the drift; runtime enforcement is mandatory.

## See also

- [`MEMORY_CONTRACT.md`](../../../../00_Core/MEMORY_CONTRACT.md) — the LOAD/SAVE protocol every agent operates under.
- [`MEMORY_SUBSTRATE.md`](../../../../00_Core/MEMORY_SUBSTRATE.md) — Tier-3 substrate detail (Graphiti vs LightRAG, workspace schema, ingest cadence).
- [`VAULT_TAXONOMY.md`](../../../../00_Core/VAULT_TAXONOMY.md) — `origin` classification (`repo-product` / `repo-embedded` / `human-curated`).
- [`secrets-from-doppler.md`](secrets-from-doppler.md) — sibling invariant from the same postmortem (no `.env` on deploy hosts).
