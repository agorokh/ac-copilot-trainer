"""Synthetic regression cases; these are NOT the #955 replay accuracy corpus."""

from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.ac_harness.trace_replay import TraceReplayHarness
from tools.ai_sidecar.coaching_diagnosis import RootError
from tools.ai_sidecar.coaching_ledger import CornerState, Status
from tools.ai_sidecar.coaching_runtime import build_coach_runtime
from tools.ai_sidecar.traffic_eligibility import (
    archive_traffic_eligibility,
    traffic_eligibility,
)
from tools.lap_qualification import qualify_archive


def context(*, at=1.0, gap=20.0, distance=20.0, height=0.0, count=2):
    cars = [
        {
            "index": 0,
            "spline": 0.4,
            "speed_kmh": 180.0,
            "position": [0.0, 0.0, 0.0],
            "is_connected": True,
            "is_in_pitlane": False,
        }
    ]
    for index in range(1, count):
        cars.append(
            {
                "index": index,
                "spline": (0.4 + gap / 5000) % 1.0,
                "speed_kmh": 150.0,
                "position": [distance, height, 0.0],
                "is_connected": True,
                "is_in_pitlane": False,
            }
        )
    return {
        "schema_version": 1,
        "sampled_at_s": at,
        "cars_count": count,
        "track_length_m": 5000.0,
        "cars": cars,
    }


def test_occupied_clear_and_count_alone():
    assert traffic_eligibility(context(), now_s=1.0).status == "constrained"
    assert traffic_eligibility(context(gap=600, distance=600), now_s=1.0).eligible
    assert traffic_eligibility(context(count=1), now_s=1.0).eligible
    assert traffic_eligibility({"cars_count": 20}, now_s=1.0).status == "unknown"


@pytest.mark.parametrize("flag", ["is_in_pitlane", "is_connected"])
def test_pit_and_disconnected_controls(flag):
    observed = context()
    observed["cars"][1][flag] = flag == "is_in_pitlane"
    assert traffic_eligibility(observed, now_s=1.0).eligible


@pytest.mark.parametrize("gap,distance,height", [(20, 300, 0), (900, 5, 0), (5, 5, 10)])
def test_adjacent_segments_require_both_spline_and_3d(gap, distance, height):
    assert traffic_eligibility(
        context(gap=gap, distance=distance, height=height), now_s=1.0
    ).eligible


@pytest.mark.parametrize("case_id", ["A011", "A012"])
def test_original_elevation_misses_are_constrained(case_id):
    # The failed experiment stays immutable; these are now regression inputs,
    # never members of the fresh held-out evaluation.
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/traffic_shadow_955/frozen_45.json").read_text()
    )
    case = next(c for c in fixture["approaches"] if c["id"] == case_id)
    row = case["row"]
    assert traffic_eligibility(row["traffic"], now_s=row["traffic_now_s"]).status == "constrained"


@pytest.mark.parametrize("height", [6.0, 15.0, 25.0])
def test_same_road_elevation_scales_with_along_track_distance(height):
    assert (
        traffic_eligibility(context(gap=80, distance=80, height=height), now_s=1.0).status
        == "constrained"
    )


def test_finish_wrap_is_occupied_but_car_behind_is_clear():
    observed = context(distance=10)
    observed["cars"][0]["spline"] = 0.999
    observed["cars"][1]["spline"] = 0.001
    assert traffic_eligibility(observed, now_s=1.0).status == "constrained"
    assert traffic_eligibility(context(gap=-100, distance=100), now_s=1.0).eligible


@pytest.mark.parametrize("now", [1.251, 0.99, None, True, float("nan"), float("inf")])
def test_stale_future_or_unrelated_clock_is_unknown(now):
    assert traffic_eligibility(context(), now_s=now).status == "unknown"
    assert traffic_eligibility(context(), now_s=1.250).status == "constrained"


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), -1.0])
@pytest.mark.parametrize("key", ["spline", "speed_kmh"])
def test_bad_scalar_is_unknown_even_on_an_ignored_pit_car(key, value):
    observed = context()
    observed["cars"][1]["is_in_pitlane"] = True
    observed["cars"][1][key] = value
    assert traffic_eligibility(observed, now_s=1.0).status == "unknown"


@pytest.mark.parametrize("key", ["index", "position", "is_connected", "is_in_pitlane"])
def test_missing_fields_fail_closed(key):
    observed = context()
    observed["cars"][1].pop(key)
    assert traffic_eligibility(observed, now_s=1.0).status == "unknown"


@pytest.mark.parametrize("index", [-1, 0, 2, True, 1.5])
def test_invalid_or_duplicate_index(index):
    observed = context()
    observed["cars"][1]["index"] = index
    assert traffic_eligibility(observed, now_s=1.0).status == "unknown"


def test_full_roster_is_required_before_any_eligible_or_constrained_verdict():
    observed = context(count=3)
    observed["cars"].pop()
    assert traffic_eligibility(observed, now_s=1.0).status == "unknown"
    observed = context(count=3)
    observed["cars"][2]["position"][1] = float("inf")
    assert traffic_eligibility(observed, now_s=1.0).status == "unknown"
    for count in (-1, 0, True, 2.5, 129):
        observed["cars_count"] = count
        assert traffic_eligibility(observed, now_s=1.0).status == "unknown"


def _capture(*, constrained=False):
    frames = [context(at=index / 10, gap=600, distance=600) for index in range(11)]
    if constrained:
        frames[3] = context(at=0.3)
    return {
        "schema_version": 1,
        "complete": True,
        "started_at_s": 0.0,
        "ended_at_s": 1.0,
        "frames": frames,
    }


@pytest.mark.parametrize(
    "use", ["human_progression", "live_reference", "reference_comparison", "plant_fit"]
)
@pytest.mark.parametrize("kind", ["constrained", "unknown"])
def test_archive_quarantine_precedes_legacy_policy_and_preserves_analysis(use, kind):
    record = {
        "schema_version": 1,
        "source": "in_game",
        "lap": {"lap_ms": 1000},
        "traffic": _capture(constrained=kind == "constrained"),
    }
    if kind == "unknown":
        record["traffic"]["complete"] = False
    before = copy.deepcopy(record)
    denied = qualify_archive(record, use=use)
    assert denied.managed and not denied.allowed
    assert qualify_archive(record, use="analysis").allowed
    assert record == before


def test_clean_archive_retains_legacy_provenance_verdict_not_human_certification():
    record = {"lap": {"lap_ms": 1000}, "traffic": _capture()}
    for use in ("human_progression", "live_reference", "plant_fit"):
        verdict = qualify_archive(record, use=use)
        assert verdict.allowed and verdict.authority == "legacy_unknown"
    assert archive_traffic_eligibility({}) is None


def test_managed_consumers_respect_traffic_denial_without_attribution(monkeypatch):
    from tools.ai_sidecar import protocol
    from tools.session_review.report import _reference_kind

    record = {
        "source": "in_game",
        "lap": {"lap_ms": 1000},
        "traffic": _capture(constrained=True),
        "trace": {"samples": [[0, 100], [1, 100]], "fields": ["spline", "speed"]},
    }
    assert _reference_kind(record) != "your-best"
    monkeypatch.setattr(protocol, "resolve_lap_archive", lambda _: record)
    assert protocol.build_brain_followup(record) is None


def _traffic_tick(observed):
    from tools.ai_sidecar.external_protocol import make_telemetry_tick

    return make_telemetry_tick(
        {
            "speed_kmh": 120,
            "rpm": 6000,
            "throttle": 0.5,
            "brake": 0,
            "steer": 0,
            "gear": 3,
            "lat_g": 0,
            "long_g": 0,
            "traffic": observed,
            "traffic_now_s": 1.0,
            "setup_reset_allowed": False,
        }
    )


def test_traffic_wire_accepts_bounded_rosters_and_sampling_failure():
    from tools.ai_sidecar.external_protocol import validate_inbound

    assert validate_inbound(_traffic_tick(context(count=128))) is None
    failed = {"schema_version": 1, "cars": [], "error": "traffic_clock_invalid"}
    assert validate_inbound(_traffic_tick(failed)) is None
    pit = context()
    pit["cars"][0]["is_in_pitlane"] = True
    assert validate_inbound(_traffic_tick(pit)) is None


@pytest.mark.parametrize("kind", ["oversize", "nested", "missing", "index", "clock", "error"])
def test_traffic_wire_rejects_unbounded_or_malformed_payloads(kind):
    from tools.ai_sidecar.external_protocol import validate_inbound

    frame = _traffic_tick(context())
    observed = frame["payload"]["traffic"]
    if kind == "oversize":
        observed["cars"] = observed["cars"] * 65
    elif kind == "nested":
        observed["cars"][0]["extra"] = {"unbounded": "x" * 20000}
    elif kind == "missing":
        observed["cars"][0].pop("position")
    elif kind == "index":
        observed["cars"][1]["index"] = True
    elif kind == "clock":
        frame["payload"]["traffic_now_s"] = float("nan")
    else:
        observed["error"] = "x" * 129
    assert validate_inbound(frame) is not None


def test_raw_traffic_only_reaches_observers_and_preserves_peripheral_status(monkeypatch):
    from tools.ai_sidecar import server

    class Peer:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(json.loads(payload))

    classes = ("screen", "haptics", "physical", "browser", "observer")
    peers = {kind: Peer() for kind in classes}
    monkeypatch.setattr(server, "_external_peer_classes", {p: kind for kind, p in peers.items()})
    frame = _traffic_tick(context(count=128))
    original = copy.deepcopy(frame)
    asyncio.run(server._broadcast_targets(frame, targets=list(peers.values())))
    for kind, peer in peers.items():
        received = peer.sent[0]["payload"]
        assert received["setup_reset_allowed"] is False
        assert ("traffic" in received) == (kind == "observer")
        assert ("traffic_now_s" in received) == (kind == "observer")
        if kind != "observer":
            assert len(json.dumps(peer.sent[0])) < 1024
    assert frame == original


def test_raw_capture_is_recomputed_and_missing_coverage_cannot_be_promoted():
    record = {"lap": {"lap_ms": 1000}, "traffic": _capture(constrained=True)}
    record["traffic"]["status"] = "eligible"
    assert archive_traffic_eligibility(record).status == "constrained"
    record["traffic"]["frames"] = record["traffic"]["frames"][4:]
    assert archive_traffic_eligibility(record).status == "unknown"
    record["traffic"] = _capture()
    record["traffic"]["frames"][3] = record["traffic"]["frames"][2]
    assert archive_traffic_eligibility(record).status == "unknown"


@pytest.mark.parametrize("lap_ms", [500, 1500, 10000])
def test_archive_coverage_keeps_observation_and_simulation_clocks_separate(lap_ms):
    record = {"lap": {"lap_ms": lap_ms}, "traffic": _capture()}
    assert archive_traffic_eligibility(record).status == "eligible"
    assert qualify_archive(record, use="human_progression").allowed
    # Removing cross-clock equality does not permit missing observation coverage.
    record["traffic"]["frames"] = record["traffic"]["frames"][4:]
    assert archive_traffic_eligibility(record).status == "unknown"
    record["traffic"] = _capture()
    record["traffic"]["complete"] = False
    assert archive_traffic_eligibility(record).status == "unknown"


def _py(table):
    if not hasattr(table, "items"):
        return table
    keys = list(table.keys())
    if keys and all(type(key) is int for key in keys):
        return [_py(table[i]) for i in range(1, len(keys) + 1)]
    return {key: _py(value) for key, value in table.items()}


def _lua_cars(harness):
    return [
        harness.make_car(
            index=i,
            splinePosition=0.4 + i * 0.004,
            speedKmh=180,
            position=(i * 20, 0, 0),
            isConnected=True,
            isInPitlane=False,
        )
        for i in range(20)
    ]


@pytest.mark.parametrize("hz", [10, 20])
def test_sampler_keeps_nominal_rate_across_render_jitter_without_catchup(hz):
    harness = TraceReplayHarness()
    result = harness.lua.eval("""function(hz)
      local sampler = require('traffic_context').new(hz)
      local sim = {carsCount=1,trackLengthM=5000}
      local car = {index=0,position={x=0,y=0,z=0},splinePosition=.4,
        speedKmh=180,isConnected=true,isInPitlane=false}
      local function getCar(i) assert(i==0);return car end
      local n,previous = 0,nil
      for frame=0,3419 do
        local now=frame/57+(frame%3)*.001
        local snapshot,due=sampler:update(now,sim,getCar)
        if due then
          assert(snapshot.sampled_at_s==now)
          assert(previous==nil or now>previous)
          n,previous=n+1,now
        end
      end
      local before=#sampler.frames
      local _,due=sampler:update(65,sim,getCar)
      assert(due and #sampler.frames==before+1)
      local _,again=sampler:update(65.001,sim,getCar)
      assert(not again, 'a hitch must not create a catch-up burst')
      sampler:reset()
      assert(sampler.next_at==nil)
      return {count=n}
    end""")(hz)
    assert abs(result["count"] - hz * 60) <= 1


@pytest.mark.parametrize("lua_runtime", ["default", "luajit21"])
def test_real_lua_module_schema_and_rate_limit_without_wheel_reads(lua_runtime):
    if lua_runtime == "luajit21":
        # LuaJIT's caught Windows SEH exceptions confuse pytest's in-process
        # faulthandler. Run the identical assertions in an isolated interpreter;
        # an actual crash still fails this test through its return code.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import runpy,sys; "
                "runpy.run_path(sys.argv[1])['_exercise_traffic_sampler']('luajit21')",
                str(Path(__file__).resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        _exercise_traffic_sampler(lua_runtime)


def _exercise_traffic_sampler(lua_runtime):
    harness = TraceReplayHarness(lua_runtime=lua_runtime)
    module = harness.require("traffic_context")
    cars = _lua_cars(harness)
    sim = harness.make_sim(carsCount=20, trackLengthM=5000)
    # A wheel getter increments a counter even if a consumer swallows its exception.
    harness.lua.execute("wheelReads = 0")
    trap = harness.lua.eval(
        "function(car) return setmetatable({}, {__index=function(_, k) "
        "if k == 'wheels' then wheelReads=wheelReads+1; error('no wheels') end; "
        "return car[k] end}) end"
    )
    cars = [trap(car) for car in cars]
    roster = harness.lua.table_from(dict(enumerate(cars)))
    get_car = harness.lua.eval("function(cars) return function(i) return cars[i] end end")(roster)
    sampler = module.new(20)
    # Lua helpers unpack multi-returns independently of lupa's runtime setting.
    update = harness.lua.eval(
        "function(s,t,sim,getCar) local snap,due=s:update(t,sim,getCar); "
        "return {snapshot=snap,due=due} end"
    )
    assert update(sampler, 1.0, sim, get_car)["due"]
    assert not update(sampler, 1.01, sim, get_car)["due"]
    assert update(sampler, 1.05, sim, get_car)["due"]
    observed = _py(sampler.snapshot)
    assert len(observed["cars"]) == 20
    assert traffic_eligibility(observed, now_s=1.05).status == "constrained"
    assert harness.lua.globals().wheelReads == 0
    assert "wheels" not in json.dumps(observed)
    first_lap = _py(sampler.finishLap(sampler, 1.1))
    assert not first_lap["complete"]
    assert sampler.complete
    sampler.reset(sampler)
    assert not sampler.complete and len(sampler.frames) == 0


def test_lua_bad_index_and_nonfinite_cstruct_values_are_unknown():
    harness = TraceReplayHarness()
    module = harness.require("traffic_context")
    sim = harness.make_sim(carsCount=2, trackLengthM=5000)
    cars = _lua_cars(harness)
    cars[1]["index"] = 0
    observed = _py(module.sample(sim, lambda i: cars[i], 1.0))
    assert observed["error"] == "traffic_car_index_invalid"
    assert traffic_eligibility(observed, now_s=1.0).status == "unknown"
    cars[1]["index"] = 1
    cars[1]["speedKmh"] = float("nan")
    observed = _py(module.sample(sim, lambda i: cars[i], 1.0))
    assert observed["error"] == "traffic_car_fields_invalid"


@pytest.mark.parametrize("traffic_kind", ["constrained", "unknown", "clear"])
def test_replay_gate_silences_prime_but_shadow_keeps_existing_cues(traffic_kind):
    archive = json.loads(
        (Path(__file__).parent / "fixtures/magione_gt3r_reference.json").read_text()
    )
    trace = archive["trace"]
    fields = {name: i for i, name in enumerate(trace["fields"])}
    for mode in ("shadow", "replay"):
        runtime = build_coach_runtime(archive, traffic_gate_mode=mode, use_environment=False)
        ref = runtime.refs[0]
        root = RootError.EARLY_BRAKE
        runtime.ledger.begin_lap(3)
        runtime.ledger._states[ref.index] = CornerState(
            corner=ref.index,
            status=Status.ARMED,
            root=root,
            register="urgent",
            intensity=0.5,
        )
        runtime.ledger._speak_set = {ref.index}
        anchor = runtime.anchors[ref.index].for_root(root)
        speed = trace["samples"][0][fields["speed"]]
        traffic = context(gap=600, distance=600) if traffic_kind == "clear" else context()
        now = 2.0 if traffic_kind == "unknown" else 1.0
        observed = []
        for spline in (anchor - 0.001, anchor + 0.001):
            observed.extend(
                runtime.observe(
                    {
                        "spline": spline,
                        "speed": speed,
                        "brake": 0,
                        "throttle": 1,
                        "steer": 0,
                        "lap": 3,
                        "traffic": traffic,
                        "traffic_now_s": now,
                    }
                )
            )
        primes = [a for a in observed if a.detail.get("coach") == "prime"]
        assert bool(primes) == (mode == "shadow" or traffic_kind == "clear")
        expected = "eligible" if traffic_kind == "clear" else traffic_kind
        assert runtime.last_traffic_eligibility.status == expected


@pytest.mark.parametrize("traffic_kind", ["constrained", "unknown"])
def test_contamination_survives_clear_exit_and_resets_for_next_corner_pass(traffic_kind):
    archive = json.loads(
        (Path(__file__).parent / "fixtures/magione_gt3r_reference.json").read_text()
    )
    runtime = build_coach_runtime(archive, traffic_gate_mode="replay", use_environment=False)
    runtime.ledger.assess_laps = 0
    ref = next(r for r in runtime.refs if runtime.anchors[r.index].brake > 0.05)
    state = CornerState(corner=ref.index, status=Status.PRIMED, root=RootError.EARLY_BRAKE)
    state.consecutive = 2
    runtime.ledger._states[ref.index] = state
    runtime.ledger.begin_lap(3)
    fields = {name: i for i, name in enumerate(archive["trace"]["fields"])}
    frames = [
        {name: row[fields[name]] for name in ("spline", "speed", "brake", "throttle", "steer")}
        for row in archive["trace"]["samples"]
    ]
    contaminated = False
    for frame in frames:
        traffic, now = context(gap=600, distance=600), 1.0
        if not contaminated and ref.spline_lo <= frame["spline"] <= ref.apex_spline:
            traffic = context()
            now = 2.0 if traffic_kind == "unknown" else 1.0
            contaminated = True
        runtime.observe({**frame, "lap": 3, "traffic": traffic, "traffic_now_s": now})
    assert contaminated
    assert runtime.last_pass_capability[ref.index]["traffic_reason"]
    assert state.clean_streak == 0
    assert state.root is RootError.EARLY_BRAKE
    assert state.status is Status.PRIMED
    for frame in frames:
        runtime.observe(
            {**frame, "lap": 4, "traffic": context(gap=600, distance=600), "traffic_now_s": 1.0}
        )
    assert runtime.last_pass_capability[ref.index]["traffic_reason"] == ""


def test_entry_script_and_module_compile_with_declared_harness_runtimes():
    # The whole entry uses the established Lua 5.5 harness: stock LuaJIT rejects
    # both pinned base bc1c935 and entry at its 60-upvalue limit. This does not
    # certify the CSP host. The new standalone collector also runs under LuaJIT.
    harness = TraceReplayHarness()
    source = (
        Path(__file__).parents[1] / "src/ac_copilot_trainer/ac_copilot_trainer.lua"
    ).read_text(encoding="utf-8")
    result = harness.lua.eval("function(s) local f,e=load(s); return e or 'ok' end")(source)
    assert result == "ok"
    assert TraceReplayHarness(lua_runtime="luajit21").require("traffic_context") is not None
