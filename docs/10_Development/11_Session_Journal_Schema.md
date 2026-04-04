# Session journal schema (Phase 3 / issue #47)

Structured JSON written when a driving stint ends so training logs can be compared across sessions.

## Trigger

When the player returns to the **Assetto Corsa main menu** after `wasDriving` was true, the app persists brake/telemetry data, then writes one journal file **if `laps_completed` ≥ 1**, then clears runtime state. If persistence fails, neither reset nor journal export runs (same as pre-journal behavior).

## Paths (CSP ScriptConfig)

- App data root: `ac.getFolder(ac.FolderID.ScriptConfig) / ac_copilot_trainer /`
- Journal entries: `.../journal/session_<UTC_YYYYMMDD_HHMMSS>_<session_key>.json`
- Append-only index: `.../journal/journal_index.jsonl` (one JSON object per line: `journal_file`, `exported_at`, `session_key`)

`session_key` matches `persistence.sessionKey(car, sim)` (sanitized car + track id).

## Schema version 1

| Field | Type | Notes |
|------|------|--------|
| `schema_version` | int | Always `1` for this revision. |
| `exported_at` | string | ISO-8601 UTC, e.g. `2026-04-03T14:30:00Z`. |
| `app_version_ui` | string | App label from the Lua bundle (e.g. `v0.4.2`). |
| `session_key` | string | Stable id for car+track combo. |
| `car` | object | `{ "id": string }` from `ac.getCarID` / fallback. |
| `track` | object | `{ "id": string }` from track globals / fallback. |
| `conditions` | object | `{ "track_grip": number \| null }` from `sim.trackGripLevel` when available. |
| `summary` | object | `laps_completed`, `best_lap_ms`, `last_lap_ms`, `avg_lap_ms` (numbers or null). |
| `lap_history` | array | Per stored lap: `{ "lap_ms", "corner_count" }`. |
| `corners_last_lap` | array | Simplified corner feature rows from the last lap in history. |
| `coaching_hints_last` | array | `{ "kind", "text" }` objects (rules-based HUD hints at export time). |
| `llm_debrief` | null | Reserved for milestone 3d (Ollama debrief). |

## Validation

Python helper: `tools/session_journal.py` (`validate_session_journal`). Tests: `tests/test_session_journal.py`.

## Lua implementation

`src/ac_copilot_trainer/modules/session_journal.lua` — uses `persistence.encodeJson` / `JSON` global like other save paths.
