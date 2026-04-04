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

\*Missing `protocol` on `lap_complete` is accepted with a server warning (legacy); new clients should always send `protocol: 1`.

### `coaching_response` (Python → Lua)

| Field      | Type   | Required | Notes                                                |
| ---------- | ------ | -------- | ---------------------------------------------------- |
| `protocol` | int    | yes      | `1`                                                  |
| `event`    | string | yes      | `"coaching_response"`                                |
| `lap`      | int    | yes      | Must match the `lap` from the triggering `lap_complete` |
| `hints`    | array  | yes      | Up to 3 items: `{ "kind", "text" }` or plain strings |

When received while the coaching hold timer is active for the same `lap`, Lua **replaces** `state.coachingLines` with these hints (rules-based hints are overridden).

### `analysis_error` (Python → Lua)

| Field       | Type   | Required |
| ----------- | ------ | -------- |
| `protocol`  | int    | yes      |
| `event`     | string | yes      |
| `message`   | string | yes      |

Lua currently ignores this event (logging only in Python); future versions may surface errors in UI.

## Python entrypoint

`python -m tools.ai_sidecar` — see `WARP.md` for operator flags (`--no-reply`, host/port).

## Tests

`tests/test_ai_sidecar_protocol.py` — `prepare_outbound_message` unit tests and asyncio WebSocket round-trip (requires `websockets`).
