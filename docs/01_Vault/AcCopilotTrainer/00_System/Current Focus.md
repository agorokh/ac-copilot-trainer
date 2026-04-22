---
type: current-focus
status: active
memory_tier: canonical
last_updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Current focus

**Repo:** ac-copilot-trainer.

## Stream A — Rig screen Phase-2 UI (post-PR #83)

**Status:** PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83)
is merged to `main` (2026-04-22). End-to-end path is working: sidecar
accepts ESP32 with token, device emits
`{v:1,type:"action",name:"toggleFocusPractice"}` every 10 s, and display
renders via `Arduino_Canvas`.

**Next:** Phase-2 LVGL bring-up per
[`01_Decisions/screen-ui-stack-lvgl-touch.md`](../01_Decisions/screen-ui-stack-lvgl-touch.md):
LVGL 8.3 + 40-line AXS15231B touch reader + canvas-flush bridge, then
SquareLine layout.

**Live-dev requirement:** PC's **Windows Mobile Hotspot `AG_PC 7933`**
must be on. Router AHOME5G mesh blocks cross-AP TCP — see
[`03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md`](../03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md).

## Stream B — CSP-apps integration (Pocket Technician, Setup Exchange)

**New epic.** User wants the rig touchscreen to bridge our trainer
PLUS Pocket Technician and Setup Exchange. Discovery is in progress
(see freshly-written investigation node in `03_Investigations/`); the
integration ADR lands as `01_Decisions/screen-and-csp-apps-integration.md`
with the verdict on read-only state scrape vs. cooperative same-VM
`require()`.

## Stream C — PR #75 in-game smoke test (still open)

Branch `fix/issue-75-in-game-smoke-test`. Pre-existing; merge
`origin/main` in, resolve conflicts, push, run live in Vallelunga +
Porsche 911 GT3 R.

## Priority call

Stream A is the user's hot path: move from working transport to real touch
UI (LVGL + tile actions). Stream B (CSP apps) is the research/design
phase in parallel. Stream C remains pre-existing backlog.
