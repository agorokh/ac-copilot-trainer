---
type: project-state
status: active
memory_tier: canonical
last_updated: 2026-06-30
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/glossary/_index.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Project state

## What this is

Real-time driver-coaching system for Assetto Corsa: an in-game CSP Lua HUD + a Python
WebSocket sidecar that diagnoses driving and delivers coaching as on-screen hints, voice
cues, and a physical ESP32 rig touchscreen, plus an autonomous self-test harness.

## Milestone

Past template bootstrap and well into product build-out. The **real-time + per-lap**
coaching path is shipped and live-verified; the **longitudinal** layer (driver model,
progression, session review, retention) is the current frontier — planned in
[Roadmap.md](Roadmap.md) / [umbrella #401](https://github.com/agorokh/ac-copilot-trainer/issues/401).

## Services / subsystems (shipped)

- **Sidecar** (`tools/ai_sidecar/`) — WS v1 hub; real-time diagnosis (`coaching_diagnosis.py`,
  `trail_brake.py`), anticipatory cueing (`coaching_runtime.py`), conditions/tyre/setup models.
- **Voice coach** (`tools/ai_sidecar/voice/`) — pre-baked phrase bank + urgency scheduler.
- **Data lakehouse** (`tools/coaching_lake/`) — DuckDB star schema rebuilt from immutable
  lap archives (`journal/laps/`); [DuckDB-over-ClickHouse decision](../01_Decisions/duckdb-over-clickhouse-storage-2026-06-29.md).
- **Reference** (`track_reference.py`) — GGV ceiling + corpus envelope; Track Titan ingest (`tools/tt_ingest/`).
- **Surfaces** — in-game HUD (`src/ac_copilot_trainer/`), ESP32 rig screen (`firmware/screen/`),
  Windows Game Point launcher (`tools/rig_launcher/`).
- **Autonomy** (`tools/ac_harness/`) — one-command self-test: launch → carcsw drive → coaching assert.

## Known gaps (tracked)

Driver/session/stint entities + retention (#402); driver model & curriculum (#403, biggest);
session review/trends/reports (#404); diagnosis depth (#405); fuel/brake/tyre management (#406);
setup↔feedback closed loop (#407); reference depth (#408). Full matrix in [#401](https://github.com/agorokh/ac-copilot-trainer/issues/401).

## Canonical references (do not duplicate here)

- **Roadmap:** [Roadmap.md](Roadmap.md)
- **Invariants:** [invariants/_index.md](invariants/_index.md)
- **Glossary:** [glossary/_index.md](glossary/_index.md)
