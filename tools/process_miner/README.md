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
- Learned rules: `.claude/rules/learned/*.md` and `.cursor/rules/learned/*.mdc` (when `--emit-learned`)
- Knowledge DB: `.cache/repo_knowledge/knowledge.db` (when `--ingest-knowledge`, gitignored)

## API note (REST vs GraphQL)

The GitHub client uses REST with explicit `timeout=30` and `max_pages` (default 20) on paginated endpoints. GraphQL batching could reduce round-trips; we keep REST for simpler debugging and document revisiting if rate limits bite.

## Scheduled automation

See `.github/workflows/process-miner.yml` (weekly + `workflow_dispatch`). Uses `gh pr create` when there are changes.
