---
type: index
status: active
memory_tier: canonical
created: 2026-06-30
updated: 2026-06-30
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Product roadmap

Forward-looking plan organized by the product's real verticals, replacing the ad-hoc
"Stream A–D + residuals" changelog. Built 2026-06-30 from three codebase capability
inventories (coaching engine · data/retention · surfaces/autonomy) crossed against a
sim-racing coaching capability taxonomy (sources: Driver61, Blayze, NASA Speed News, VRS,
Sim Coaches/TrackPro, MoTeC i2, Full Grip Vision, trophi.ai — design reference, verify
pass was rate-limited; load-bearing facts come from the code inventories).

**Live tracker (canonical, do not duplicate the matrix here):**
[ROADMAP umbrella #401](https://github.com/agorokh/ac-copilot-trainer/issues/401).

## One-line diagnosis

The **real-time + per-lap** path is a genuine product (deep, shipped). The
**across-laps / across-sessions / across-time** path barely exists. Most remaining
value is **longitudinal** — the parts that don't pay off in a single 12-hour sprint.

## Vertical → epic map

| Vertical | What's missing (headline) | Owning issue(s) |
|---|---|---|
| 1. Telemetry & data platform | session/stint/driver entities; retention policy | [#402](https://github.com/agorokh/ac-copilot-trainer/issues/402) |
| 2. Reference & benchmarking | sector/micro-sector deltas; stitched optimal lap | [#408](https://github.com/agorokh/ac-copilot-trainer/issues/408) + [#353](https://github.com/agorokh/ac-copilot-trainer/issues/353) |
| 3. Diagnosis depth | steering, vision proxy, consistency, gear | [#405](https://github.com/agorokh/ac-copilot-trainer/issues/405) (reconciles [#396](https://github.com/agorokh/ac-copilot-trainer/issues/396)) |
| 4. Real-time + debrief | structured post-session debrief | [#404](https://github.com/agorokh/ac-copilot-trainer/issues/404) Part A |
| 5. Tyre/brake/fuel mgmt | fuel/energy strategy (absent); brake temp; wet | [#406](https://github.com/agorokh/ac-copilot-trainer/issues/406) |
| 6. Setup ↔ driver feedback | complaint→lever; closed loop | [#407](https://github.com/agorokh/ac-copilot-trainer/issues/407) |
| 7. Driver model & progression | profile, skill tracking, curriculum (**biggest gap**) | [#403](https://github.com/agorokh/ac-copilot-trainer/issues/403) |
| 8. Delivery surfaces | design language, voice, haptics logic | [#400](https://github.com/agorokh/ac-copilot-trainer/issues/400) · [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) · [#381](https://github.com/agorokh/ac-copilot-trainer/issues/381) · [#117](https://github.com/agorokh/ac-copilot-trainer/issues/117) |
| 9. Session review & data products | replay/history, trend dashboards, reports | [#404](https://github.com/agorokh/ac-copilot-trainer/issues/404) |
| —. Autonomy & self-test | (mature, owned) | [#154](https://github.com/agorokh/ac-copilot-trainer/issues/154) |

## Sequencing

1. **Foundation:** #402 (session/driver entities + retention) — verticals 7 & 9 depend on it.
2. **Longitudinal value:** #404 (review/trends) + #403 (driver model/curriculum).
3. **Depth in parallel:** #405, #406, #407, #408.
4. **Surfaces track:** #400 → #86 → #381 → #117.
5. **Reconcile #396** first (anticipatory cueing largely ships in `coaching_runtime.py`).

## Invariant

When an epic closes a gap, flip it in **both** the #401 matrix and `Project State.md`
(see [[Project State]]). Reconcile against merged code, not issue titles — several
"gaps" are partially shipped.
