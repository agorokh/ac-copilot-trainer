---
type: handoff
status: active
created: 2026-11-12
updated: 2026-11-12
issue: https://github.com/agorokh/ac-copilot-trainer/issues/955
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-11-214100Z-post-merge-pr960-2bc79e.md
---

# Issue 955: authorized second experiment

The operator explicitly reauthorized fixing A011/A012, evaluating a fresh frozen
set, and completing actual 20-car verification without manual operator checks.
The previous no-go and original fixture are immutable historical evidence, now
regressions, not a fresh evaluation. Owner #955 remains OPEN; labels enhancement,
phase-3, python. No open PRs at LOAD. Branch is
feat/issue-955-elevation-and-real-grid from main 264ae342. No adjacent creations.

The geometry correction replaces the absolute 3 m world-height cap with a vertical
budget of absolute wrapped along-track separation plus the existing 3 m positional
allowance. Both bounded spline and 3D Euclidean proximity remain required. This
allows separated cars on hills without selecting a new global height cap to fit
the two cases. A nearby overpass whose vertical separation exceeds that short
along-track budget still clears. This remains provisional scalar geometry, not a
road-topology or collision planner; fresh evaluation is mandatory.

The sampler also keeps its deadline phase across render-frame jitter. Missing
deadlines are skipped; each due update captures one real observation, never fake
catch-up frames. A 57 Hz jittered render test exercises nominal 10/20 Hz capture
and a hitch/no-burst control. Regressions cover both original missed observations,
larger same-road elevation changes and the existing overpass/adjacent controls.
Focused traffic/archive suite: 85 passed. Ruff and scoped CSP API checks passed.
No fresh-set predictions have been run. Rule is fixed before fresh data scoring.

Council returned 2/3 voices; quorum unmet. It suggested widening the fixed cap but
provided no physical calibration or verified 20-car download. Its absence claim
is not proof no replay exists. The distance-based budget was selected instead of
fitting a new fixed cap. Direct public research located an open-source native
replay writer (mishan/assetto-ts); inspect its format before any derived fixture.
Twenty-car loops inside a 54-car world remain excluded as actual-grid proof.

Previous successful native sample spans total 22.752 minutes. A conservative
accounting including the whole pre-first-capture rig hold and each capture through
sealing totals 46.39 minutes. Reserve at most 35 minutes for the next rig lock,
keeping the retained 90-minute cap with margin. No new capture has started. Keep
two-engineering-day scope, no autonomous driving/live race actuation, no live cue
activation, immutable raw inputs and fresh pre-change rig/config preservation.

Next: obtain a native 20-car world, source nonoverlapping unseen trajectories,
independently label and hash fresh45 before scoring, measure achieved 10/20 Hz and
native p99, preserve fail-closed/qualification behavior, then full CI and exact-head
review. Direct Tier-3 MCP unavailable; local ac_copilot prefetch succeeded with a
stale-endpoint warning. No agents, adjacent issues or extra sessions were created.
