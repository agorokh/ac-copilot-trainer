# Memory substrate (Tier-3)

**Status:** Template
**Version:** 1.0
**Category:** Core
**Related:** [VAULT_TAXONOMY.md](VAULT_TAXONOMY.md), [SESSION_LIFECYCLE.md](SESSION_LIFECYCLE.md), [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml)

---

## What "substrate" means here

Tier-3 memory (the semantic graph that complements `AGENTS.md` and the Obsidian vault) is served by a **substrate**: a process or process-group that owns the graph store, the entity/relation extraction pipeline, and the retrieval surface that downstream agents call.

This template supports two substrates today. Each workspace in `ops/memory_manifest.yml` declares its substrate via the per-workspace `backend` field.

| Backend | Purpose | Default for new workspaces? |
|---|---|---|
| `graphiti` ([getzep/graphiti](https://github.com/getzep/graphiti)) | Bi-temporal entity-relation graph with automatic contradiction detection. One MCP server hosts all workspaces by `group_id`. | **Yes — canonical going forward.** |
| `lightrag` ([HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)) | Dual-level (entity + relation) retrieval over a per-workspace HTTP server. Mature ingest path for narrative vaults. | No — workspaces that exist on this backend persist until each is migrated to `graphiti`. |

There is **no perpetual sidecar**. The two-backend state is a migration window, not an end-state.

---

## Why the substrate choice matters

The two backends differ in three semantic dimensions that propagate to every consumer:

1. **Process topology**
   - `graphiti`: **one** MCP server process, **one** Neo4j connection, workspaces partitioned by per-call `group_id`. Fewer ports, less per-workspace ops, single blast-radius.
   - `lightrag`: **N** HTTP server processes (one per workspace) on distinct ports. Fault-isolated per workspace; more launchd plists.

2. **Temporal semantics**
   - `graphiti`: bi-temporal edges (`valid_at` / `invalid_at` + `created_at` / `expired_at`). Contradictions detected on ingest and resolved by stamping `invalid_at` on the loser; nothing is hard-deleted. Supports "what was true at time T" queries natively.
   - `lightrag`: append-mostly; no first-class temporal validity model. Time queries are not native.

3. **Retrieval shape**
   - `graphiti`: structured entity/edge results from `search_nodes` / `search_memory_facts`. Caller composes prose.
   - `lightrag`: prose RAG output with embedded reference lines. Mode parameter (`hybrid` / `mix` / `global` / `local` / `naive`) controls retrieval strategy.

These differences are why `ops/memory_manifest.yml` declares `canary_acceptance` per backend (the response shapes are not interchangeable) and why each workspace's `mode` field is backend-scoped vocabulary.

---

## When to use which

- **`graphiti` is the default for any new workspace.** It is the canonical substrate going forward. Choose it unless you have a concrete reason not to.
- **Choose `lightrag`** only when:
  - You are operating an existing `lightrag` workspace that has not yet been migrated, OR
  - You explicitly need LightRAG's mode vocabulary (`hybrid` / `mix` / `global` / `local` / `naive`) for a use case that has been validated against Graphiti's retrieval and demonstrably underperforms.

The bias is: new workspaces are born onto `graphiti`. Existing `lightrag` workspaces migrate forward, they do not retroactively re-establish themselves as legacy.

---

## Declaring a workspace

Every workspace lives as a row under a host in `ops/memory_manifest.yml`. The minimum required fields (v2) are:

`name`, `backend`, `origin`, `endpoint`, `vault_root`, `audit_log`, `launchd_label`, `stale_after_hours`, and at least one `canary_queries[]` entry (each with `prompt` and `mode`).

```yaml
- name: "<workspace_id>"
  backend: "graphiti"           # or "lightrag" if migrating an existing one
  origin: "repo-embedded"       # see VAULT_TAXONOMY.md
  endpoint: "http://localhost:8100" # graphiti: shared MCP URL; lightrag: per-workspace port
  vault_root: "~/path/to/vault"
  audit_log: "~/path/to/vault/.turbovault/audit/operations.jsonl"
  launchd_label: null           # graphiti: null; lightrag: ai.lightrag.ingest-audit.<name>
  stale_after_hours: 24
  canary_queries:
    - prompt: "<short probe relevant to this vault>"
      mode: "search_nodes"      # graphiti tool name OR lightrag mode
```

For `graphiti` workspaces, `launchd_label` is `null` (single shared process). For `lightrag` workspaces, `launchd_label` typically follows `ai.lightrag.ingest-audit.<workspace_name>`; use `null` when ingest is operator-managed externally (see `divorce_proceedings` in the live manifest).

For `graphiti` workspaces, the MCP `group_id` defaults to the workspace `name`. Override via manifest `graph_namespace` (consumers map that field to `group_id` on each Graphiti call).

---

## Substrate credentials

Tier-3 substrates (LightRAG, Graphiti, anything that runs programmatic LLM extraction at ingest time) consume LLM access through **DIAL**, not through raw OpenAI / Anthropic / Gemini API keys. Three-tier fallback (all live in Doppler):

| Tier | Doppler secret | Purpose |
|---|---|---|
| 1 (primary) | `DIAL_API_KEY_PROJECT` | Project-scoped key, larger token budget |
| 2 (fallback) | `DIAL_API_KEY` | Personal key, smaller budget |
| 3 (final fallback) | `OPENROUTER_API_KEY` | Diversification when DIAL itself is unreachable |

The base URL is `DIAL_BASE_URL` (verify exact var name in Doppler at use time).

**Mapping to third-party tools:** upstream Graphiti / LightRAG images often demand env vars literally named `OPENAI_API_KEY` and `OPENAI_API_URL`. Those are *name slots* the tool's code looks for — the *values* MUST be sourced from DIAL. Compose / shell mapping pattern:

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

## Migration discipline

When migrating a workspace from `lightrag` to `graphiti`:

1. Stand up the workspace in Graphiti (re-ingest via the file→episode reconciler — Graphiti has no LightRAG-graph importer).
2. Verify recall quality against the existing canary queries (translated to Graphiti's tool vocabulary).
3. Flip the `backend` value in `ops/memory_manifest.yml` in a single PR.
4. Retire the LightRAG launchd plist for that workspace.
5. Vault handoff: record the migration in the project's vault investigation log.

Do **not** leave a workspace ingesting into both substrates simultaneously — that creates the dual-write authority problem the substrate boundary is designed to avoid.

---

## Backward compatibility

Consumers that parse `ops/memory_manifest.yml` MUST:

- Treat a workspace with no `backend` field as `backend: "lightrag"` (the implicit v1 default).
- Treat a flat (un-nested) `canary_acceptance` block as `canary_acceptance.lightrag` (the v1 shape).
- Default missing `origin` to `null` and treat as "unclassified" without erroring.

This keeps v1 manifests parseable until every consumer adopts the v2 schema, and lets the migration roll out per-workspace rather than as a coordinated cut-over.

---

## See also

- [VAULT_TAXONOMY.md](VAULT_TAXONOMY.md) — what `origin` means and how it shapes ingest cadence
- [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml) — live manifest with the schema in use
- [`.claude/rules/memory-substrate.md`](../../.claude/rules/memory-substrate.md) — rule pointer for agents
- Graphiti MCP server: [getzep/graphiti/mcp_server](https://github.com/getzep/graphiti/tree/main/mcp_server)
