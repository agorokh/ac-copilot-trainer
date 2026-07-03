---
type: decision
status: active
created: 2026-07-02
updated: 2026-07-02
issue: https://github.com/agorokh/ac-copilot-trainer/issues/463
relates_to:
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/issue-86-rig-screen-hotspot-autostart-2026-06-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Decision: rig screen talks to the sidecar over USB serial, not WiFi/hotspot

## Context

The screen reached the sidecar over WebSocket/TCP. Because the `AHOME5G` mesh
drops cross-AP TCP ([router-mesh-cross-ap-tcp-block](../03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md)),
the only working path was a Windows **Mobile Hotspot** on the rig PC. That hotspot
hosts a 2.4 GHz SoftAP on the PC's **single-radio** Intel AC 7260; while the client
is on 5 GHz `AHOME5G`, one radio cannot serve both bands, so the main WiFi drops
and will not reconnect. Physical limitation, not a Windows bug.

## Decision

Move the **screen leg** of the transport from external-WS to the native **USB CDC**
(the same COM port used to flash). Protocol v1 `{v,type}` frames are carried as
newline-delimited JSON. The in-game CSP trainer's loopback-WS peer is unchanged;
only the screen's byte transport changes. This removes WiFi, the hotspot, and the
mesh cross-AP block from the screen path in one move.

- **Sidecar** (`tools/ai_sidecar/serial_transport.py`): a `SerialPeer` reusing the
  transport-agnostic `_handle_external_frame` fan-out; `--serial-port` /
  `AC_COPILOT_SIDECAR_SERIAL_PORT`.
- **Firmware** (`firmware/screen`): `SCREEN_TRANSPORT_SERIAL` build flag, env
  `jc3248w535_serial` (now the rig default). Heartbeat `hello` (1 s until linked,
  5 s after) so a restarted sidecar re-registers the screen without a reboot.
- **Launcher** (`tools/rig_launcher`): the Mobile Hotspot probe/row/readiness
  coupling is removed entirely; the screen row derives from `screen_peers`.

## Key hardware finding (the DTR trap)

On the ESP32-S3 native USB CDC, the device only delivers **host→device (RX)** bytes
to the sketch once the host asserts **DTR**; the auto-reset is an **RTS** pulse, not
a steady DTR. Opening DTR-low (the intuitive "don't reset" choice) gives *no reset
but no RX* — the board never sees `hello_ack` and re-`hello`s forever. Correct:
**DTR high, RTS low**. Verified live on COM6.

## Evidence (live, 2026-07-02)

Mobile Hotspot OFF, main WiFi `AHOME5G` connected throughout (68%→69%, never
dropped; no `192.168.137.x`): screen registered as a serial screen peer
(`screen_peers=1`), bidirectional round-trip confirmed (board `hello` → sidecar
`hello_ack` → board dropped to the 5 s heartbeat), a trainer `coaching.snapshot`
fanned out to the serial peer with zero send failures. Both firmware envs build.

## Consequences

- The rig no longer needs the Mobile Hotspot; the single-radio main-WiFi drop is
  gone. The screen must stay USB-tethered to the PC (it already is on the rig).
- The WebSocket build (`jc3248w535`) is retained for LAN/hotspot deployments and CI.
- New protocol types still need three sites updated (firmware dispatch, trainer Lua,
  sidecar allow-list) — transport is orthogonal to that contract.
