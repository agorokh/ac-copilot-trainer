---
type: decision
status: active
memory_tier: canonical
created: 2026-06-29
updated: 2026-06-29
relates_to:
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/01_Decisions/curated-setup-as-data-platform-entity-2026-06-28.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/invariants/persistence.md
---

# Embedded DuckDB (not ClickHouse) for AC analytics storage

## Context

A recurring question: AC copilot uses **embedded DuckDB** as its analytics store,
while the rest of the fleet defaults to **ClickHouse**. Why the divergence — and is
it because DuckDB is "embedded and faster for voice coaching"? This node records the
rationale so the trade-off is not re-litigated each session.

**Two premises corrected up front:**

1. **DuckDB is offline-only — it is NOT on the voice/realtime path.** The lakehouse
   build is "**46s offline (not on the realtime path)**" ([[coaching-lakehouse-duckdb-2026-06-28]]).
   Voice latency is solved by a different mechanism entirely (below).
2. **There was no head-to-head DuckDB-vs-ClickHouse trade study.** ClickHouse appears
   **nowhere** in this repo (`grep -rinE "clickhouse"` → 0 hits). DuckDB was chosen for
   a job ClickHouse was never a candidate for; this node reconstructs the *why* from the
   recorded properties + architecture invariants, not from a prior bench-off.

## What DuckDB actually does here

`tools/coaching_lake` — an embedded DuckDB **star schema** (`laps` / `corners` /
`setup_params` / `samples`) built **idempotently from the immutable per-lap JSON corpus**
(`journal/laps/lap_*.json`). Purpose: **cross-lap trend/dependency questions** no single
lap can answer (e.g. *does +1° front wing improve T1 apex speed across all my Spa laps?*).
Declared as the optional `analytics` extra (`duckdb>=1.4` in `pyproject.toml`); the same
engine LEFT-JOINs the JSONL setup catalog onto driven laps
([[curated-setup-as-data-platform-entity-2026-06-28]]). It is a **batch analytics brain,
not a hot-path store**.

## What makes voice coaching fast (it is NOT DuckDB)

The voice path uses **no database in the loop** ([[voice-coach-architecture-2026-06-28]]):
a **pre-rendered phrase bank** (baked WAV + content-addressed manifest) gives
deterministic, **sub-50 ms, zero-GPU** playback; the realtime brain feeding it is
**pure-stdlib streaming** (`tools/ai_sidecar/realtime_observer.py`), in-process, no query
engine. So "DuckDB is faster for voice coaching" conflates two layers that never touch.

## Decision drivers (deployment topology + invariants, not query speed)

| Constraint in AC copilot | DuckDB fits | ClickHouse does not |
|---|---|---|
| Runs **on the sim rig** — one Windows PC saturating GPU/CPU on AC+CSP | Embedded, **server-less, single pip wheel, Windows + py3.11 native**, in-process | A server to run/operate/keep alive on an already-saturated single-user box |
| **Immutable JSON corpus is source of truth** ([[data-immutability]], [[persistence]]) | DuckDB file is a **derived, disposable view** rebuilt from JSON; JSON never mutated | Wants ETL into a long-lived authoritative store — fights the invariant |
| Scale **~213 laps / 375k samples** (megabytes) | DuckDB's sweet spot — laptop-scale columnar OLAP | Distributed OLAP over billions of rows / high-ingest streaming is irrelevant here |
| Must run **in CI**, count toward coverage | Embeds in the test process, zero infra | Needs a container/service in CI |

ClickHouse earns its keep in the fleet's *server-resident, multi-source, high-volume* use
cases. AC copilot is the opposite — **single local machine, small immutable corpus, offline
batch questions** — exactly the niche where an embedded engine beats a server one. The
divergence is the architecture (local rig + immutable JSON), not a voice-latency win.

## Consequences

- Keep DuckDB scoped to **offline analytics**; never put it on the realtime/voice hot path.
- If the data plane ever becomes multi-rig / server-hosted / high-ingest, revisit — that is
  the condition under which the fleet ClickHouse default would start to apply.
