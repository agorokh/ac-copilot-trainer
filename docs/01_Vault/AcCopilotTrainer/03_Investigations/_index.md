---
type: index
status: active
created: 2026-04-08
updated: 2026-06-16
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
| [lua-telemetry-trace-replay-testability.md](lua-telemetry-trace-replay-testability.md) | The 5 coaching-logic modules are pure functions of plain tables — testable under lupa with NO `ac.*` shim, just a `math.atan2` LuaJIT-parity shim + a trace feeder (EPIC #154 Part A). |
| [garage-to-track-autonomous-entry-2026-06-13.md](garage-to-track-autonomous-entry-2026-06-13.md) | Two-stage autonomy: session entry is a launch problem (race.ini spawns on track but doesn't skip the Drive screen; OS input dead); driving = CSP Custom AI mmap. App context can't pilot. |
| [menu-skip-race-and-shared-memory-oracle-2026-06-14.md](menu-skip-race-and-shared-memory-oracle-2026-06-14.md) | Pre-drive menu-skip is a timing/state RACE (no CSP/CM config knob; depends on prior pit state). Deterministic fix = detect-and-retry on `acpmf_graphics` AC_STATUS+IsInPit. #175 shipped the DETECT half (`shared_memory.py`); 64-bit ctypes + observed-advancement gotchas. |
| [csp-car-wheels-0-indexed-2026-06-15.md](csp-car-wheels-0-indexed-2026-06-15.md) | CSP `car.wheels` is **0-indexed** (FL=0..RR=3) per `ac.Wheel`; reading `[1..4]` shifts every corner + reads an out-of-bounds zero for RR (the #185 `tire_temps.rr=0` bug). Always use `[0..3]`. |
| [csp-custom-ai-mmap-interface-2026-06-16.md](csp-custom-ai-mmap-interface-2026-06-16.md) | The `carcsw` driver foundation (Part E #190): CSP Custom AI mmap names (`AcTools.CSP.NewBehaviour.CustomAI.CarControls<N>.v0` write / `.Car<N>.v0` read / `.SimState.v0`), cai_car_controls fields, create-CarControls→CSP-creates-Car signaling, 333 Hz, activation ini flags. Byte offsets need build-time verification. |
| [autonomous-drive-live-verified-2026-06-16.md](autonomous-drive-live-verified-2026-06-16.md) | **EPIC #154 L2 ACHIEVED.** Agent drove a full clean lap (no human) via carcsw + pure-pursuit; trainer captured a reference + coached it live. LIVE-VERIFIED offsets (gear 0=R/1=N/2=1st; autoclutch launch; teleport@40 reset; pos@88/look@64; spline@448 GARBAGE; steer sign OK). `restart_session`=poison; menu-skip race retry; minimize Claude to click CM; hotlap counts only VALID laps. |
| [issue-188-wrap-skew-rig-verification.md](issue-188-wrap-skew-rig-verification.md) | **#188 RESOLVED/CLOSED 2026-06-16.** On-rig probe: `car.resetCounter` **present** (`value=2`) → teleports fully handled → closed as moot per operator criterion; #199 deferral is defensive-only. Q2 skew moot (no resetCounter-less build to test). |
| [steam-elevation-mismatch-ac-launch-2026-06-16.md](steam-elevation-mismatch-ac-launch-2026-06-16.md) | Rig gotcha: AC "Steam API has failed to initialize" = Steam(elevated)/Content-Manager(non-elevated) integrity mismatch (`ActiveProcess pid=0`). Fix: `steam -shutdown` + relaunch Steam non-elevated via `explorer.exe` (auto-login). Agent shell is elevated → launch the game via CM, never `acs.exe` directly. |
| [pr-207-motec-reference-import.md](pr-207-motec-reference-import.md) | MoTeC CSV importer for schema-v1 `source=imported` lap archive records + opt-in imported-reference activation that never overwrites local PB persistence. |
