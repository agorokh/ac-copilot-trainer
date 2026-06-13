"""L0 off-sim Lua trace-replay harness (EPIC #154 Part A + Part B bootstrap).

Runs the REAL CSP coaching modules under ``lupa`` against synthetic telemetry
traces, with a LuaJIT<->lupa parity shim and a *schema-gated* mock ``car``/``sim``
so a test that drifts onto a hallucinated CSP field fails loudly instead of
silently passing.

Public surface:

* :func:`load_schema` / :class:`AcSchema` -- the code-derived ``ac_schema.json``.
* :class:`TraceReplayHarness` -- builds the runtime, loads modules, mints gated
  ``car``/``sim`` tables and converts traces to Lua.
* :func:`synthesize_trace` -- emits named telemetry scenarios as plain frames.
* :class:`SchemaViolationError` -- raised (from Lua) when a non-schema field is read.

Nothing here imports Assetto Corsa, Windows, or a WebSocket. The only heavy dep
is ``lupa`` (already a dev dependency).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

# Repo + module layout. trace_replay.py lives at tools/ac_harness/; the modules
# are at src/ac_copilot_trainer/modules/ and the parity shim at tests/fixtures/.
_HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = _HARNESS_DIR.parent.parent
MODULES_DIR = REPO_ROOT / "src" / "ac_copilot_trainer" / "modules"
PARITY_SHIM = REPO_ROOT / "tests" / "fixtures" / "csp_luajit_parity.lua"
SCHEMA_PATH = _HARNESS_DIR / "ac_schema.json"

# A telemetry frame the modules consume. Field names match exactly what
# telemetry.lua / brake_detection.lua / corner_analysis.lua read off the trace
# rows and the live car table (see ac_schema.json / the module sources):
#   spline, speed, eMs, throttle, brake, steer, gear, px, py, pz
TraceFrame = dict[str, float]


class SchemaViolationError(RuntimeError):
    """Raised when Lua code reads a ``car``/``sim`` field absent from the schema.

    The mock tables installed by :class:`TraceReplayHarness` raise a Lua error
    whose message is prefixed with ``SCHEMA-VIOLATION:``; lupa surfaces that as a
    ``LuaError`` which the harness re-raises as this type so tests can assert on
    it without importing lupa internals.
    """


@dataclass(frozen=True)
class AcSchema:
    """The set of ``car.*`` / ``sim.*`` fields the trainer is allowed to read.

    Built from ``ac_schema.json`` (code-derived bootstrap). ``car_vec3`` maps a
    vec3-typed car field (``look``/``position``/``velocity``) to its allowed
    sub-fields, so the mock can gate ``car.position.x`` too.
    """

    car_fields: frozenset[str]
    sim_fields: frozenset[str]
    car_vec3: dict[str, frozenset[str]] = field(default_factory=dict)
    note: str = ""


def load_schema(path: Path | str = SCHEMA_PATH) -> AcSchema:
    """Load and parse ``ac_schema.json`` into an :class:`AcSchema`."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    car_spec = raw.get("car", {})
    sim_spec = raw.get("sim", {})
    car_vec3: dict[str, frozenset[str]] = {}
    for name, spec in car_spec.items():
        if isinstance(spec, dict) and spec.get("type") == "vec3":
            sub = spec.get("fields", {})
            car_vec3[name] = frozenset(sub.keys()) if sub else frozenset({"x", "y", "z"})
    return AcSchema(
        car_fields=frozenset(car_spec.keys()),
        sim_fields=frozenset(sim_spec.keys()),
        car_vec3=car_vec3,
        note=str(raw.get("_note", "")),
    )


# Lua factory that wraps a backing table in a schema gate: reads of a key NOT in
# the allowlist raise a Lua error. vec3 sub-tables are themselves gated. This is
# defined once and `require`-free so it works under a bare LuaRuntime.
_SCHEMA_GATE_LUA = r"""
-- _make_gated(backing, allowed, kind) returns a proxy table that:
--   * returns backing[k] when k is in `allowed` (a set: allowed[k] == true)
--   * raises "SCHEMA-VIOLATION: <kind>.<k> ..." otherwise
-- Reads that are present-but-nil are allowed (the modules use `car.x or 0`),
-- but reads of a key the schema never declared are hard errors.
function _make_gated(backing, allowed, kind)
  local proxy = {}
  return setmetatable(proxy, {
    __index = function(_, k)
      if allowed[k] then
        return backing[k]
      end
      error("SCHEMA-VIOLATION: " .. tostring(kind) .. "." .. tostring(k)
        .. " is not a declared CSP field in ac_schema.json"
        .. " (the trainer must not read it, or refresh the schema via dump_schema.lua)", 2)
    end,
    __newindex = function(_, k, v)
      rawset(backing, k, v)
    end,
    -- Expose the backing length / pairs for completeness (not gated).
    __len = function() return #backing end,
  })
end
"""

# Minimal mock of the CSP globals the modules touch when NOT going through the
# schema-gated car/sim. telemetry.lua requires csp_helpers which references the
# `ac` global only inside functions we do not call on the hot path; brake/tick do
# not need ac/ui/web/physics at all. We still install thin stubs so a module that
# touches them at require-time does not explode, mirroring the established
# test_lua_runtime_smoke.py / test_phase5_rebuild_ete.py pattern.
_MOCK_GLOBALS_LUA = r"""
ac = ac or {
  log = function() end,
  getFolder = function() return "" end,
  FolderID = { Root = 0, AppLuaRoot = 1, ScriptConfig = 2 },
}
ui = ui or {}
-- web.socket is callback-based in CSP; the harness never opens one, but provide a
-- no-op so a require of ws_bridge (if ever pulled in) does not throw.
web = web or {
  socket = function() return { close = function() end } end,
}
physics = physics or {}
function _vec3(x, y, z) return { x = x or 0, y = y or 0, z = z or 0 } end
vec3 = vec3 or _vec3
function _vec2(x, y) return { x = x or 0, y = y or 0 } end
vec2 = vec2 or _vec2
"""


class TraceReplayHarness:
    """A lupa runtime preloaded for off-sim coaching-module replay.

    Usage::

        h = TraceReplayHarness()
        bd = h.require("brake_detection")
        det = bd.new(h.lua.table())
        car = h.make_car(brake=0.0, speedKmh=180.0, splinePosition=0.2)
        ev = det.update(det, car, 0.016)
    """

    def __init__(self, schema: AcSchema | None = None) -> None:
        import lupa

        self._lupa = lupa
        self.schema = schema if schema is not None else load_schema()
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=False)
        # package.path -> modules dir (mirrors the established smoke-test setup).
        modules_path = str(MODULES_DIR).replace("\\", "/")
        self.lua.execute(f'package.path = package.path .. ";{modules_path}/?.lua"')
        # Parity shim FIRST so any module that uses math.atan2 etc. works on call.
        self.lua.execute(PARITY_SHIM.read_text(encoding="utf-8"))
        # Mock globals + the schema-gate factory.
        self.lua.execute(_MOCK_GLOBALS_LUA)
        self.lua.execute(_SCHEMA_GATE_LUA)
        # Pre-build the allowed-field sets as Lua sets once.
        self._car_allowed = self._as_lua_set(self.schema.car_fields)
        self._sim_allowed = self._as_lua_set(self.schema.sim_fields)
        self._vec3_allowed = {
            name: self._as_lua_set(subs) for name, subs in self.schema.car_vec3.items()
        }

    # -- module loading -----------------------------------------------------

    def require(self, module_name: str) -> Any:  # noqa: ANN401 - lupa table
        """``require()`` a coaching module by name and return its table.

        ``require`` returns two values (module, loader-path); execute() with an
        explicit single return so lupa hands back only the module table.
        """
        return self.lua.execute(f'local m = require("{module_name}"); return m')

    # -- Lua interop helpers -------------------------------------------------

    def _as_lua_set(self, names: frozenset[str] | set[str]) -> Any:  # noqa: ANN401
        """Build a Lua table used as a set: ``{name = true, ...}``."""
        tbl = self.lua.table()
        for n in names:
            tbl[n] = True
        return tbl

    def to_lua_trace(self, frames: Sequence[TraceFrame]) -> Any:  # noqa: ANN401
        """Convert a Python list of frame dicts into a 1-indexed Lua array."""
        arr = self.lua.table()
        for i, frame in enumerate(frames, start=1):
            row = self.lua.table()
            for k, v in frame.items():
                row[k] = v
            arr[i] = row
        return arr

    # -- schema-gated mock car/sim ------------------------------------------

    def make_car(self, **fields: Any) -> Any:  # noqa: ANN401 - returns Lua table
        """Build a schema-gated mock ``car`` table.

        Only keys present in ``schema.car_fields`` may be read back; reading any
        other key raises a Lua ``SCHEMA-VIOLATION`` error. vec3 fields
        (``position``/``look``/``velocity``) are passed as ``(x, y, z)`` tuples
        or dicts and are themselves gated on their sub-fields.
        """
        backing = self.lua.table()
        for name, value in fields.items():
            if name in self._vec3_allowed:
                backing[name] = self._make_vec3(name, value)
            else:
                backing[name] = value
        gate = self.lua.globals()._make_gated
        return gate(backing, self._car_allowed, "car")

    def make_sim(self, **fields: Any) -> Any:  # noqa: ANN401 - returns Lua table
        """Build a schema-gated mock ``sim`` table (same gating as ``make_car``)."""
        backing = self.lua.table()
        for name, value in fields.items():
            backing[name] = value
        gate = self.lua.globals()._make_gated
        return gate(backing, self._sim_allowed, "sim")

    def _make_vec3(self, field_name: str, value: Any) -> Any:  # noqa: ANN401
        """Gate a vec3 sub-table on its allowed sub-fields (x/y/z)."""
        if isinstance(value, dict):
            x, y, z = value.get("x", 0.0), value.get("y", 0.0), value.get("z", 0.0)
        elif isinstance(value, (tuple, list)):
            x, y, z = (list(value) + [0.0, 0.0, 0.0])[:3]
        else:  # already a Lua table or scalar -- pass through ungated
            return value
        backing = self.lua.table()
        backing["x"], backing["y"], backing["z"] = x, y, z
        allowed = self._vec3_allowed[field_name]
        gate = self.lua.globals()._make_gated
        return gate(backing, allowed, f"car.{field_name}")

    # -- error translation ---------------------------------------------------

    def call_guarding_schema(self, fn: Any, *args: Any) -> Any:  # noqa: ANN401
        """Call a Lua function, translating SCHEMA-VIOLATION Lua errors.

        Re-raises as :class:`SchemaViolationError` so tests do not depend on
        ``lupa``'s exception type.
        """
        try:
            return fn(*args)
        except self._lupa.LuaError as exc:  # pragma: no cover - exercised in tests
            if "SCHEMA-VIOLATION" in str(exc):
                raise SchemaViolationError(str(exc)) from exc
            raise


# ---------------------------------------------------------------------------
# Trace synthesis
# ---------------------------------------------------------------------------

# Scenario knobs kept module-level so tests can reference the same constants the
# generator uses (e.g. the braking spline / entry speed they assert on).
SCENARIO_TRACK_LENGTH_M = 4500.0
BRAKE_SPLINE = 0.20  # where the "brake too late" scenario starts braking
BRAKE_ENTRY_SPEED_KMH = 180.0  # speed at the moment brake is first applied
CLEAN_LAP_FRAMES = 240
DT_S = 0.05  # 20 Hz synthetic sampling


def _base_frame(
    *,
    spline: float,
    speed: float,
    e_ms: float,
    throttle: float = 1.0,
    brake: float = 0.0,
    steer: float = 0.0,
    gear: int = 4,
    px: float = 0.0,
    py: float = 0.0,
    pz: float = 0.0,
) -> TraceFrame:
    return {
        "spline": spline,
        "speed": speed,
        "eMs": e_ms,
        "throttle": throttle,
        "brake": brake,
        "steer": steer,
        "gear": float(gear),
        "px": px,
        "py": py,
        "pz": pz,
    }


def _clean_lap(n: int = CLEAN_LAP_FRAMES) -> list[TraceFrame]:
    """A smooth lap: speed never spikes-then-drops sharply, light steering.

    Designed so corner_analysis does NOT detect spurious speed-minima corners
    and realtime_coaching has nothing urgent to say (the false-positive guard).
    Speed is a gentle sinusoid well above the in-corner thresholds.
    """
    frames: list[TraceFrame] = []
    for i in range(n):
        sp = i / (n - 1)
        # Gentle speed undulation 150..210 km/h; amplitude < the 8 km/h corner
        # dead band per local window, so no false "minima" corners.
        speed = 180.0 + 30.0 * math.sin(sp * 2.0 * math.pi)
        steer = 0.03 * math.sin(sp * 4.0 * math.pi)  # mild, below 0.12 corner gate
        frames.append(
            _base_frame(
                spline=sp,
                speed=speed,
                e_ms=sp * 90000.0,
                throttle=0.95,
                brake=0.0,
                steer=steer,
                gear=5,
                px=sp * 100.0,
            )
        )
    return frames


def _brake_too_late_lap(
    *,
    brake_spline: float = BRAKE_SPLINE,
    entry_speed: float = BRAKE_ENTRY_SPEED_KMH,
) -> list[TraceFrame]:
    """A lap with one hard, sustained braking zone at ``brake_spline``.

    Built so brake_detection emits exactly one qualified brake event with
    ``entrySpeed == entry_speed`` and ``spline == brake_spline``:
      * full throttle up to brake_spline,
      * brake held > 0.3 for well over brakeDurationMin (0.5 s) across several
        frames (the modeled corner), speed bleeding down,
      * brake released after the corner -> event fires on release.
    """
    frames: list[TraceFrame] = []
    n_pre = 60
    n_brake = 24  # 24 * 0.05 s = 1.2 s of braking >> 0.5 s minimum
    n_post = 80
    total = n_pre + n_brake + n_post
    idx = 0

    def push(sp: float, speed: float, brake: float, steer: float, e_ms: float) -> None:
        frames.append(
            _base_frame(
                spline=sp,
                speed=speed,
                e_ms=e_ms,
                throttle=0.0 if brake > 0 else 0.95,
                brake=brake,
                steer=steer,
                gear=4 if brake > 0 else 5,
                px=sp * 100.0,
            )
        )

    # Pre-brake straight: accelerate up to entry_speed, arriving AT brake_spline.
    for i in range(n_pre):
        sp = (i / n_pre) * brake_spline
        speed = 120.0 + (entry_speed - 120.0) * (i / max(1, n_pre - 1))
        push(sp, speed, 0.0, 0.0, idx * DT_S * 1000.0)
        idx += 1

    # Braking zone: spline advances slowly through the corner, speed drops, brake
    # firmly above threshold so it QUALIFIES; entrySpeed is captured on the FIRST
    # braking frame -> equals entry_speed exactly.
    for i in range(n_brake):
        sp = brake_spline + (i / n_brake) * 0.04
        speed = entry_speed - (entry_speed - 90.0) * (i / max(1, n_brake - 1))
        push(sp, speed, 0.9, 0.25 * math.sin(i / n_brake * math.pi), idx * DT_S * 1000.0)
        idx += 1

    # Post-corner: brake released (event fires here), accelerate away.
    for i in range(n_post):
        sp = (brake_spline + 0.04) + (i / n_post) * (1.0 - (brake_spline + 0.04))
        speed = 90.0 + 100.0 * (i / max(1, n_post - 1))
        push(sp, speed, 0.0, 0.0, idx * DT_S * 1000.0)
        idx += 1

    assert len(frames) == total
    return frames


_SCENARIOS = {
    "clean_lap": _clean_lap,
    "brake_too_late": _brake_too_late_lap,
}


def synthesize_trace(scenario: str, **kwargs: Any) -> list[TraceFrame]:
    """Return a list of telemetry frames for a named scenario.

    Supported scenarios:

    * ``"clean_lap"`` -- a smooth lap with no hard braking and no spurious
      corners (the false-positive guard input).
    * ``"brake_too_late"`` -- a lap with one sustained braking zone at
      ``BRAKE_SPLINE`` entering at ``BRAKE_ENTRY_SPEED_KMH``; produces exactly
      one brake event.

    Frame fields match what the modules read:
    ``spline, speed, eMs, throttle, brake, steer, gear, px, py, pz``.
    """
    try:
        builder = _SCENARIOS[scenario]
    except KeyError as exc:
        valid = ", ".join(sorted(_SCENARIOS))
        raise ValueError(f"unknown scenario {scenario!r}; valid: {valid}") from exc
    return builder(**kwargs)


def available_scenarios() -> list[str]:
    """Names accepted by :func:`synthesize_trace`."""
    return sorted(_SCENARIOS)
