"""Off-sim (L0) Lua trace-replay harness for the AC Copilot Trainer coaching brain.

This package lets the agent regression-test the real CSP Lua coaching modules
under ``lupa`` against synthetic/recorded telemetry traces -- with NO Assetto
Corsa, NO Windows, NO WebSocket, and NO human. It is the cheapest, most
deterministic layer (L0) of the autonomous self-test harness for EPIC #154.

See :mod:`tools.ac_harness.trace_replay` for the runtime builder, the trace
synthesizer, and the schema-gated mock ``ac``/``car``/``sim`` tables.
"""

from __future__ import annotations

from tools.ac_harness.shared_memory import (
    AcGameStatus,
    DrivingEntryDetector,
    GraphicsSnapshot,
    PhysicsSnapshot,
    SharedMemoryReader,
    SharedMemoryUnavailable,
    parse_graphics,
    parse_physics,
)
from tools.ac_harness.trace_replay import (
    AcSchema,
    SchemaViolationError,
    TraceReplayHarness,
    load_schema,
    synthesize_trace,
)

__all__ = [
    # L0 off-sim trace-replay harness.
    "AcSchema",
    "SchemaViolationError",
    "TraceReplayHarness",
    "load_schema",
    "synthesize_trace",
    # L2 in-sim shared-memory oracle (on-track-entry detector).
    "AcGameStatus",
    "DrivingEntryDetector",
    "GraphicsSnapshot",
    "PhysicsSnapshot",
    "SharedMemoryReader",
    "SharedMemoryUnavailable",
    "parse_graphics",
    "parse_physics",
]
