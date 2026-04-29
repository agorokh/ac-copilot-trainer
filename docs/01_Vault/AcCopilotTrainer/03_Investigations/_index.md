---
type: index
status: active
created: 2026-04-08
updated: 2026-04-29
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Investigations (index)

Technical deep-dives and root-cause analyses from development sessions.

| Node | Summary |
|------|---------|
| [csp-cdata-callable-guards.md](csp-cdata-callable-guards.md) | `type(vec2)` returns "cdata" not "function" in CSP/LuaJIT — use nil-checks |
| [csp-web-socket-api.md](csp-web-socket-api.md) | CSP web.socket is callback-based; sock(data) to send; reconnect:true required |
| [ac-storage-persistence.md](ac-storage-persistence.md) | ac.storage table-form silently fails; use per-key form for persistence |
| [jc3248w535-board-identification-2026-04-21.md](jc3248w535-board-identification-2026-04-21.md) | Board ID + pin verification for the Guition rig screen. |
| [screen-firmware-windows-build-gotchas-2026-04-21.md](screen-firmware-windows-build-gotchas-2026-04-21.md) | PlatformIO long-cmd / Windows SCons workarounds. |
| [jc3248w535-display-canvas-flush-2026-04-21.md](jc3248w535-display-canvas-flush-2026-04-21.md) | JC3248W535 needs Arduino_Canvas + ips=false; Arduino_AXS15231B init table is for the 1.91" AMOLED variant. |
| [router-mesh-cross-ap-tcp-block-2026-04-21.md](router-mesh-cross-ap-tcp-block-2026-04-21.md) | AHOME5G mesh drops cross-AP TCP between PC and screen; Windows Mobile Hotspot is the workaround. |
| [csp-app-pocket-tech-setup-exchange-2026-04-21.md](csp-app-pocket-tech-setup-exchange-2026-04-21.md) | Surface map for x4fab's PocketTechnician + SetupExchange — APIs, files, integration paths. |
| [screen-debugging-journey-2026-04-21.md](screen-debugging-journey-2026-04-21.md) | Dead-ends tried before the display + network fixes landed. DO NOT REPEAT. |
| [cowork-session-retrospective-2026-04-21.md](cowork-session-retrospective-2026-04-21.md) | User's critique of earlier Cowork session + durable autonomy/ownership preferences. |
| [pr-78-sidecar-autolaunch-lap-archive.md](pr-78-sidecar-autolaunch-lap-archive.md) | Sidecar auto-launch via CSP os.runConsoleProcess + per-lap JSON archive schema v1 + 500 MB rotation. |
| [pr-75-ollama-corner-coaching-protocol.md](pr-75-ollama-corner-coaching-protocol.md) | corner_query / corner_advice protocol, two-phase response (rules < 10ms + Ollama ~3-7s), sim-time staleness. |
| [screen-end-to-end-bringup-2026-04-26.md](screen-end-to-end-bringup-2026-04-26.md) | 8 root-cause bugs found during PR #91 Parts C+D bring-up on real hardware: AR linker, ArduinoWebsockets header leak, sidecar allow-list, sidecar bind, CSP onOpen unreliable, AXS15231B rotation matrix, portrait mount, em-dash glyph. |
| [wifi-hotspot-single-radio-2026-04-26.md](wifi-hotspot-single-radio-2026-04-26.md) | Intel 7260 single-radio: hotspot's "2.4 GHz" lies while connected to 5 GHz client mode; SSID-with-space breaks ESP32 scan. Fix: disconnect 5 GHz primary + rename SSID. |
| [ci-conventional-stale-pr-title-2026-04-25.md](ci-conventional-stale-pr-title-2026-04-25.md) | `ci-conventional` fails after a PR title rename — Actions captures the event payload at trigger time and doesn't re-fire on rename. Push a fresh commit. |
