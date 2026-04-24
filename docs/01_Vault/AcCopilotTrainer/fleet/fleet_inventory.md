---
type: entity
status: active
created: 2026-04-04
updated: 2026-04-04
memory_tier: canonical
issue: https://github.com/agorokh/template-repo/issues/71
relates_to:
  - AcCopilotTrainer/fleet/_index.md
  - AcCopilotTrainer/fleet/fleet_inventory.yml
  - 00_Graph_Schema.md
---

# Fleet inventory schema

**Classification:** Internal — describes private org repos and automation metadata; do not treat as public documentation.

Canonical data lives in [`fleet_inventory.yml`](fleet_inventory.yml). The refresh script (`scripts/fleet_inventory_refresh.py`) merges **static** hub metadata (slug, display name, domain, notes) with **snapshot** fields from the GitHub API.

## Static fields (YAML, maintained in-repo)

| Field | Meaning |
|-------|---------|
| `slug` | `owner/name` for GitHub API |
| `name` | Short repo name (directory style) |
| `domain` | Fleet domain tag (`legal`, `trading`, `infra`, `gaming`, …) aligned with `tools/process_miner/fleet.py` |
| `notes` | Optional human context |

## Snapshot fields (written by refresh)

| Block | Fields |
|-------|--------|
| `github` | `default_branch`, `language`, `archived`, `pushed_at`, `updated_at`, `stars`, `open_issues_count`, `visibility`, `error` |
| `template_sync` | `copier_answers_present`, `copier_answers_short_sha` (7-char prefix of blob SHA; avoids secret scanners) |
| `vault` | `vault_root_present`, `project_key` (first `docs/01_Vault/<dir>` directory that is not a schema-only file), `error` |
| `agent_config` | `claude_dir_present`, `settings_json_present`, `hook_event_count`, `error` |
| `activity` | Reserved for future counters; refresh may leave `null` |

Missing files, private repos without auth, or API errors set `error` on the relevant block instead of failing the whole run.

## Index table

[`_index.md`](_index.md) includes an auto-generated summary table between HTML comments; do not hand-edit rows inside the marked region.
