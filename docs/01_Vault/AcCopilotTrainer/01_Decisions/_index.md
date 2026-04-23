---
type: index
status: active
created: 2026-03-28
updated: 2026-04-22
relates_to:
  - ProjectTemplate/00_System/Architecture Invariants.md
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
