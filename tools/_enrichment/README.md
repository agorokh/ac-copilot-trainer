# Phase 3 milestone enrichment (Parallel)

When **`parallel-cli`** is installed (`/parallel-setup` in Cursor), enrich the seed CSV with external best practices and doc pointers for each milestone.

**Seed file:** [`phase3_milestones_seed.csv`](phase3_milestones_seed.csv)

## Data enrichment (after `parallel-cli` works)

Per **parallel-data-enrichment** skill: run with `--no-wait`, then poll.

```bash
parallel-cli enrich run --source-type csv --source tools/_enrichment/phase3_milestones_seed.csv --target tools/_enrichment/phase3_milestones_enriched.csv --source-columns '[{"name":"milestone_key","description":"Milestone id 3a-3f"},{"name":"title_one_line","description":"Short title"},{"name":"repo_context","description":"Repo stack context"}]' --intent "Key framework docs links, API safety patterns, and delivery risks for this milestone; bullet list" --no-wait
```

Then:

```bash
parallel-cli enrich poll "<TASKGROUP_ID>" --timeout 540
```

Commit **`phase3_milestones_enriched.csv`** (and optionally paste a summary into **#9** or milestone issues) once reviewed.

## Deep research (optional, heavier)

```bash
parallel-cli research run "Assetto Corsa CSP Lua web.socket WebSocket limits; Dear ImGui in-game text; Ollama localhost coaching debrief patterns; SHAP driver coaching IEEE" --processor pro-fast --no-wait --json
parallel-cli research poll "<RUN_ID>" -o tools/_enrichment/phase3-coaching-research --timeout 540
```

Do **not** substitute web search for these when the skill requires `parallel-cli`; install the CLI first.
