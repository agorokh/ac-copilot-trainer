---
description: "Learned via process-miner — verify before relying on it."
paths:
  - "src/**/*"
source: process-miner
rule_fingerprint: ee7626aaa4150ac2
mined_from: 10 review comments across 6 PRs
last_updated: 2026-04-06
repository: agorokh/ac-copilot-trainer
severity: bug
preventability: guideline
---

# Code Fallback This (learned)

Reviewers repeatedly raised similar feedback in this area. Treat as a heuristic, not a hard rule.

## Representative themes

- `ac.getCarID(0)` / `ac.getTrackID()` are invoked directly. Elsewhere in this module you already defensively handle CSP API variability (e.g., `ac.getTrackLayout and ac.getTrackLayout()`). If these fun...
- `ac.getTrackID()` is called unguarded. Since this function is used during initialization and this PR’s goal is to avoid CSP API-related startup crashes, consider guarding this call similarly to `ac.ge...
- The new gating logic returns early unless `render.debugLine` exists (or legacy `drawSphere` fallback). This regresses CSP builds where `render.debugSphere` and/or `render.debugCross` exist but `render...
- Primitive budget calculation in the non-line branch can undercount when `render.debugSphere` exists but has been marked unusable (`debugSphereUsable == false`) and you fall back to `render.drawSphere`...

## Suggested enforcement

- Document the preferred pattern in AGENTS.md or a scoped rule.
