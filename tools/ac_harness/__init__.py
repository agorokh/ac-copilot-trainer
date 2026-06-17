"""Off-sim (L0) Lua trace-replay harness for the AC Copilot Trainer coaching brain.

This package lets the agent regression-test the real CSP Lua coaching modules
under ``lupa`` against synthetic/recorded telemetry traces -- with NO Assetto
Corsa, NO Windows, NO WebSocket, and NO human. It is the cheapest, most
deterministic layer (L0) of the autonomous self-test harness for EPIC #154.

See :mod:`tools.ac_harness.trace_replay` for the runtime builder, the trace
synthesizer, and the schema-gated mock ``ac``/``car``/``sim`` tables.
"""

from __future__ import annotations

from tools.ac_harness.ai_line import ControlOutput, PurePursuit, load_ai_line
from tools.ac_harness.custom_ai import (
    CarControls,
    CarData,
    CustomAIController,
    SimState,
    SimStateController,
    car_controls_name,
    car_data_name,
    parse_car_data,
)
from tools.ac_harness.entry_launcher import (
    LAUNCH_MODES,
    ActuatorEvent,
    ColdRestartActuator,
    ContentManagerActuator,
    EntryActuator,
    EntryLauncher,
    EntryLauncherConfig,
    EntryLaunchResult,
    EntryLaunchUnsupported,
    EntryOutcome,
    EntryPhase,
    classify_entry_phase,
    make_actuator,
    normalize_race_ini_spawn_set,
)
from tools.ac_harness.lap_driver import DriveFrame, LapDriver
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
    # L2 detect-and-retry entry actuator loop.
    "LAUNCH_MODES",
    "ActuatorEvent",
    "ColdRestartActuator",
    "ContentManagerActuator",
    "EntryActuator",
    "EntryLauncher",
    "EntryLauncherConfig",
    "EntryLaunchResult",
    "EntryLaunchUnsupported",
    "EntryOutcome",
    "EntryPhase",
    "classify_entry_phase",
    "make_actuator",
    "normalize_race_ini_spawn_set",
    # L2 in-sim shared-memory oracle (on-track-entry detector).
    "AcGameStatus",
    "DrivingEntryDetector",
    "GraphicsSnapshot",
    "PhysicsSnapshot",
    "SharedMemoryReader",
    "SharedMemoryUnavailable",
    "parse_graphics",
    "parse_physics",
    # Custom-AI external-control actuator (autonomous drive of car 0).
    "CarControls",
    "CarData",
    "CustomAIController",
    "SimState",
    "SimStateController",
    "car_controls_name",
    "car_data_name",
    "parse_car_data",
    # Autonomous lap driver (orchestrates pure-pursuit + actuator into clean laps).
    "DriveFrame",
    "LapDriver",
    # Racing line loader + pure-pursuit controller.
    "ControlOutput",
    "PurePursuit",
    "load_ai_line",
]
