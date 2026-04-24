# Process miner (ported)

Mines merged GitHub PRs for recurring review feedback, CI failures, and file churn. Tier 1 emits path-scoped learned rules; Tier 2 feeds SQLite + optional `repo-knowledge` MCP.

## Install

```bash
pip install -e ".[mining]"          # miner only
pip install -e ".[mining,knowledge]" # + SQLite ingest + MCP
```

## Run

```bash
export GITHUB_TOKEN=...
export REPO=owner/repo   # optional if you pass --repo
python scripts/process_miner.py --days 7 --emit-learned --ingest-knowledge
```

Outputs:

- Report: `reports/process_miner/<since>_last<N>days.md`
- Cache: `.cache/process_miner/*.json` (gitignored)
- Learned rules (when `--emit-learned`): scoped under `.claude/rules/learned/local/` (single-repo), `universal/` (fleet S0), and `domain/<legal|trading|infra|gaming>/` (fleet S2); mirrored under `.cursor/rules/learned/.../*.mdc`.

## Fleet / cross-repo (#70)

- Default repo list: `tools/process_miner/fleet.py` (`DEFAULT_FLEET_REPOS`).
- `python scripts/cross_repo_aggregate.py` with `MINING_USE_DEFAULT_FLEET=1` uses that list (still needs `GITHUB_TOKEN`).
- Vault health (issue #73): set `MINING_AUDIT_VAULT=1` to attach per-repo `vault_health` summaries to aggregate output. Single-repo: `python scripts/process_miner.py --audit-vault ...` adds a **Vault Health** section and, with `--ingest-knowledge`, persists `vault_health` / `vault_nodes` tables.
- Optional `MINING_EMIT_LEARNED=1` writes universal + domain rules from aggregate results (maintainer workflow; review before merge).
- **#78 distillation:** With `MINING_DISTILL=1` and an LLM key in the environment (see `.env.example` / Doppler), the aggregate run performs an OpenAI-compatible JSON pass over universal (S0) clusters and writes `reports/cross_repo_mining/aggregate_distill.json`; results are cached under `.cache/process_miner_distill/`. Prefer `doppler run -- …` per root `doppler.yaml`.
- Post-cluster noise (#78): `analyze_prs` merges near-duplicate cluster titles (permuted TF-IDF tokens) and drops titles that are only bot/reviewer *UI chrome* (product names), not browser Chrome; see `stats["noise_filter_post_cluster_audit"]` on each analysis.
- Bot noise is stripped before TF-IDF; emission applies PR-count gates, nit thresholds, boilerplate detection, and semantic dedup vs existing rules.
- Knowledge DB: `.cache/repo_knowledge/knowledge.db` (when `--ingest-knowledge`, gitignored)

## API note (REST vs GraphQL)

The GitHub client uses REST with explicit `timeout=30` and `max_pages` (default 20) on paginated endpoints. GraphQL batching could reduce round-trips; we keep REST for simpler debugging and document revisiting if rate limits bite.

## Scheduled automation

See `.github/workflows/process-miner.yml` (weekly + `workflow_dispatch`). Uses `gh pr create` when there are changes.
