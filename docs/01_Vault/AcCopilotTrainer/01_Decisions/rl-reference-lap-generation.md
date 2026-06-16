---
type: decision
status: active
created: 2026-06-16
updated: 2026-06-16
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/116
relates_to:
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/01_Decisions/autonomous-self-test-harness.md
  - AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md
---

# Decision: generated reference laps before RL training

## Context

Issue #116 asks whether this project should pursue RL training, TUMFTM-style trajectory generation, or deferral for
reference-lap generation. The current repo already has a lap archive schema v1 (`lap_archive.lua`) and a live coaching
path that loads `bestLapTrace` from the trainer persistence payload. EPIC #154 also established that deterministic
L0/L1/L1.5 harnesses are the priority, while in-sim truth is handled by the Custom AI driver rather than replay.

External grounding:

- TUMFTM `global_racetrajectory_optimization` supports shortest-path, minimum-curvature, minimum-time, and powertrain
  objectives, and its README notes minimum-time optimization needs more parameters and more compute than
  minimum-curvature: https://github.com/TUMFTM/global_racetrajectory_optimization.
- CommonRoad Raceline Planner exposes FTM shortest-path/minimum-curvature planner surfaces based on TUMFTM helpers:
  https://commonroad-raceline-planner-feb47b.pages.gitlab.lrz.de/spp/.
- AssettoCorsaGym is a real Assetto Corsa Gym/RL benchmark with SAC baselines, datasets, plugin setup, track occupancy
  assets, and optional large dataset downloads: https://github.com/dasGringuen/assetto_corsa_gym.
- Stable-Baselines3 SAC expects a continuous `Box` action space, so using SAC here would require a bounded action
  interface plus a repeatable simulator loop, not just a Python dependency:
  https://stable-baselines3.readthedocs.io/en/master/modules/sac.html.

## Decision

Defer RL training as a product/runtime feature. Do not add `assetto_corsa_gym`, `stable-baselines3`, PyTorch, GPU
training, or simulator plugin dependencies to `make ci-fast`.

Pursue a deterministic generated-reference path first:

1. Generate reference traces into the existing lap archive schema v1 with `source: "imported"` and
   `import_format: "generated_reference_v1"`.
2. Keep the prototype stdlib-only and off-sim under `tools/ac_harness/reference_lap.py`.
3. Provide an explicit bridge from archive rows to the live trainer persistence fragment:
   `bestLapTrace`, `bestReferenceLapMs`, `bestLapMs`, `bestBrakePoints`, and `bestCornerFeatures`.
4. Treat future TUMFTM/CommonRoad output as another producer of the same object-frame list passed to
   `build_archive_record`; do not let solver-specific schemas leak into the trainer.

## Runtime boundary

Current prototype requirements:

- Python 3.11+ stdlib only.
- No Assetto Corsa process, Windows host, GPU, Gym, PyTorch, or TUMFTM dependency.
- Covered by `tests/test_reference_lap.py`, so schema compatibility is checked inside `make ci-fast`.

Future optional trajectory/RL work must stay isolated behind an opt-in command or extra, with fixture output committed
only after conversion to schema v1. A real RL training loop needs a separate issue with simulator lifecycle,
action-space bounds, data volume, and acceptance metrics.

## How a generated reference enters the comparison path

The generated archive record is the immutable dataset artifact. To make it active for live coaching, an importer should
merge `build_trainer_reference_payload(record)` into the per-car/track trainer persistence JSON. On next load, the app's
existing `applyLoaded` path normalizes `bestLapTrace`, builds `bestSortedTrace`, derives sector deltas, and exposes the
reference to real-time coaching and `delta`.

This PR intentionally stops at the generator/validator/bridge seam. It does not auto-install generated references into
the live CSP data folder, because that write path needs a separate UI or explicit import command and in-sim validation.

## Consequences

- Issue #116 has an evidence-backed go/no-go: RL deferred, deterministic generated references accepted.
- The prototype emits one schema-compatible reference lap today and can emit a trainer-state payload for a future
  importer.
- The main runtime remains dependency-free and CI remains game-free.
- TUMFTM integration remains useful, but it is now a producer behind the archive adapter rather than an architectural
  dependency of the trainer.
