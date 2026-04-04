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

## Tests

`tests/test_ai_sidecar_protocol.py` — `prepare_outbound_message` unit tests and asyncio WebSocket round-trip (requires `websockets`). `tests/test_llm_coach.py` — Ollama debrief helpers with mocked HTTP (issue **#46**).
