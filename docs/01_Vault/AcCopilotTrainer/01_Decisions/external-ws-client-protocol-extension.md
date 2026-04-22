---
type: decision
status: active
created: 2026-04-21
updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/03_Investigations/csp-web-socket-api.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/_index.md
---

# External WebSocket client protocol extension

## Context

`tools/ai_sidecar` (Python) is the WS hub for the trainer today. The CSP Lua `ws_bridge.lua` module dials `ws://127.0.0.1:8765` as its only client and speaks **protocol v1** (`PROTOCOL_VERSION = 1`). Inbound message types in use: `coaching_response`, `corner_advice`.

We want a **second** WS client — the rig-mounted ESP32 touchscreen — to read and write a curated subset of the trainer's state (the ~28 keys in `CONFIG_DEFAULTS` plus named actions). The screen connects over WiFi, not loopback, so the sidecar needs to accept a LAN bind safely.

## Decision

1. **Extend protocol v1 in a backward-compatible way.** Do **not** roll a v2. New message types are additive; existing `coaching_response` / `corner_advice` keep their shape. A client may ignore unknown message types.

2. **New message namespace** (all JSON-over-WS):

   | Direction | Type | Body |
   |---|---|---|
   | client → server | `config.get` | `{ key }` |
   | server → client | `config.value` | `{ key, value, source: "storage"|"default" }` |
   | client → server | `config.set` | `{ key, value }` |
   | server → client | `config.ack` | `{ key, ok: bool, error?: string }` |
   | client → server | `action` | `{ name, args?: object }` |
   | server → client | `action.result` | `{ name, ok: bool, result?: any, error?: string }` |
   | client → server | `state.subscribe` | `{ topics: [...] }` |
   | server → client | `state.snapshot` | `{ topic, payload, ts_sim }` |

3. **Auth and binding.**
   - Default sidecar bind stays `127.0.0.1:8765`. **No regression** for users who never connect an external client.
   - New sidecar CLI flag `--external-bind <host>` (e.g. `0.0.0.0`) requires `--token <secret>` set at the same time, or the sidecar refuses to start.
   - External clients must send `X-AC-Copilot-Token: <secret>` on the WS upgrade request. Missing/wrong token → 401 and immediate close.
   - Token lives in `firmware/screen/secrets/token.h` (gitignored) on the ESP32 side; in `%LOCALAPPDATA%\ac-copilot-trainer\sidecar.token` or an env var on the sidecar side.

4. **Config key surface.** Expose the existing `CONFIG_DEFAULTS` keys through the new messages. No new storage — reuse the per-key `ac.storage("<key>_v1", default)` pattern already in `ac_copilot_trainer.lua`. The Lua side handler in `ws_bridge.pollInbound` writes via the existing wrappers.

## Consequences

- Zero-change default deployment: token disabled, loopback bind, existing Lua client keeps working byte-identical.
- Phase-1 firmware can be written against a stable contract before the LVGL UI is built.
- External-control code path must be **feature-flagged off** by default on the Lua side so the inbound queue doesn't grow unbounded when the ESP32 isn't connected.
- Any Lua config key removal or rename is now a **protocol-breaking change** — needs a dedicated ADR + firmware bump.

## Alternatives considered

- **Roll protocol v2.** Rejected — v1 is in production, and the external-client additions don't conflict with existing types. No win from a version bump.
- **Separate WS daemon for external clients.** Rejected — duplicates the lifecycle problem (`os.runConsoleProcess` spawn, crash-loop guards) the sidecar already solves.
- **HTTP REST API on the sidecar for external clients.** Rejected — need push semantics for `state.snapshot`, and we'd end up reinventing a second protocol on the same process.

## Open questions

- Rate-limiting: what's a reasonable `config.set` cadence cap before the sidecar drops requests? Needs profiling on the Lua inbound queue (`MAX_RECV_PER_TICK = 8`).
- Whether `state.snapshot` should be pushed at a fixed cadence or event-driven. Start event-driven; revisit if the ESP32 UI feels laggy.
