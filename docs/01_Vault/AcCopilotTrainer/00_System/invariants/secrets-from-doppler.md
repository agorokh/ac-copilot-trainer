---
type: invariant
status: active
created: 2026-05-17
updated: 2026-06-13
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
  - AcCopilotTrainer/00_System/invariants/memory-three-tiers.md
part_of: AcCopilotTrainer/00_System/invariants/_index.md
issue: "https://github.com/agorokh/template-repo/issues/115"
---

# Invariant: secrets and env from Doppler

## Rule

All deployed services and recurring scripts read secrets / env from **Doppler at process-start**. No `.env` files on deploy hosts (even uncommitted). `env_file:` is forbidden in production `compose.yml`. `launchd` plists wrap services with `doppler run --`. `.env.example` is a **key-name catalogue only** — never contains real values.

LLM-extraction substrates (Graphiti, LightRAG) consume DIAL via the three-tier fallback in [`MEMORY_SUBSTRATE.md`](../../../../00_Core/MEMORY_SUBSTRATE.md):

1. `DIAL_API_KEY_PROJECT` (primary, project-scoped)
2. `DIAL_API_KEY` (personal fallback)
3. `OPENROUTER_API_KEY` (last-resort diversification when DIAL unreachable)

A raw `OPENAI_API_KEY` sourced from a real OpenAI key **must never** appear in any substrate config, `.env`, ADR, or deploy bundle in this org.

## Scope (cross-repo boundary)

This invariant governs **this project's own deployed services** (its `launchd` units and recurring scripts, wrapped with `doppler run --`). The threat it prevents is a **rogue, uncontrolled `.env`** that *silently overrides* a correct Doppler substitution (the originating postmortem) — not a controlled projection.

A **co-located foreign-repo container** on a shared host — another project's compose service running on the same machine — that consumes a **Doppler-*projected*, operator-managed `.env`** follows **that repo's own sanctioned secret-consumption model**, *provided* **Doppler remains the canonical upstream** and the projection is **verifiable** against it (e.g. the on-disk value's hash matches Doppler). That controlled projection is a different posture from the rogue-override threat above. Do **not** hand-edit a foreign repo's host `.env` to repair such a secret — re-project via that repo's sanctioned path, and record the cross-repo reconciliation as an ADR in the owning project's vault.

## Rationale

A 2026-05-16 postmortem ([issue #115](https://github.com/agorokh/template-repo/issues/115); [agent-factory PR #164](https://github.com/agorokh/agent-factory/pull/164)) caught the production Graphiti deploy on `m2pro` silently routing all extraction calls through OpenRouter (not DIAL) for unknown duration because a `~/deploy/graphiti-mcp/.env` had overridden the compose's correct `AZURE_OPENAI_API_KEY=${DIAL_API_KEY_PROJECT:-${DIAL_API_KEY}}` substitution. Both fallbacks resolved empty; the OpenRouter key in the `.env` won by accident.

`.env` files on deploy hosts:

- Bypass Doppler rotation (silent stack drift over time).
- Accumulate copy-paste rot (the failing key in this incident was hand-pasted).
- Have no audit trail.
- Survive Doppler key rotation, leaving stale credentials in production.

## Enforcement

- **`make doppler-doctor`** (PR A) asserts: no `env_file:` directive in any tracked `compose.yml` under `ops/`; no `OPENAI_API_KEY=sk-` or `Bearer sk-` lines in non-`.env.example` repo files; `.env.example` contains key names only (no `=value` after `=`).
- Runtime probes per service: `make <service>-doctor` (e.g. `graphiti-doctor` in workstation-ops) assert canonical credential env vars are non-empty in the running container.
- Routing rule in `AGENTS.md`: "an architectural invariant gap detected, including `.env` discovery on a deploy host, **stops the current task** — file a `template-repo` issue using the `architectural-invariant-gap` template before resuming."

## See also

- [`MEMORY_SUBSTRATE.md`](../../../../00_Core/MEMORY_SUBSTRATE.md) § Substrate credentials.
- [`memory-three-tiers.md`](memory-three-tiers.md) — sibling invariant from the same postmortem.
- [`no-secrets.md`](no-secrets.md) — base no-secrets-in-source rule.
