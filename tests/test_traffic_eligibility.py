"""Synthetic regression cases; these are NOT the #955 replay accuracy corpus."""

from __future__ import annotations

import copy
import json
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


@pytest.mark.parametrize("use", ["human_progression", "live_reference", "plant_fit"])
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
    assert not qualify_archive(record, use=use).allowed
    assert qualify_archive(record, use="analysis").allowed
    assert record == before


def test_clean_archive_retains_legacy_provenance_verdict_not_human_certification():
    record = {"lap": {"lap_ms": 1000}, "traffic": _capture()}
    for use in ("human_progression", "live_reference", "plant_fit"):
        verdict = qualify_archive(record, use=use)
        assert verdict.allowed and verdict.authority == "legacy_unknown"
    assert archive_traffic_eligibility({}) is None


def test_raw_capture_is_recomputed_and_missing_coverage_cannot_be_promoted():
    record = {"lap": {"lap_ms": 1000}, "traffic": _capture(constrained=True)}
    record["traffic"]["status"] = "eligible"
    assert archive_traffic_eligibility(record).status == "constrained"
    record["traffic"]["frames"] = record["traffic"]["frames"][4:]
    assert archive_traffic_eligibility(record).status == "unknown"
    record["traffic"] = _capture()
    record["traffic"]["frames"][3] = record["traffic"]["frames"][2]
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


def test_real_lua_module_schema_and_rate_limit_without_wheel_reads():
    harness = TraceReplayHarness()
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
    sampler = module.new(20)
    # Lua helpers unpack multi-returns independently of lupa's runtime setting.
    update = harness.lua.eval(
        "function(s,t,sim,getCar) local snap,due=s:update(t,sim,getCar); "
        "return {snapshot=snap,due=due} end"
    )
    assert update(sampler, 1.0, sim, lambda i: cars[i])["due"]
    assert not update(sampler, 1.01, sim, lambda i: cars[i])["due"]
    assert update(sampler, 1.05, sim, lambda i: cars[i])["due"]
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


def test_replay_gate_silences_prime_but_shadow_keeps_existing_cues():
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
                        "traffic": context(),
                        "traffic_now_s": 1.0,
                    }
                )
            )
        primes = [a for a in observed if a.detail.get("coach") == "prime"]
        assert bool(primes) == (mode == "shadow")
        assert runtime.last_traffic_eligibility.status == "constrained"
