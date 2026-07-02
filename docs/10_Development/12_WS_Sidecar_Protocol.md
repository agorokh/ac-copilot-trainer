# WebSocket sidecar protocol (v1)

Issue **#45** — versioned JSON over the same WebSocket the Lua app already uses for `lap_complete`.

## Constants

| Field        | Value | Meaning                          |
| ------------ | ----- | -------------------------------- |
| `protocol`   | `1`   | Schema version on every message  |

## Events

### `lap_complete` (Lua → Python)

Sent after each completed lap when `config.wsSidecarUrl` is set and the socket is connected.

| Field           | Type        | Required | Notes                                |
| --------------- | ----------- | -------- | ------------------------------------ |
| `protocol`      | int         | yes\*    | Must be `1` for strict validation   |
| `event`         | string      | yes      | `"lap_complete"`                     |
| `lap`           | int         | yes      | App lap counter (`lapsCompleted`)    |
| `lapTimeMs`     | int         | yes      | Previous lap time in ms              |
| `coachingHints` | string[]    | no       | Rules-based hint strings (same lap)  |
| `telemetry`     | object      | no       | Optional structured lap data for sidecar analysis (issue **#49**); see below |
| `archivePath`   | string      | no       | Issue **#277**: archive-backed follow-up path, sent only after the async lap archive write completes |
| `referenceArchivePath` | string | no    | Optional safe lap archive path for the driver's written PB/reference, enabling delta-based brain rules |
| `historyArchivePaths` | string[] | no    | Optional bounded list of recent safe lap archive paths; enables per-corner lap-to-lap consistency diagnostics |
| `brainOnly`     | bool        | no       | When `true`, the sidecar skips the generic immediate ack and only emits the archive-backed brain follow-up |

\*Missing `protocol` on `lap_complete` is accepted with a server warning (legacy); new clients should always send `protocol: 1`.

#### Optional `telemetry` (issue **#49**)

When present, `telemetry.corners` is an array of per-corner objects used for **improvement ranking** in the Python sidecar. The sidecar ranks against the **fastest lap seen on that WebSocket connection that included `telemetry.corners`** (overall `lapTimeMs` PB may be updated from laps without corners; see issue **#49**). Lua **3b** may omit this until telemetry export exists; the field is forward-compatible.

Each corner object:

| Field           | Type   | Notes                                      |
| --------------- | ------ | ------------------------------------------ |
| `id`            | int    | Corner identifier                          |
| `minSpeedKmh`   | number | Optional; higher is better for ranking     |
| `apexSpeedKmh`  | number | Optional; higher is better for ranking     |

Snake_case variants (`min_speed_kmh`, …) are also accepted.

### `coaching_response` (Python → Lua)

| Field      | Type   | Required | Notes                                                |
| ---------- | ------ | -------- | ---------------------------------------------------- |
| `protocol` | int    | yes      | `1`                                                  |
| `event`    | string | yes      | `"coaching_response"`                                |
| `lap`      | int    | yes      | Must match the `lap` from the triggering `lap_complete` |
| `hints`    | array  | yes      | Up to 3 items: `{ "kind", "text" }` or plain strings |
| `improvementRanking` | array | no | Issue **#49**: ordered corner-level suggestions vs best lap-with-corners reference (ignored by current Lua until **3b** consumes it) |
| `debrief`  | string | no       | Issue **#46**: one or two paragraphs when `AC_COPILOT_OLLAMA_ENABLE=1` (local Ollama with **`AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC`** default 12s, then rules fallback); omitted when debrief feature is off. The sidecar builds outbound messages in a worker thread so slow Ollama does not block the WebSocket loop. |
| `debriefSource` | string | no | `"ollama"` or `"brain"` for async follow-ups. Lua preserves the rich debrief text and treats `"brain"` as a structured tile source. |
| `cornerAnalysis` | array | no | Issue **#277**: machine-readable setup-vs-technique corner tiles from the brain follow-up. |
| `balance` | object | no | Issue **#277**: overall balance verdict/coaching, rendered as a secondary brain tile when space allows. |

When received for the same `lap`, Lua **replaces** `state.coachingLines` with these hints (rules-based hints are overridden). If the hold timer had already expired (e.g. delayed sidecar), Lua **restarts** the hold so hints still display.

#### `improvementRanking` items (issue **#49**)

When present, `improvementRanking` is a JSON array of objects, **highest priority first** (Python sorts by normalized speed regret). Keys are snake_case as emitted today:

| Field         | Type   | Required | Meaning |
| ------------- | ------ | -------- | ------- |
| `corner`      | int    | yes      | Corner id (same notion as `telemetry.corners[].id`). |
| `metric`      | string | yes      | Internal key: `min_speed_kmh` or `apex_speed_kmh` (aliases accepted on *inbound* telemetry only). |
| `last`        | number | yes      | Value on the lap that triggered this message. |
| `reference`   | number | yes      | Value from the session reference lap-with-corners for the same corner and metric. |
| `priority`    | number | yes      | Normalized regret `(reference - last) / max(|reference|, ε)`; higher = larger gap vs reference on that metric. |
| `suggestion`  | string | yes      | Human-readable line for UI or logging. |

For the current speed metrics, **higher** telemetry is better; an item usually indicates a possible gain when `reference > last`. Consumers may ignore unknown fields for forward compatibility.

#### `cornerAnalysis` items (issue **#405**)

The brain follow-up emits one object per segmented corner. Existing fields (`index`, `apex_spline`, `min_speed_kmh`, `time_loss_s`, `headline`, `attributions`) remain stable. Issue **#405** adds `diagnostics`, a machine-readable block that lets clients render deeper coach tiles even when an attribution does not rank in the top prose lines.

| Diagnostic key | Meaning |
| -------------- | ------- |
| `steering` | Steering smoothness score, correction count, p95 steering rate, and a scrub proxy derived from steering rate while loaded. |
| `brake_shape` | Brake trace classification (`ideal_trace`, `increasing_pressure`, `abrupt_release`, `braking_at_apex`, or `no_brake`) plus release smoothness. |
| `gear` | Entry/apex/exit gear, gear-change count, and apex-gear delta vs `referenceArchivePath` when a reference lap is supplied. |
| `exit_road_usage` | Reference-path lateral-delta proxy. `available=false` without a reference lap; true curb/track-edge under-use coaching requires map-edge geometry or caller-supplied `under_used_exit_width_m`. |
| `consistency` | Lap-to-lap per-corner spread and 0-100 repeatability score when at least one valid `historyArchivePaths` lap plus the current lap segment the same corner. |

### `analysis_error` (Python → Lua)

| Field       | Type   | Required |
| ----------- | ------ | -------- |
| `protocol`  | int    | yes      |
| `event`     | string | yes      |
| `message`   | string | yes      |

Lua currently ignores this event (logging only in Python); future versions may surface errors in UI.

## Python entrypoint

`python -m tools.ai_sidecar` — see `WARP.md` for operator flags (`--no-reply`, host/port).

**Fixture ranking (issue #49):** `python -m tools.ai_sidecar --compare-laps slower.json reference.json` prints JSON for corner-level improvement suggestions (requires `telemetry.corners` in both files).

**Setup optimization (issue #114):**

- screen/client -> sidecar -> Lua: `{"v":1,"type":"setup.spinner.list"}` returns `setup.spinner.list.result` with active setup controls (`section`, `label`, `value`, `min`, `max`, `step`, `unit`).
- screen/client -> sidecar -> Lua: `{"v":1,"type":"setup.spinner.set","section":"FRONT_BIAS","value":67}` returns `setup.spinner.set.ack`; Lua applies the edit only inside the AC user setup folder and only when the pits/reset gate allows setup changes.
- Lua → sidecar: `{"v":1,"type":"setup.experiment.store","store_path":".../journal/setup_experiments/experiments.jsonl"}` registers the canonical store after handshake so compare/suggest can use rebuilt rows immediately after sidecar restart.
- Lua → sidecar: `{"v":1,"type":"setup.experiment.record","archive_path":".../journal/laps/lap_...json"}` ingests one PR #78 lap archive into `journal/setup_experiments/experiments.jsonl`.
- client → sidecar: `{"v":1,"type":"setup.compare","baseline_setup":"old","candidate_setup":"new"}` returns `setup.compare.result` with A/B improvement, confidence, and significance.
- client → sidecar: `{"v":1,"type":"setup.suggest","car_id":"...","track_id":"..."}` returns `setup.suggest.result` with the next setup candidate and rationale.

CLI equivalents:

```bash
python -m tools.ai_sidecar --setup-rebuild-experiments "<...>/journal/laps"
python -m tools.ai_sidecar --setup-store "<...>/experiments.jsonl" --setup-compare old new
python -m tools.ai_sidecar --setup-store "<...>/experiments.jsonl" --setup-suggest
python -m tools.ai_sidecar --setup-store "<...>/experiments.jsonl" --host 127.0.0.1 --port 8765
```

See [13_Setup_Experiments.md](13_Setup_Experiments.md) for data location, reset, and rebuild.

## Session Review Reports

Loopback Lua/client -> sidecar: `{"v":1,"type":"session.review.generate","lap_dir":".../journal/laps"}` writes a derived post-session review to the sibling `journal/reports` directory.

Optional fields:

| Field | Type | Notes |
| ----- | ---- | ----- |
| `session` | string | Session UUID to review, or omit for latest. |
| `driver_id` | string | Driver profile key; defaults to `local-driver`. |
| `reference_source` | string | `auto`, `your-best`, `pro`, `tt`, `generated`, `imported`, or `none`; aliases such as `track-titan` are accepted. |
| `reference_file` | string | Basename under the same `journal/laps` directory to pin one same-car/track/layout reference archive. |

The loopback ack is `session.review.result` with local `markdown_path`, `json_path`, and `html_path` plus `reference` / `reference_selection` metadata. External `session.review` snapshots and `coaching.cue` details redact host paths to `markdown_file`, `json_file`, and `html_file` basenames while preserving the reference metadata.

## Tests

`tests/test_ai_sidecar_protocol.py` — `prepare_outbound_message` unit tests and asyncio WebSocket round-trip (requires `websockets`). `tests/test_llm_coach.py` — Ollama debrief helpers with mocked HTTP (issue **#46**).
