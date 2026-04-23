---
type: decision
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/00_System/Current Focus.md
---

# Dashboard visual design (Figma source of truth)

## Context

Multiple vault nodes reference a Figma-backed UI source of truth for the trainer HUD and Phase-2 rig touchscreen work, but the ADR file was missing. That left dangling links and no single place to record design ownership and token usage.

## Decision

1. Treat the Figma dashboard file as the visual source of truth for:
   - In-game HUD styling alignment where practical.
   - Rig touchscreen (LVGL) layout, spacing, color, and typography targets.
2. Keep implementation constraints in code ADRs (`screen-ui-stack-lvgl-touch`, protocol ADRs), but keep visual intent and token mapping here.
3. Track the canonical Figma URL outside git-tracked docs when access is private; this ADR remains the stable link target for the vault graph.

## Token and typography mapping

- Numeric emphasis: Michroma (target 20 pt equivalent on device)
- Body copy: Montserrat Regular/Bold
- Branding accents: Syncopate Bold
- Use shared semantic tokens (surface/background/text/accent/warn) rather than hardcoded per-screen colors

## Consequences

- Existing references to `dashboard-visual-design-figma.md` resolve again.
- Future UI work has a single ADR anchor for "why this should look this way."
- If the Figma file or token set changes materially, update this ADR and link the follow-up decision/investigation.
