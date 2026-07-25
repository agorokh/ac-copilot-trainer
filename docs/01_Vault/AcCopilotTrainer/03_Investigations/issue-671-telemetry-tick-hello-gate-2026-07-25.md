---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-25
updated: 2026-07-25
issue: https://github.com/agorokh/ac-copilot-trainer/issues/671
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
---

# #671 — gate `telemetry_tick` on `externalHelloAcked`

## Verdict

**CLOSED** by PR [#679](https://github.com/agorokh/ac-copilot-trainer/pull/679) squash
[`efca5ca`](https://github.com/agorokh/ac-copilot-trainer/commit/efca5ca11e245d0f453a2ecc46fbdbc531eb3b70)
(2026-07-25T06:52:01Z). Extracted from #619 by the 2026-07-24 backlog reconcile.

## Bug

`publishTelemetryTickIfDue` sent via `wsBridge.sendJson`, which only requires a socket.
`publishTopic` already gated on `sock and externalHelloAcked` (PR #171) because the sidecar
rejects non-hello frames from unregistered peers. During reconnect storms, due ticks reached
the wire before `hello_ack`.

## Fix

- `ws_bridge.isExternalReady()` / `sendClientFrame()` — shared readiness + gated transport.
- Hello retry keeps using raw `sendJson` (gate must not live there).
- Topic / setup / session publishers route through `sendClientFrame`.
- `telemetry_publisher` probes `isExternalReady` before seq/payload, prefers `sendClientFrame`.

## Observed verification

Lupa harness (consumer path for this Lua change):

```text
pytest tests/test_ws_bridge_hello_handshake.py tests/test_telemetry_publisher.py -q
→ 51 passed
```

New cases cover: gated `sendClientFrame`, hello retry still firing while gated, publisher
silent until ack, reconnect `onOpen` re-suppresses ticks until fresh `hello_ack`.
`make ci-fast` green locally; hosted CI `build` / policy / conformance SUCCESS on merge SHA.

## Out of scope (still separate)

#672 voice endpoint hygiene; `AC_COPILOT_VOICE_BANK` arm-switch surfacing.
