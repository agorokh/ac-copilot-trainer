---
type: index
status: active
created: 2026-03-28
updated: 2026-06-16
relates_to:
  - AcCopilotTrainer/00_System/Architecture Invariants.md
  - 00_Graph_Schema.md
---

# Decisions (ADRs)

Architecture Decision Records for this vault.

- [local-reviewer-model](local-reviewer-model.md) — Tier 3 local reviewer model scope and phases (epic #26).
- [csp-api-field-safety](csp-api-field-safety.md) — CSP C-struct field access rules, valid/invalid fields, render API (issue #24).
- [screen-firmware-in-trainer-monorepo](screen-firmware-in-trainer-monorepo.md) — `firmware/` lives inside the trainer repo.
- [screen-firmware-toolchain](screen-firmware-toolchain.md) — Arduino_GFX 1.4.7 + ArduinoWebsockets + ArduinoJson on espressif32@6.13.0.
- [external-ws-client-protocol-extension](external-ws-client-protocol-extension.md) — sidecar opt-in LAN bind + token + `{v,type}` envelope (issue #81).
- [screen-ui-stack-lvgl-touch](screen-ui-stack-lvgl-touch.md) — LVGL 8.3 + AXS15231B touch + SquareLine for the rig screen UI.
- [screen-and-csp-apps-integration](screen-and-csp-apps-integration.md) — bridge the rig screen to Pocket Technician + Setup Exchange via same-VM API replication, not cross-VM bridging.
- [dashboard-visual-design-figma](dashboard-visual-design-figma.md) — Figma file is source of truth for both HUD (shipped) and rig touchscreen (Phase 2); design tokens + cockpit-UX rules captured here.
- [autonomous-self-test-harness](autonomous-self-test-harness.md) — agent test-drives the trainer with no human in the loop; layered pyramid (L0 lupa / L1 WS-tap / L1.5 in-sim probe / L2 daemon+CSP Custom AI / L3 human smoke); EPIC #154.
- [delta-clock-boundary-alignment](delta-clock-boundary-alignment.md) — the `delta` WS topic publishes only when the lap clock is start/finish-aligned (`deltaRefStale`); WS is stricter than the HUD; teleport via guarded `car.resetCounter` (PR #185, #188 residual).
- [rl-reference-lap-generation](rl-reference-lap-generation.md) — issue #116 go/no-go: defer RL runtime, pursue stdlib/off-sim generated reference laps in archive schema v1 with a persistence-payload bridge.
- [track-titan-coaching-oracle-strategy-2026-06-27](track-titan-coaching-oracle-strategy-2026-06-27.md) — **draft proposal**: treat Track Titan as a swappable external "coaching oracle" (not a runtime data source); cheap wins = pro-ghost→#207 importer + TT-as-referee for the harness; gated ws:9121 spike; never automate the user's cloud token. See [[track-titan-telemetry-extraction-feasibility-2026-06-27]].
- [voice-coach-architecture-2026-06-28](voice-coach-architecture-2026-06-28.md) — in-the-ear voice coach (issue #340): pre-rendered phrase bank (not live TTS) + urgency scheduler (barge-in/dedup/TTL/cooldown) speaking the same `Advisory` stream as the text HUD; stdlib core dep-free, audio deps behind the `voice` extra; headset pinned off the haptic DAC.
- [voice-intensity-register-2026-06-28](voice-intensity-register-2026-06-28.md) — intensity-expressive coach (issue #368): a baked `register` tone tier (calm/firm/critical) as a 4th content-addressed manifest axis; severity→register in the observer w/ hysteresis; terse anticipatory cues (act ≤450 ms); ffmpeg prosody chain over Kokoro/say-expressive/ToneBackend; timing-report + voice benchmark. Corrects the stale "spline absent from live payload" comment.
