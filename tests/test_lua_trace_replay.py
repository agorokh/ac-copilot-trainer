"""L0 off-sim Lua trace-replay tests (EPIC #154 Part A + Part B bootstrap).

These run the REAL CSP coaching modules under ``lupa`` against synthetic
telemetry traces -- no Assetto Corsa, no Windows, no WebSocket, no human. Unlike
``tests/test_lua_runtime_smoke.py`` (which only ``require()``s the modules and so
never exercised the ``math.atan2`` LuaJIT-parity gap), every test here actually
CALLS ``:update`` / ``tick`` and asserts the coaching OUTPUTS.

The module contracts asserted on were verified against the real source:

* ``brake_detection.lua`` -- ``M.new(cfg)`` -> ``:update(car, dt)`` emits a brake
  event ``{spline, px, py, pz, entrySpeed, heading}`` on brake RELEASE after the
  hold qualifies (``brakeDurationMin`` 0.5 s). Uses ``math.atan2`` for heading.
* ``realtime_coaching.lua`` -- ``M.tick(opts)`` returns a viewmodel with
  ``primaryLine`` in {"DRIVE A LAP","BRAKE NOW","PREPARE TO BRAKE",
  "CARRY MORE SPEED","EASE OFF","APPROACHING","ON PACE"} plus ``kind`` /
  ``subState`` / ``cornerLabel`` / ``targetSpeedKmh`` / ``distToBrakeM``.
* ``corner_analysis.lua`` -- ``M.buildSegments(trace, brakePoints)`` /
  ``M.cornerFeaturesForLap(trace, segments)``.
* ``delta.lua`` -- ``M.prepareTrace`` / ``M.bestElapsedMsAtSpline`` /
  ``M.deltaSecondsAtSpline``.
* ``telemetry.lua`` -- ``:update(dt, car, sim)`` (note arg order) -> per-lap
  trace via ``finalizeLapTrace``.
"""

from __future__ import annotations

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

from tools.ac_harness.trace_replay import (  # noqa: E402 - after importorskip
    BRAKE_ENTRY_SPEED_KMH,
    BRAKE_SPLINE,
    SchemaViolationError,
    TraceReplayHarness,
    available_scenarios,
    load_schema,
    synthesize_trace,
)


@pytest.fixture
def harness() -> TraceReplayHarness:
    """A fresh lupa harness per test (modules carry module-level state)."""
    return TraceReplayHarness()


def _replay_brake_detection(
    harness: TraceReplayHarness, frames: list[dict[str, float]]
) -> list[dict[str, float]]:
    """Drive brake_detection:update over a trace; return emitted brake events."""
    bd = harness.require("brake_detection")
    det = bd.new(harness.lua.table())
    events: list[dict[str, float]] = []
    for f in frames:
        car = harness.make_car(
            brake=f["brake"],
            speedKmh=f["speed"],
            splinePosition=f["spline"],
            position={"x": f["px"], "y": f["py"], "z": f["pz"]},
            look={"x": 1.0, "y": 0.0, "z": 0.0},
        )
        ev = harness.call_guarding_schema(det.update, det, car, 0.05)
        if ev is not None:
            events.append(
                {
                    "spline": float(ev["spline"]),
                    "entrySpeed": float(ev["entrySpeed"]),
                    "heading": float(ev["heading"]),
                }
            )
    return events


# ---------------------------------------------------------------------------
# brake_detection :update -- the test that would have caught the atan2 gap
# ---------------------------------------------------------------------------


def test_brake_detection_emits_event_for_braking_scenario(harness: TraceReplayHarness) -> None:
    """L0-01: the 'brake_too_late' trace produces exactly one brake event with the
    expected entrySpeed and spline. This CALLS :update (exercising math.atan2 via
    flatHeading), which the require()-only smoke test never did."""
    frames = synthesize_trace("brake_too_late")
    events = _replay_brake_detection(harness, frames)

    assert len(events) == 1, f"expected exactly one brake event, got {len(events)}: {events}"
    ev = events[0]
    assert ev["entrySpeed"] == pytest.approx(BRAKE_ENTRY_SPEED_KMH, abs=0.01), (
        f"entrySpeed must be the speed at first brake frame ({BRAKE_ENTRY_SPEED_KMH}), "
        f"got {ev['entrySpeed']}"
    )
    assert ev["spline"] == pytest.approx(BRAKE_SPLINE, abs=1e-6), (
        f"brake event spline must be the braking-zone start ({BRAKE_SPLINE}), got {ev['spline']}"
    )
    # heading came back as a real number => math.atan2 parity shim worked.
    assert isinstance(ev["heading"], float)


def test_brake_detection_clean_lap_emits_no_event(harness: TraceReplayHarness) -> None:
    """L0-02 (FALSE-POSITIVE GUARD): a clean lap with zero braking must produce NO
    brake events. A detector that fired here would generate phantom brake points."""
    frames = synthesize_trace("clean_lap")
    events = _replay_brake_detection(harness, frames)
    assert events == [], f"clean lap must emit no brake events, got {events}"


def test_brake_detection_short_tap_does_not_qualify(harness: TraceReplayHarness) -> None:
    """L0-03: a sub-threshold-duration brake tap (< brakeDurationMin 0.5 s) must
    NOT qualify as a brake point -- guards against twitch-braking false events."""
    bd = harness.require("brake_detection")
    det = bd.new(harness.lua.table())
    # 3 frames * 0.05 s = 0.15 s of braking, then release => below the 0.5 s floor.
    seq = [
        (0.10, 0.0, 150.0),
        (0.11, 0.9, 150.0),
        (0.12, 0.9, 140.0),
        (0.13, 0.9, 130.0),
        (0.14, 0.0, 120.0),
    ]
    fired = False
    for spline, brake, speed in seq:
        car = harness.make_car(
            brake=brake,
            speedKmh=speed,
            splinePosition=spline,
            position={"x": 0.0, "y": 0.0, "z": 0.0},
            look={"x": 1.0, "y": 0.0, "z": 0.0},
        )
        if harness.call_guarding_schema(det.update, det, car, 0.05) is not None:
            fired = True
    assert not fired, "a 0.15 s brake tap must not qualify (brakeDurationMin = 0.5 s)"


# ---------------------------------------------------------------------------
# realtime_coaching tick -- should-brake vs on-pace
# ---------------------------------------------------------------------------


def _brake_points_and_segments(harness: TraceReplayHarness) -> tuple:
    """A single low-entry-speed brake point at T1 plus matching segments."""
    brakes = harness.lua.execute(
        """return {
            { spline = 0.20, px = 0, py = 0, pz = 0, entrySpeed = 95, label = "T1" },
        }"""
    )
    segs = harness.lua.execute(
        """return {
            { kind = "brake",    s0 = 0.18, s1 = 0.20, label = "B1" },
            { kind = "corner",   s0 = 0.20, s1 = 0.26, label = "T1", brakeSpline = 0.18 },
            { kind = "straight", s0 = 0.26, s1 = 1.00, label = "S1" },
        }"""
    )
    return brakes, segs


def test_realtime_coaching_should_brake_says_brake_now(harness: TraceReplayHarness) -> None:
    """L0-04: ~31 m before T1 (target 95) at 142 km/h must say 'BRAKE NOW' with
    kind='brake', a 'TARGET 95 KM/H' secondary, and cornerLabel 'T1'."""
    rtc = harness.require("realtime_coaching")
    rtc.reset()
    brakes, segs = _brake_points_and_segments(harness)
    # 31 m / 4500 m = 0.0069 ahead of 0.20 => splinePos 0.193.
    opts = harness.lua.table()
    opts["splinePos"] = 0.193
    opts["currentSpeedKmh"] = 142
    opts["brakingPoints"] = brakes
    opts["segments"] = segs
    opts["trackLengthM"] = 4500
    view = rtc.tick(opts)

    assert view is not None
    assert view["primaryLine"] == "BRAKE NOW", (
        f"~31 m before T1 (target 95) at 142 km/h must say 'BRAKE NOW', got {view['primaryLine']!r}"
    )
    assert view["kind"] == "brake", f"kind must be 'brake', got {view['kind']!r}"
    assert view["subState"] == "braking", f"subState must be 'braking', got {view['subState']!r}"
    assert "TARGET" in (view["secondaryLine"] or ""), (
        f"secondary must show the target speed, got {view['secondaryLine']!r}"
    )
    assert view["cornerLabel"] == "T1", f"cornerLabel must be 'T1', got {view['cornerLabel']!r}"
    assert view["targetSpeedKmh"] == 95, f"targetSpeedKmh must be 95, got {view['targetSpeedKmh']}"


def test_realtime_coaching_on_pace_clean(harness: TraceReplayHarness) -> None:
    """L0-05 (FALSE-POSITIVE GUARD): on a straight far from the next brake point and
    not over-speed, the viewmodel must be informational ('ON PACE' / 'APPROACHING'),
    NEVER an urgent brake/line hint. No false coaching on a clean stretch."""
    rtc = harness.require("realtime_coaching")
    rtc.reset()
    brakes, segs = _brake_points_and_segments(harness)
    opts = harness.lua.table()
    opts["splinePos"] = 0.50  # far past T1, on the long straight
    opts["currentSpeedKmh"] = 200
    opts["brakingPoints"] = brakes
    opts["segments"] = segs
    opts["trackLengthM"] = 4500
    view = rtc.tick(opts)

    assert view is not None
    primary = (view["primaryLine"] or "").upper()
    assert view["kind"] == "info", (
        f"a clean straight must yield kind='info', got {view['kind']!r} ({primary!r})"
    )
    assert "BRAKE" not in primary, f"clean straight must NOT raise a brake hint, got {primary!r}"
    assert any(word in primary for word in ("ON PACE", "APPROACHING", "FREE", "NEXT")), (
        f"clean straight viewmodel must be informational, got {primary!r}"
    )


def test_realtime_coaching_empty_state_is_placeholder(harness: TraceReplayHarness) -> None:
    """L0-06: with NO reference data at all, tick returns the placeholder viewmodel
    ('DRIVE A LAP' / subState 'no_reference') and never nil."""
    rtc = harness.require("realtime_coaching")
    rtc.reset()
    opts = harness.lua.table()
    opts["splinePos"] = 0.5
    opts["currentSpeedKmh"] = 90
    opts["brakingPoints"] = harness.lua.table()
    opts["segments"] = harness.lua.table()
    opts["trackLengthM"] = 4500
    view = rtc.tick(opts)

    assert view is not None, "tick must never return nil"
    assert view["primaryLine"] == "DRIVE A LAP", (
        f"empty state must say 'DRIVE A LAP', got {view['primaryLine']!r}"
    )
    assert view["subState"] == "no_reference", (
        f"empty state subState must be 'no_reference', got {view['subState']!r}"
    )


# ---------------------------------------------------------------------------
# corner_analysis + delta end-to-end on a synthesized + telemetry-ingested trace
# ---------------------------------------------------------------------------


def test_telemetry_ingest_then_corner_and_delta_pipeline(harness: TraceReplayHarness) -> None:
    """L0-07: feed a synthesized lap through telemetry:update(dt, car, sim), finalize
    the lap trace, then run corner_analysis.buildSegments + cornerFeaturesForLap and
    delta.prepareTrace + bestElapsedMsAtSpline + deltaSecondsAtSpline end-to-end."""
    tel = harness.require("telemetry")
    ca = harness.require("corner_analysis")
    dl = harness.require("delta")

    frames = synthesize_trace("brake_too_late")

    # Ingest via the real telemetry buffer. NOTE arg order: update(dt, car, sim).
    t = tel.new(harness.lua.table())
    t.beginLapClock(t, 0.0)
    game_time = 0.0
    for f in frames:
        car = harness.make_car(
            brake=f["brake"],
            gas=f["throttle"],
            steer=f["steer"],
            gear=int(f["gear"]),
            speedKmh=f["speed"],
            splinePosition=f["spline"],
            position={"x": f["px"], "y": f["py"], "z": f["pz"]},
        )
        sim = harness.make_sim(isInMainMenu=False, gameTime=game_time)
        harness.call_guarding_schema(t.update, t, 0.05, car, sim)
        game_time += 0.05

    lap_trace = t.finalizeLapTrace(t)
    rows = harness.lua.eval("function(tr) return #tr end")(lap_trace)
    assert rows > 0, "telemetry must produce a non-empty lap trace"

    # corner_analysis: with an explicit brake point we get a real 'corner' segment.
    brakes = harness.lua.execute(
        f"""return {{
            {{ spline = {BRAKE_SPLINE}, px = 0, py = 0, pz = 0, entrySpeed = 95, label = "T1" }},
        }}"""
    )
    segs = ca.buildSegments(lap_trace, brakes)
    nseg = harness.lua.eval("function(s) return #s end")(segs)
    assert nseg >= 2, f"buildSegments must produce a brake+corner pair, got {nseg} segments"
    kinds = harness.lua.eval(
        "function(s) local o = {} for i = 1, #s do o[i] = s[i].kind end "
        'return table.concat(o, ",") end'
    )(segs)
    assert "corner" in kinds, f"buildSegments must classify a corner, got kinds: {kinds!r}"

    feats = ca.cornerFeaturesForLap(lap_trace, segs)
    nfeat = harness.lua.eval("function(s) return #s end")(feats)
    assert nfeat >= 1, "cornerFeaturesForLap must extract at least one corner feature"

    # delta: sorted view + interpolation must return finite numbers.
    sorted_tr = dl.prepareTrace(lap_trace)
    assert sorted_tr is not None, "prepareTrace must return a sorted trace"
    elapsed = dl.bestElapsedMsAtSpline(sorted_tr, 0.5)
    assert elapsed is not None and elapsed > 0, "bestElapsedMsAtSpline(0.5) must be positive"
    dsec = dl.deltaSecondsAtSpline(sorted_tr, 0.5, elapsed + 1000.0)
    assert dsec == pytest.approx(1.0, abs=1e-6), (
        f"deltaSecondsAtSpline with +1000 ms current must be +1.0 s, got {dsec}"
    )


# ---------------------------------------------------------------------------
# Schema gate -- the anti-hallucination guard fires
# ---------------------------------------------------------------------------


def test_schema_gate_blocks_unknown_car_field(harness: TraceReplayHarness) -> None:
    """L0-08: reading a car field NOT in ac_schema.json must raise loudly. This is
    the guard that makes a test which drifts onto a hallucinated CSP API FAIL
    instead of silently passing on a field that does not exist in production."""
    car = harness.make_car(speedKmh=100.0)
    reader = harness.lua.eval("function(c) return c.totallyMadeUpField end")
    with pytest.raises(SchemaViolationError, match="SCHEMA-VIOLATION: car.totallyMadeUpField"):
        harness.call_guarding_schema(reader, car)


def test_schema_gate_blocks_unknown_sim_field(harness: TraceReplayHarness) -> None:
    """L0-09: same guard on the sim table."""
    sim = harness.make_sim(gameTime=1.0)
    reader = harness.lua.eval("function(s) return s.notARealSimField end")
    with pytest.raises(SchemaViolationError, match="SCHEMA-VIOLATION: sim.notARealSimField"):
        harness.call_guarding_schema(reader, sim)


def test_schema_gate_blocks_unknown_vec3_subfield(harness: TraceReplayHarness) -> None:
    """L0-10: vec3 sub-fields are gated too (car.position.w is not x/y/z)."""
    car = harness.make_car(position={"x": 1.0, "y": 2.0, "z": 3.0}, speedKmh=100.0)
    reader = harness.lua.eval("function(c) return c.position.w end")
    with pytest.raises(SchemaViolationError, match="SCHEMA-VIOLATION: car.position.w"):
        harness.call_guarding_schema(reader, car)


def test_schema_gate_allows_declared_fields(harness: TraceReplayHarness) -> None:
    """L0-11: declared fields read back; an unset-but-declared field returns nil so
    the modules' ``car.x or 0`` pattern keeps working (the gate must not over-block)."""
    car = harness.make_car(speedKmh=123.0, position={"x": 4.0, "y": 5.0, "z": 6.0})
    assert harness.lua.eval("function(c) return c.speedKmh end")(car) == pytest.approx(123.0)
    assert harness.lua.eval("function(c) return c.position.y end")(car) == pytest.approx(5.0)
    # brake is declared but unset on this car => nil, NOT a schema violation.
    assert harness.lua.eval("function(c) return c.brake end")(car) is None


# ---------------------------------------------------------------------------
# Harness / schema metadata sanity
# ---------------------------------------------------------------------------


def test_schema_marks_itself_a_bootstrap() -> None:
    """L0-12: ac_schema.json must declare itself a code-derived bootstrap pending an
    on-box dump_schema.lua refresh (so nobody mistakes it for the full CSP API)."""
    schema = load_schema()
    assert "bootstrap" in schema.note.lower(), "schema _note must say it is a bootstrap"
    assert "dump_schema.lua" in schema.note, "schema _note must point at dump_schema.lua"
    # The fields the modules actually read must be present.
    assert {"speedKmh", "brake", "splinePosition", "position", "look"} <= schema.car_fields
    assert {"isInMainMenu", "gameTime"} <= schema.sim_fields


def test_synthesize_trace_scenarios_have_expected_shape(harness: TraceReplayHarness) -> None:
    """L0-13: both scenarios emit frames with the full column set the modules read."""
    assert set(available_scenarios()) == {"clean_lap", "brake_too_late"}
    expected_cols = {
        "spline",
        "speed",
        "eMs",
        "throttle",
        "brake",
        "steer",
        "gear",
        "px",
        "py",
        "pz",
    }
    for scenario in available_scenarios():
        frames = synthesize_trace(scenario)
        assert len(frames) > 0
        assert set(frames[0].keys()) == expected_cols, (
            f"{scenario} frame columns drifted: {set(frames[0].keys()) ^ expected_cols}"
        )


def test_synthesize_trace_rejects_unknown_scenario() -> None:
    """L0-14: an unknown scenario name fails fast with a helpful message."""
    with pytest.raises(ValueError, match="unknown scenario"):
        synthesize_trace("does_not_exist")


# ---------------------------------------------------------------------------
# Harness Lua-interop helpers (to_lua_trace, vec3 coercion variants)
# ---------------------------------------------------------------------------


def test_to_lua_trace_builds_indexed_array(harness: TraceReplayHarness) -> None:
    """L0-15: to_lua_trace converts a Python frame list into a 1-indexed Lua array
    whose rows carry every column, so it can feed corner_analysis/delta directly."""
    frames = synthesize_trace("brake_too_late")
    arr = harness.to_lua_trace(frames)
    n = harness.lua.eval("function(tr) return #tr end")(arr)
    assert n == len(frames), f"Lua array length must match frame count, got {n} vs {len(frames)}"
    # Row 1 must be readable and carry the spline/speed columns.
    first_spline = harness.lua.eval("function(tr) return tr[1].spline end")(arr)
    assert first_spline == pytest.approx(frames[0]["spline"])
    # A converted trace flows through the real corner pipeline.
    ca = harness.require("corner_analysis")
    brakes = harness.lua.execute(
        f'return {{ {{ spline = {BRAKE_SPLINE}, entrySpeed = 95, label = "T1" }} }}'
    )
    segs = ca.buildSegments(arr, brakes)
    assert harness.lua.eval("function(s) return #s end")(segs) >= 2


def test_make_car_accepts_vec3_as_tuple(harness: TraceReplayHarness) -> None:
    """L0-16: vec3 fields may be passed as an (x, y, z) tuple/list, not only a dict.
    Both coercion paths must produce a gated, readable vec3."""
    car = harness.make_car(speedKmh=80.0, position=(7.0, 8.0, 9.0))
    assert harness.lua.eval("function(c) return c.position.x end")(car) == pytest.approx(7.0)
    assert harness.lua.eval("function(c) return c.position.z end")(car) == pytest.approx(9.0)
    # Still gated on sub-fields.
    with pytest.raises(SchemaViolationError, match="SCHEMA-VIOLATION: car.position"):
        harness.call_guarding_schema(
            harness.lua.eval("function(c) return c.position.bogus end"), car
        )


def test_make_car_vec3_scalar_passthrough(harness: TraceReplayHarness) -> None:
    """L0-17: a non-dict/non-sequence vec3 value (e.g. an already-built Lua vec3 or a
    scalar) is passed through unchanged -- the harness must not try to coerce it."""
    lua_vec = harness.lua.eval("function() return { x = 1.0, y = 2.0, z = 3.0 } end")()
    car = harness.make_car(speedKmh=50.0, look=lua_vec)
    # look is the same passthrough table; reading x works (ungated passthrough).
    assert harness.lua.eval("function(c) return c.look.x end")(car) == pytest.approx(1.0)
