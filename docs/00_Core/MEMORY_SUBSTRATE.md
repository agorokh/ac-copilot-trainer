# Memory substrate (Tier-3)

**Status:** Template
**Version:** 1.1
**Category:** Core
**Related:** [VAULT_TAXONOMY.md](VAULT_TAXONOMY.md), [SESSION_LIFECYCLE.md](SESSION_LIFECYCLE.md), [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml)

> **2026-05-17 substrate-selection sunset** ([Graphiti sunset ADR in agent-factory](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md)):
>
> - **LightRAG = canonical online substrate.** All agent reads via `mcp__agentic-memory__*` (which wraps LightRAG). Default for new workspaces.
> - **Graphiti = offline-only.** Retained for entity-resolution + bi-temporal metadata feeding LightRAG's chunk index. **Agents NEVER query Graphiti directly.**
> - **Substrate writes are indirect.** No write tool is exposed on the agent surface; the substrate is rebuilt by re-ingesting Tier-2 vault notes on cadence.

---

## What "substrate" means here

Tier-3 memory (the semantic graph that complements `AGENTS.md` and the Obsidian vault) is served by a **substrate**: a process or process-group that owns the graph store, the entity/relation extraction pipeline, and the retrieval surface that downstream agents call.

This template uses one canonical online substrate (LightRAG) plus an optional offline metadata layer (Graphiti). Each workspace in `ops/memory_manifest.yml` declares its substrate via the per-workspace `backend` field.

| Backend | Purpose | Default for new workspaces? |
|---|---|---|
| `lightrag` ([HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)) | Dual-level (entity + relation) retrieval over a per-workspace HTTP server. **Canonical online substrate.** All agent reads via `mcp__agentic-memory__*`. | **Yes — canonical.** |
| `graphiti` ([getzep/graphiti](https://github.com/getzep/graphiti)) | Bi-temporal entity-relation graph with automatic contradiction detection. **Offline-only after the 2026-05-17 sunset**: produces entity-resolution + bi-temporal metadata that feeds LightRAG's chunk index. Never on the agent read path. | No — offline use only. |

---

## Why the substrate choice matters

The two backends differ in three semantic dimensions:

1. **Process topology**
   - `lightrag`: **N** HTTP server processes (one per workspace) on distinct ports. Fault-isolated per workspace; one launchd plist per workspace.
   - `graphiti`: **one** MCP server process, **one** Neo4j connection, workspaces partitioned by per-call `group_id`. For OFFLINE entity-resolution use only.

2. **Temporal semantics**
   - `lightrag`: append-mostly chunk index; time-aware retrieval comes from bi-temporal metadata that Graphiti feeds in offline.
   - `graphiti`: bi-temporal edges (`valid_at` / `invalid_at` + `created_at` / `expired_at`). Used to produce metadata, **not** for online queries.

3. **Retrieval shape (agent-visible)**
   - `lightrag` via `mcp__agentic-memory__query_knowledge_graph`: prose RAG output with embedded reference lines + `references` array. Mode parameter (`hybrid` / `mix` / `global` / `local` / `naive`) controls retrieval strategy.
   - `graphiti`: **not exposed at the agent surface.** Its outputs land as metadata on LightRAG chunks via the ingest pipeline.

These differences are why `ops/memory_manifest.yml` declares `canary_acceptance` per backend and why each workspace's `mode` field is backend-scoped vocabulary.

---

## When to use which

- **`lightrag` is the canonical online substrate for every workspace.** All new workspaces are born onto LightRAG. All agent reads go through `mcp__agentic-memory__*`.
- **`graphiti` is retained only for offline workflows** that LightRAG cannot replicate (per the sunset ADR):
  - Bi-temporal entity resolution at ingest time
  - Temporal drift detection
  - Offline writeback validation

These offline outputs feed LightRAG's chunk metadata. Agents never see them as Graphiti queries; they see them as enriched LightRAG retrieval results.

---

## Declaring a workspace

Every workspace lives as a row under a host in `ops/memory_manifest.yml`. The minimum required fields (v2) are:

`name`, `backend`, `origin`, `endpoint`, `vault_root`, `audit_log`, `launchd_label`, `stale_after_hours`, and at least one `canary_queries[]` entry (each with `prompt` and `mode`).

```yaml
- name: "<workspace_id>"
  backend: "lightrag"           # canonical online; "graphiti" only for offline workspaces (per sunset ADR)
  origin: "repo-embedded"       # see VAULT_TAXONOMY.md
  endpoint: "http://localhost:8060" # per-workspace LightRAG port
  vault_root: "~/path/to/vault"
  audit_log: "~/path/to/vault/.turbovault/audit/operations.jsonl"
  launchd_label: "ai.lightrag.ingest-audit.<name>" # null when ingest is operator-managed externally
  stale_after_hours: 24
  canary_queries:
    - prompt: "<short probe relevant to this vault>"
      mode: "hybrid"            # lightrag retrieval mode
```

For `lightrag` workspaces, `launchd_label` typically follows `ai.lightrag.ingest-audit.<workspace_name>`; use `null` when ingest is operator-managed externally.

---

## Substrate credentials

Tier-3 substrates (LightRAG, Graphiti, anything that runs programmatic LLM extraction at ingest time) consume LLM access through **DIAL**, not through raw OpenAI / Anthropic / Gemini API keys. Three-tier fallback (all live in Doppler):

| Tier | Doppler secret | Purpose |
|---|---|---|
| 1 (primary) | `DIAL_API_KEY_PROJECT` | Project-scoped key, larger token budget |
| 2 (fallback) | `DIAL_API_KEY` | Personal key, smaller budget |
| 3 (final fallback) | `OPENROUTER_API_KEY` | Diversification when DIAL itself is unreachable |

The base URL is `DIAL_BASE_URL` (verify exact var name in Doppler at use time).

**Mapping to third-party tools:** upstream LightRAG / Graphiti images often demand env vars literally named `OPENAI_API_KEY` and `OPENAI_API_URL`. Those are *name slots* the tool's code looks for — the *values* MUST be sourced from DIAL. Compose / shell mapping pattern:

```bash
OPENAI_API_KEY=${DIAL_API_KEY_PROJECT:-${DIAL_API_KEY:?DIAL credential required}}
OPENAI_API_URL=${DIAL_BASE_URL}/v1
```

Or wrap the launch:

```bash
doppler run --project ag-dev-ecosystem --config dev_work -- docker compose up -d
```

**Interactive agent loops are different.** Conversational agents (Codex via ChatGPT subscription, Gemini, Claude/Anthropic) consume the operator's subscriptions via Hermes shims (`chatgpt-projects`, `gemini-sub`, `anthropic-dial-adapter`, `claude_dial*` wrappers). Those shims own credential acquisition and are out of scope for *substrate* configuration; this section covers ingestion-time credentials only.

**Hard rule:** a raw `OPENAI_API_KEY` sourced from a real OpenAI key MUST NEVER appear in any substrate config, .env, ADR, or deploy bundle in this org.

---

## Sunset migration discipline

Workspaces that were on `backend: graphiti` during the migration window are being reverted to `backend: lightrag` per the sunset ADR. Any new offline-use Graphiti deployments (entity-resolution, bi-temporal metadata pipelines) follow these rules:

1. Mark the workspace `backend: graphiti` ONLY for an offline use case justified by the sunset ADR's offline-workflow criteria.
2. Add a `notes` field referencing the sunset ADR + the specific offline workflow.
3. The agent-facing read path remains `mcp__agentic-memory__*` pointed at the LightRAG instance that consumes Graphiti's offline output.
4. Verify the LightRAG canary still passes with the Graphiti-derived metadata in place.

Do **not** add a Graphiti workspace to the agent's MCP connection list; it must remain off the read path. **Transitional exception:** rows in `ops/memory_manifest.yml` that still declare `backend: graphiti` as unprovisioned placeholders (see the manifest comment block) are not agent read targets—the SessionStart prefetch may probe them and records a `missing` marker until workstation-ops flips each row to `lightrag`.

---

## Backward compatibility

Consumers that parse `ops/memory_manifest.yml` MUST:

- Treat a workspace with no `backend` field as `backend: "lightrag"` (the canonical default).
- Treat a flat (un-nested) `canary_acceptance` block as `canary_acceptance.lightrag` (the legacy v1 shape).
- Default missing `origin` to `null` and treat as "unclassified" without erroring.

**Strict mode (recommended for fleet health checks):** `scripts/check_memory_manifest.py` (wired into `ci_policy`) **fails** when a workspace row omits `backend`, uses an unknown value, or declares `graphiti` without `notes`. Manifest *parsers* may still default omitted `backend` to `lightrag` for backward compatibility when reading legacy files, but the SessionStart hook **does not** default at runtime — omitted `backend` skips HTTP prefetch and stamps `.scratch/.last_memory_query.missing`. The hook only issues HTTP reads when `backend == "lightrag"`; `graphiti` rows (including sunset placeholders) never hit the agent read path — see `tests/test_hook_session_start_memory_prefetch.py::test_graphiti_backend_writes_missing_marker` and `test_missing_backend_skips_prefetch`.

---

## See also

- [VAULT_TAXONOMY.md](VAULT_TAXONOMY.md) — what `origin` means and how it shapes ingest cadence
- [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml) — live manifest with the schema in use
- [`.claude/rules/memory-substrate.md`](../../.claude/rules/memory-substrate.md) — rule pointer for agents
- LightRAG: [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)
- Graphiti (offline-only): [getzep/graphiti/mcp_server](https://github.com/getzep/graphiti/tree/main/mcp_server) — see [Graphiti sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md) in agent-factory
