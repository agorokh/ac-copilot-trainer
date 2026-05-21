# Vault taxonomy (vault origin classification)

**Status:** Template
**Version:** 1.0
**Category:** Core
**Related:** [MEMORY_SUBSTRATE.md](MEMORY_SUBSTRATE.md), [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml)

---

## Why classify vault origin

Vaults in this ecosystem have different *natures* depending on how they come into being. The same retrieval substrate (Tier-3) serves all of them, but the **ingest cadence, the value of bi-temporal modeling, and the conflict-resolution policy differ by origin**. Naming the three categories explicitly lets every consumer reason about each vault correctly.

This is `origin` on the per-workspace row in [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml).

---

## The three origin types

### `repo-product`

The vault is a **build artifact** of another repository's content pipeline. Markdown is machine-generated from raw source (PDFs, scraped data, extracted entities, etc.). The source-of-truth is the input pipeline, not the vault itself.

- **Update pattern:** bulk-rebuild when source changes; rare, atomic, large.
- **Conflict semantics:** the rebuild replaces the prior vault snapshot wholesale; reconciliation happens at the pipeline boundary, not in the graph.
- **Bi-temporal value:** mostly cosmetic — facts don't evolve incrementally within the vault, they get re-emitted by a deterministic pipeline.
- **Examples:** `example_workspace_a` (built from court-filing PDFs by the `example_doc_pipeline` repo).

### `repo-embedded`

The vault **is** the repository's own documentation directory. Markdown lives in the same git history as the code; vault changes go through the same PR workflow as code changes.

- **Update pattern:** continuous high-frequency edits, deletes, renames via PRs; small, atomic, frequent.
- **Conflict semantics:** humans resolve via PR review; the vault is single-writer via the repo's branch protection.
- **Bi-temporal value:** **high** — facts about an evolving system get superseded constantly; "what did we believe on date X" is a real query.
- **Examples:** `agent_factory_steward` (this template's vault descendants), `alpaca_trading` (vault inside the trader repo).

### `human-curated`

The vault is an **operator-authored knowledge base** with mixed origins. Some entries are bulk-infused from external sources (papers, third-party knowledge dumps); others are manual notes; others are MCP-mediated structured imports. The operator (human) drives ingest cadence directly.

- **Update pattern:** mixed — periodic bulk infusions plus continuous manual edits.
- **Conflict semantics:** the operator is the single writer; conflicting facts resolved by hand (or by Tier-3's contradiction detection, surfaced for review).
- **Bi-temporal value:** **useful** — particularly for tracking when external knowledge was infused vs. when manual edits happened.
- **Examples:** `example_kb_workspace` (operator-curated knowledge base with client-content infusions and structured MCP imports), `example_demo_workspace` (operator-curated demo subset of `example_kb_workspace`).

---

## Consequences for substrate choice

The origin classification interacts with the substrate choice (see [MEMORY_SUBSTRATE.md](MEMORY_SUBSTRATE.md)):

| Origin | Best substrate (online) | Rationale |
|---|---|---|
| `repo-product` | `lightrag` (canonical) | Bulk rebuild works cleanly; LightRAG dual-level retrieval matches `repo-product` query patterns |
| `repo-embedded` | `lightrag` (canonical) — optionally backed by offline Graphiti metadata | Frequent edits + supersession benefit from bi-temporal metadata; under the [sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md), agents READ via LightRAG (`mcp__agentic-memory__*`); Graphiti runs OFFLINE to produce bi-temporal metadata that enriches LightRAG's chunk index |
| `human-curated` | `lightrag` (canonical) | Mixed write patterns work well with LightRAG's hybrid retrieval mode |

LightRAG is canonical online for every origin. Graphiti is offline-only — never on the agent read path — and is justified only when one of the sunset ADR's offline workflows (bi-temporal entity resolution, temporal drift detection, offline writeback validation) is required.

---

## Consequences for ingest cadence

`origin` also informs `stale_after_hours` in the manifest:

- `repo-product`: very generous (`168`+) — operator-driven bulk rebuilds, not continuous ingest.
- `repo-embedded`: tight (`24` or less) — vault edits should propagate within a working day.
- `human-curated`: medium (`24`–`72`) — operator drives cadence but ingest should keep up with bulk infusions.

---

## Adding a new vault

When registering a new workspace in `ops/memory_manifest.yml`:

1. Pick the `origin` that matches how the vault actually comes into being (not how you wish it did).
2. Pick `backend: "lightrag"` (canonical online default; see the [Graphiti sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md) — `graphiti` only for offline use).
3. Set `stale_after_hours` informed by `origin` per the table above.
4. Add at least one canary query relevant to the vault's content.

If unsure about origin, default to `human-curated` and revisit once the ingest pattern stabilizes.

---

## See also

- [MEMORY_SUBSTRATE.md](MEMORY_SUBSTRATE.md) — substrate selection and per-workspace declaration
- [BOOTSTRAP_NEW_PROJECT.md](BOOTSTRAP_NEW_PROJECT.md) §"8. Tier-3 semantic memory (optional)" — how to register a vault from scratch
- [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml) — the live schema
