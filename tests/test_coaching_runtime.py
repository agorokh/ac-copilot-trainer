"""Coach v2 runtime — frame-level mistake-injection over the real Magione reference trace.

The offline counterpart to the on-rig auto_drive injection: replay the reference lap as live
frames across a stint, inject a *known* mistake at a *known* corner, and assert the coach gives the
right anticipatory imperative at the right place — and is silent when the driver is on the
reference. This is the deterministic regression net behind the live drive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sidecar.coaching_diagnosis import RootError
from tools.ai_sidecar.coaching_ledger import CornerState, Status
from tools.ai_sidecar.coaching_runtime import build_coach_runtime

# Prefer the committed fixture (CI); fall back to the rig capture under .scratch (gitignored).
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "magione_gt3r_reference.json"
_RIG = Path(__file__).resolve().parents[1] / ".scratch" / "coach-demo" / "reference.json"
REF_PATH = _FIXTURE if _FIXTURE.exists() else _RIG
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="reference trace fixture missing")


def _ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


def _lap_frames(archive: dict) -> list[dict]:
    tr = archive["trace"]
    fi = {f: i for i, f in enumerate(tr["fields"])}
    out = []
    for row in tr["samples"]:
        out.append(
            {
                "spline": row[fi["spline"]],
                "speed": row[fi["speed"]],
                "brake": row[fi["brake"]],
                "throttle": row[fi["throttle"]],
                "steer": row[fi["steer"]],
            }
        )
    return out


def _inject_early_brake(frames: list[dict], bp_spline: float, *, earlier: float = 0.03) -> None:
    """Make the driver brake EARLY for the corner whose ref brake point is ``bp_spline``: force the
    brake on across [bp - earlier, bp]."""
    for f in frames:
        if bp_spline - earlier <= f["spline"] < bp_spline:
            f["brake"] = 1.0
            f["throttle"] = 0.0


def _drive(runtime, laps: list[list[dict]]) -> list:
    """Replay laps through the runtime (incrementing the lap counter); collect all advisories."""
    advs = []
    for lap_idx, frames in enumerate(laps, start=1):
        for f in frames:
            advs.extend([(lap_idx, a) for a in runtime.observe({**f, "lap": lap_idx})])
    return advs


def _brake_anchor(runtime, corner_idx: int) -> float:
    return runtime.anchors[corner_idx].brake


def test_runtime_builds_from_reference():
    rt = build_coach_runtime(_ref())
    assert rt is not None and rt.refs, "runtime must build corners from the reference"


def test_runtime_policy_ignores_profile_history_for_other_combo():
    profile = {
        "schema_version": 1,
        "driver_id": "driver-a",
        "corner_history": {
            "other-car|other-track||corner:0": {
                "car_id": "other-car",
                "track_id": "other-track",
                "track_layout": "",
                "valid_laps": 8,
                "delta_min_speed_kmh": 3.0,
                "avg_trail_brake_ratio": 0.4,
                "avg_throttle": 0.7,
                "avg_steer_reversals": 1.0,
            }
        },
        "consistency": {
            "other-car|other-track|": {
                "car_id": "other-car",
                "track_id": "other-track",
                "track_layout": "",
                "session_count": 3,
                "valid_laps": 12,
                "median_session_best_ms": 100000,
                "consistency_ms": 1000.0,
            }
        },
    }

    rt = build_coach_runtime(_ref(), driver_profile=profile)

    assert rt is not None
    assert rt.cue_policy.level == "unknown"
    assert rt.ledger.lap_budget == 4


def test_runtime_policy_defaults_when_reference_combo_missing():
    profile = {
        "schema_version": 1,
        "driver_id": "driver-a",
        "corner_history": {
            "other-car|other-track||corner:0": {
                "car_id": "other-car",
                "track_id": "other-track",
                "track_layout": "",
                "valid_laps": 8,
                "delta_min_speed_kmh": 3.0,
                "avg_trail_brake_ratio": 0.4,
                "avg_throttle": 0.7,
                "avg_steer_reversals": 1.0,
            }
        },
        "consistency": {
            "other-car|other-track|": {
                "car_id": "other-car",
                "track_id": "other-track",
                "track_layout": "",
                "session_count": 3,
                "valid_laps": 12,
                "median_session_best_ms": 100000,
                "consistency_ms": 1000.0,
            }
        },
    }
    reference = _ref()
    reference.pop("car", None)
    reference.pop("track", None)

    rt = build_coach_runtime(reference, driver_profile=profile)

    assert rt is not None
    assert rt.cue_policy.level == "unknown"
    assert rt.ledger.lap_budget == 4


def test_perfect_reference_is_silent_after_assess():
    rt = build_coach_runtime(_ref())
    base = _lap_frames(_ref())
    advs = _drive(rt, [list(base) for _ in range(5)])  # 5 clean laps
    assess = rt.ledger.assess_laps
    primes = [a for (lap, a) in advs if a.detail.get("coach") == "prime" and lap > assess]
    got = [a.message for a in primes]
    assert primes == [], f"a driver on the reference should not be coached, got {got}"


def test_injected_early_brake_speaks_brake_later_at_that_corner():
    rt = build_coach_runtime(_ref())
    refs = rt.refs
    # pick a real braking corner (one with a detected reference brake point)
    target = next(r for r in refs if rt.ref_sigs[r.index].brake_point_spline is not None)
    bp = rt.ref_sigs[target.index].brake_point_spline
    laps = []
    for _ in range(4):
        f = _lap_frames(_ref())
        _inject_early_brake(f, bp)
        laps.append(f)
    advs = _drive(rt, laps)
    primes = [
        (lap, a)
        for (lap, a) in advs
        if a.detail.get("coach") == "prime" and a.corner == target.index
    ]
    assert primes, "early braking at a corner must eventually be coached"
    # it must say the right thing, and not until after the assess laps (hysteresis + watch-first)
    lap, a = primes[0]
    assert a.message == "Brake later."
    assert lap > rt.ledger.assess_laps
    # and it must land near that corner's pre-brake anchor (anticipatory, before the brake point)
    assert a.spline <= bp + 1e-6


def test_degenerate_pass_is_gated_invalid():
    """B3: a pass that never reached a real apex (validity sentinel) must NOT arm the ledger —
    the runtime no longer hardcodes valid=True."""
    rt = build_coach_runtime(_ref())
    r = rt.refs[0]
    rt._pass[
        r.index
    ].active = True  # active but no real samples (entry_count=0, min_speed sentinel)
    rt._finalize_pass(r)
    assert rt.ledger.state(r.index) is None  # invalid pass recorded nothing


def test_reset_clears_stint_state():
    """B4: reset() must clear lap/stream/ledger state so a reconnecting producer starts clean
    (else stale RETIRED/lap state suppresses cues until a process restart)."""
    rt = build_coach_runtime(_ref())
    target = next(r for r in rt.refs if rt.ref_sigs[r.index].brake_point_spline is not None)
    bp = rt.ref_sigs[target.index].brake_point_spline
    laps = []
    for _ in range(3):
        f = _lap_frames(_ref())
        _inject_early_brake(f, bp)
        laps.append(f)
    _drive(rt, laps)
    assert rt.ledger.state(target.index) is not None  # state accumulated
    rt.reset()
    assert rt._lap == 1 and rt._last_spline is None
    assert all(rt.ledger.state(r.index) is None for r in rt.refs)  # ledger wiped


def test_injected_then_fixed_acknowledges_and_silences():
    rt = build_coach_runtime(_ref())
    target = next(r for r in rt.refs if rt.ref_sigs[r.index].brake_point_spline is not None)
    bp = rt.ref_sigs[target.index].brake_point_spline
    laps = []
    for lap in range(1, 7):
        f = _lap_frames(_ref())
        if lap <= 3:  # brake early laps 1-3, clean from lap 4
            _inject_early_brake(f, bp)
        laps.append(f)
    advs = _drive(rt, laps)
    confirms = [
        (lap, a)
        for (lap, a) in advs
        if a.detail.get("coach") == "confirm" and a.corner == target.index
    ]
    assert confirms, "fixing a coached mistake should be acknowledged once"
    assert confirms[0][1].message == "Good."


def test_same_lap_rewind_does_not_advance_ledger_lap():
    """Wrap-shaped spline drop with a stable lap counter is a pit/teleport, not a new lap."""
    rt = build_coach_runtime(_ref())
    start_lap = rt._lap
    rt.observe({"spline": 0.92, "speed": 90.0, "brake": 0.5, "lap": 1})
    rt.observe({"spline": 0.03, "speed": 60.0, "brake": 0.0, "lap": 1})
    rt.observe({"spline": 0.40, "speed": 90.0, "brake": 0.0, "lap": 1})
    assert rt._lap == start_lap
    assert rt._pending_wrap_finals is False


def test_late_brake_not_suppressed_at_grip_ceiling():
    """LATE_BRAKE is 'Brake earlier.' — still valid coaching at high grip utilization."""
    rt = build_coach_runtime(_ref())
    r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
    st = rt._pass[r.index]
    st.active = True
    st.entry_count = 5
    st.min_speed_kmh = 70.0
    st.brake_onset_spline = (rt.ref_sigs[r.index].brake_point_spline or 0.25) + 0.02
    st.max_grip_used = 0.99
    rt._finalize_pass(r)
    assert rt.ledger.state(r.index) is not None


def test_pending_wrap_suppresses_prime_on_ambiguous_frame():
    """Qodo #3: wrap-shaped drop with stable lap counter must not PRIME on the ambiguous frame."""
    rt = build_coach_runtime(_ref())
    rt.ledger.assess_laps = 0
    r = rt.refs[0]
    st = rt.ledger._states.setdefault(r.index, CornerState(r.index))
    st.status = Status.ARMED
    st.root = RootError.EARLY_BRAKE
    st.time_lost_s = 5.0
    rt.ledger.begin_lap(1)
    rt.ledger._speak_set = {r.index}
    rt._last_spline = 0.92
    rt._last_lap = 1.0
    advs = rt.observe({"spline": 0.02, "speed": 100.0, "brake": 0.0, "lap": 1})
    assert rt._pending_wrap_finals
    assert not any(a.detail.get("coach") == "prime" for a in advs)


def test_wrap_finalizes_passes_before_begin_lap():
    """Qodo #4: wrap-finalized diagnoses must land before begin_lap() builds the speak-set."""
    rt = build_coach_runtime(_ref())
    rt.ledger.assess_laps = 0
    rt.ledger.hysteresis = 1
    r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
    st = rt._pass[r.index]
    st.active = True
    st.entry_count = 5
    st.min_speed_kmh = 70.0
    st.brake_onset_spline = (rt.ref_sigs[r.index].brake_point_spline or 0.25) + 0.02
    rt._last_spline = 0.92
    rt._last_lap = 1.0
    rt.observe({"spline": 0.02, "speed": 100.0, "brake": 0.0, "lap": 2})
    assert rt._lap == 2
    assert r.index in rt.ledger._speak_set
    assert rt.ledger.state(r.index) is not None
    assert rt.ledger.state(r.index).root is not RootError.NONE


def test_off_pace_reference_suppresses_prime_and_save():
    """#675 Part 4: when the reference is slower than the driver's rolling best, mute cues."""
    from tools.ai_sidecar.lap_dynamics import lap_trace_from_archive

    archive = _ref()
    rt = build_coach_runtime(archive)
    assert rt is not None
    assert rt.reference_lap_ms is not None
    # Driver posts a faster lap than the reference → reference is off-pace.
    rt.note_completed_lap(rt.reference_lap_ms - 1500.0, is_valid=True)
    assert rt._off_pace_reference is True
    assert rt.cue_suppress_reason == "reference_slower_than_rolling_best"

    rt.ledger.assess_laps = 0
    r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
    st = rt.ledger._states.setdefault(r.index, CornerState(r.index))
    st.status = Status.ARMED
    st.root = RootError.EARLY_BRAKE
    st.time_lost_s = 5.0
    rt.ledger.begin_lap(3)
    rt.ledger._speak_set = {r.index}
    fire_at = rt.anchors[r.index].brake
    rt._last_spline = (fire_at - 0.01) % 1.0
    advs = rt.observe({"spline": fire_at + 0.001, "speed": 140.0, "brake": 0.0, "lap": 3})
    assert not any(a.detail.get("coach") == "prime" for a in advs)

    # Calibration still folds (Part 0/3) even under the off-pace gate.
    n = rt.calibrate_from_driver_lap(lap_trace_from_archive(archive), track_id="magione")
    assert n >= 0  # may be 0 if onsets don't match windows; must not raise


def _combo_ggv(mu_lat_g: float, brake_b0_g: float, *, ellipse_n: float = 1.4):
    from tools.ac_harness.ggv_profile import GGVModel

    return GGVModel(
        mu_lat_g=mu_lat_g,
        k_aero_lat=0.0,
        brake_b0_g=brake_b0_g,
        brake_b1=0.0,
        drive_b0_g=0.75,
        drive_b1=0.0,
        drive_min_g=0.25,
        ellipse_n=ellipse_n,
        provenance={"lat_corner_bins": 4, "brake_fit_valid": True},
    )


def test_street_car_saturation_suppressed_while_baseline_falsely_diagnoses():
    """#938: BMW E30 (~1.05g) at 1.02g (97% of capability) suppresses SLOW_APEX/EARLY_BRAKE
    under condition-indexed and GGV denominator modes, while baseline (1.55g) falsely fires."""
    e30_ggv = _combo_ggv(1.05, 1.08)
    archive = _ref()
    archive["car"] = {"id": "ks_bmw_m3_e30", "tyreCompound": "street"}

    for mode, should_suppress in (
        ("baseline", False),
        ("ggv_denominator_only", True),
        ("condition_indexed", True),
    ):
        rt = build_coach_runtime(
            archive,
            use_environment=False,
            ggv_model=e30_ggv,
            capability_gate_mode=mode,
        )
        assert rt is not None
        rt.ledger.assess_laps = 0
        rt.ledger.hysteresis = 1
        r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
        bp = rt.ref_sigs[r.index].brake_point_spline
        frames = _lap_frames(archive)
        _inject_early_brake(frames, bp)
        for f in frames:
            if r.spline_lo <= f["spline"] <= r.spline_hi:
                f["lat_g"] = 1.02
                f["tyre_temps_c"] = {"fl": 80.0, "fr": 80.0, "rl": 78.0, "rr": 78.0}
        _drive(rt, [frames])
        st = rt.ledger.state(r.index)
        if should_suppress:
            assert st is None or st.root is RootError.NONE
        else:
            assert st is not None and st.root is RootError.EARLY_BRAKE


def test_combined_entry_braking_turn_in_saturation_suppresses_early_brake():
    """#938: corner-entry trail-braking saturating the GGV friction ellipse suppresses EARLY_BRAKE
    in condition_indexed mode even when |lat_g| alone is below 0.95 * ay_max(v)."""
    gt3_ggv = _combo_ggv(1.50, 1.65, ellipse_n=1.35)
    archive = _ref()

    for mode, should_suppress in (
        ("baseline", False),
        ("ggv_denominator_only", False),
        ("condition_indexed", True),
    ):
        rt = build_coach_runtime(
            archive,
            use_environment=False,
            ggv_model=gt3_ggv,
            capability_gate_mode=mode,
        )
        assert rt is not None
        rt.ledger.assess_laps = 0
        rt.ledger.hysteresis = 1
        r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
        bp = rt.ref_sigs[r.index].brake_point_spline
        frames = _lap_frames(archive)
        _inject_early_brake(frames, bp)
        for f in frames:
            if (rt.anchors[r.index].brake - 0.04) <= f["spline"] <= r.apex_spline:
                # |lat_g| = 1.05g is only 70% of 1.50g lateral ceiling, but combined with
                # -1.38g braking on a n=1.35 ellipse -> combined entry utilization >= 0.98.
                f["lat_g"] = 1.05
                f["long_g"] = -1.38
                f["tyre_temps_c"] = {"fl": 86.0, "fr": 86.0, "rl": 84.0, "rr": 84.0}
        _drive(rt, [frames])
        st = rt.ledger.state(r.index)
        if should_suppress:
            assert st is None or st.root is RootError.NONE
            assert rt.cue_suppress_reason == "grip_envelope_saturated"
            assert rt.last_pass_capability[r.index]["evidence_quality"] == "full"
            assert rt.last_pass_capability[r.index]["max_entry_grip_used"] >= 0.95
        else:
            assert st is not None and st.root is RootError.EARLY_BRAKE


def test_entry_combined_saturation_does_not_suppress_slow_apex_with_lateral_headroom():
    """#938: corner-entry combined braking+turn-in saturation (entry_util >= 0.95) must only gate
    EARLY_BRAKE and must NOT contaminate SLOW_APEX when apex lateral utilization has headroom."""
    gt3_ggv = _combo_ggv(1.50, 1.65, ellipse_n=1.35)
    archive = _ref()
    rt = build_coach_runtime(
        archive,
        use_environment=False,
        ggv_model=gt3_ggv,
        capability_gate_mode="condition_indexed",
    )
    assert rt is not None
    rt.ledger.assess_laps = 0
    rt.ledger.hysteresis = 1
    r = rt.refs[0]
    frames = _lap_frames(archive)
    for f in frames:
        if (rt.anchors[r.index].brake - 0.04) <= f["spline"] <= r.spline_hi:
            f["tyre_temps_c"] = {"fl": 86.0, "fr": 86.0, "rl": 84.0, "rr": 84.0}
            if abs(f["spline"] - r.apex_spline) <= 0.015:
                f["speed"] = max(20.0, f["speed"] - 25.0)
            if f["spline"] < r.apex_spline - 0.01:
                # Entry combined utilization >= 0.98, but lateral utilization = 1.05 / 1.50 = 0.70.
                f["lat_g"] = 1.05
                f["long_g"] = -1.38
            else:
                # Apex lateral utilization = 0.90 / 1.50 = 0.60 (< 0.95 -> plenty of headroom).
                f["lat_g"] = 0.90
                f["long_g"] = 0.0

    _drive(rt, [frames])
    st = rt.ledger.state(r.index)
    assert rt.last_pass_capability[r.index]["max_entry_grip_used"] >= 0.95
    assert rt.last_pass_capability[r.index]["max_lat_grip_used"] < 0.95
    assert rt.last_pass_capability[r.index]["max_grip_used"] < 0.95
    assert st is not None and st.root is RootError.SLOW_APEX


@pytest.mark.parametrize(
    ("frame_extras", "expected_reason"),
    [
        ({"tyre_temps_c": {"fl": 34.0, "fr": 35.0, "rl": 33.0, "rr": 33.0}}, "tyre_temp_cold"),
        (
            {"tyre_temps_c": {"fl": 106.0, "fr": 105.0, "rl": 92.0, "rr": 91.0}},
            "tyre_temp_overheat",
        ),
        (
            {"tyre_temps_c": {"fl": 122.0, "fr": 121.0, "rl": 96.0, "rr": 95.0}},
            "tyre_temp_critical",
        ),
        (
            {
                "tyre_temps_c": {"fl": 85.0, "fr": 85.0, "rl": 84.0, "rr": 84.0},
                "brake_temps_c": {"fl": 680.0, "fr": 670.0, "rl": 510.0, "rr": 505.0},
            },
            "brake_temp_overheat",
        ),
        (
            {
                "tyre_temps_c": {"fl": 85.0, "fr": 85.0, "rl": 84.0, "rr": 84.0},
                "brake_temps_c": {"fl": 875.0, "fr": 860.0, "rl": 540.0, "rr": 530.0},
            },
            "brake_temp_critical",
        ),
        (
            {
                "tyre_temps_c": {"fl": 82.0, "fr": 82.0, "rl": 80.0, "rr": 80.0},
                "conditions": {"trackGripLevel": 0.78, "weatherType": "rain"},
            },
            "wet_regime",
        ),
    ],
)
def test_thermal_and_condition_gates_suppress_prime_and_pass_diagnosis(
    frame_extras: dict,
    expected_reason: str,
):
    """#938: cold/overheat/critical tyres, hot/critical brakes, and wet regime abstain from both
    armed PRIME advisories and pass-exit demand-increasing diagnoses with a [a-z0-9_]+ code."""
    import re

    rt = build_coach_runtime(_ref(), use_environment=False, ggv_model=_combo_ggv(1.50, 1.65))
    assert rt is not None
    rt.ledger.assess_laps = 0
    rt.ledger.hysteresis = 1
    r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
    bp = rt.ref_sigs[r.index].brake_point_spline

    # Arm EARLY_BRAKE on corner r, then cross the PRIME anchor under the ineligible state.
    cst = rt.ledger._states.setdefault(r.index, CornerState(r.index))
    cst.status = Status.ARMED
    cst.root = RootError.EARLY_BRAKE
    cst.time_lost_s = 5.0
    rt.ledger.begin_lap(2)
    rt.ledger._speak_set = {r.index}
    fire_at = rt.anchors[r.index].brake
    rt._last_spline = (fire_at - 0.01) % 1.0
    advs = rt.observe(
        {
            "spline": (fire_at + 0.001) % 1.0,
            "speed": 140.0,
            "brake": 0.0,
            "lat_g": 0.4,
            "lap": 2,
            **frame_extras,
        }
    )
    assert not any(a.detail.get("coach") == "prime" for a in advs)
    assert rt.cue_suppress_reason == expected_reason
    assert re.fullmatch(r"[a-z0-9_]+", rt.cue_suppress_reason)

    # Also verify a fresh pass through corner r does not diagnose EARLY_BRAKE under the gate.
    rt2 = build_coach_runtime(_ref(), use_environment=False, ggv_model=_combo_ggv(1.50, 1.65))
    assert rt2 is not None
    rt2.ledger.assess_laps = 0
    rt2.ledger.hysteresis = 1
    frames = _lap_frames(_ref())
    _inject_early_brake(frames, bp)
    for f in frames:
        f["lat_g"] = 0.70
        f.update(frame_extras)
    _drive(rt2, [frames])
    st2 = rt2.ledger.state(r.index)
    assert st2 is None or st2.root is RootError.NONE
    assert rt2.cue_suppress_reason == expected_reason
    assert re.fullmatch(r"[a-z0-9_]+", rt2.cue_suppress_reason)


def test_bool_nan_inf_and_missing_telemetry_pitfalls():
    """#938 Known pitfalls:
    1. Reject bool (isinstance(True, int)) and NaN/±inf on lat_g, long_g, tyre/brake temps.
    2. Distinguish missing capability evidence from measured in-window headroom without fabricating
       saturation."""
    rt = build_coach_runtime(_ref(), use_environment=False, ggv_model=_combo_ggv(1.05, 1.08))
    assert rt is not None
    rt.ledger.assess_laps = 0
    rt.ledger.hysteresis = 1
    r = next(ref for ref in rt.refs if rt.ref_sigs[ref.index].brake_point_spline is not None)
    bp = rt.ref_sigs[r.index].brake_point_spline

    # Pass 1: frames carry bool/NaN/±inf on every capability channel -> treated as missing, not 1.0g
    # or cold 0°C/1°C, so the injected early-brake mistake is still diagnosed and evidence_quality
    # is explicitly recorded as 'missing'.
    frames = _lap_frames(_ref())
    _inject_early_brake(frames, bp)
    for f in frames:
        f["lat_g"] = True
        f["long_g"] = float("-inf")
        f["grip"] = False
        f["tyre_temps_c"] = {"fl": True, "fr": float("nan"), "rl": float("inf"), "rr": False}
        f["brake_temps_c"] = {"fl": False, "fr": float("-inf"), "rl": float("nan"), "rr": True}
        f["conditions"] = {"trackGripLevel": True, "weatherType": False}
    _drive(rt, [frames])
    st = rt.ledger.state(r.index)
    assert st is not None and st.root is RootError.EARLY_BRAKE
    assert rt.last_pass_capability[r.index]["evidence_quality"] == "missing"
    assert rt.last_pass_capability[r.index]["max_grip_used"] == 0.0


def test_discriminating_8_lap_replay_condition_indexed_vs_baseline_and_denominator_only():
    """#938 Discriminating test (bounded 2 sessions / 8 recorded laps across BMW E30 ~1.05g and
    McLaren MP4-12C GT3 ~1.50g):
    Replay 8 laps through:
      (a) baseline CoachRuntime (_GRIP_CEILING_G = 1.55),
      (b) mundane denominator-only substitute (GGVModel.ay_max(v) without thermal/condition or
          entry combined braking/turn-in gating), and
      (c) the condition-indexed capability & thermal gate.
    Pass condition:
      - >= 80% of baseline demand-increasing cues (EARLY_BRAKE, SLOW_APEX) on pre-labeled
        saturation / cold-tyre / overheat / wet passes are suppressed (including PRIME suppression),
      - >= 70% of safe, actionable under-limit opportunities on in-window laps remain admitted.
    """
    base_archive = _ref()
    e30_ggv = _combo_ggv(1.05, 1.08, ellipse_n=1.35)
    gt3_ggv = _combo_ggv(1.50, 1.65, ellipse_n=1.35)

    def _build_tagged_lap(
        *,
        apex_lat_g: float,
        entry_lat_g: float,
        entry_long_g: float,
        tyre_temp_c: float,
        brake_temp_c: float = 380.0,
        compound: str = "slick",
        track_grip: float = 0.98,
        weather: str = "clear",
        slow_apex_delta_kmh: float = 12.0,
    ) -> list[dict]:
        frames = _lap_frames(base_archive)
        ref_rt = build_coach_runtime(base_archive, use_environment=False)
        assert ref_rt is not None
        for r in ref_rt.refs:
            sig = ref_rt.ref_sigs.get(r.index)
            if sig is None:
                continue
            if sig.brake_point_spline is not None:
                _inject_early_brake(frames, sig.brake_point_spline)
            for f in frames:
                if (ref_rt.anchors[r.index].brake - 0.04) <= f["spline"] <= r.spline_hi:
                    if abs(f["spline"] - r.apex_spline) <= 0.015:
                        f["speed"] = max(30.0, f["speed"] - slow_apex_delta_kmh)
                    if f["spline"] <= r.apex_spline:
                        f["lat_g"] = entry_lat_g
                        f["long_g"] = entry_long_g
                    else:
                        f["lat_g"] = apex_lat_g
                        f["long_g"] = 0.15
        for f in frames:
            f.setdefault("lat_g", 0.15)
            f.setdefault("long_g", 0.0)
            f["tyre_temps_c"] = {
                "fl": tyre_temp_c,
                "fr": tyre_temp_c,
                "rl": tyre_temp_c - 1.5,
                "rr": tyre_temp_c - 1.5,
            }
            f["brake_temps_c"] = {
                "fl": brake_temp_c,
                "fr": brake_temp_c,
                "rl": brake_temp_c - 40.0,
                "rr": brake_temp_c - 40.0,
            }
            f["tyre_compound"] = compound
            f["conditions"] = {
                "trackGripLevel": track_grip,
                "weatherType": weather,
                "tyreCompound": compound,
            }
        return frames

    # 8 recorded laps across 2 sessions (Session 1: BMW E30 ~1.05g; Session 2: MP4-12C GT3 ~1.50g)
    # Each tuple: (session_name, ggv, compound, label, frames)
    # label in {"unsupported_out_of_window", "unsupported_saturated", "valid_in_window"}
    eight_laps = [
        # Session 1 — BMW M3 E30 (~1.05g, street compound window 65-95°C)
        (
            "e30",
            e30_ggv,
            "street",
            "unsupported_out_of_window",  # Lap 1: Cold out-lap (33°C < 40°C cold threshold)
            _build_tagged_lap(
                apex_lat_g=0.74,
                entry_lat_g=0.55,
                entry_long_g=-0.65,
                tyre_temp_c=33.0,
                compound="street",
            ),
        ),
        (
            "e30",
            e30_ggv,
            "street",
            # Lap 2: Warmed in-window lap (78°C) with genuine under-driving (~0.70g)
            "valid_in_window",
            _build_tagged_lap(
                apex_lat_g=0.72,
                entry_lat_g=0.50,
                entry_long_g=-0.55,
                tyre_temp_c=78.0,
                compound="street",
            ),
        ),
        (
            "e30",
            e30_ggv,
            "street",
            # Lap 3: Warmed E30 at lateral/combined entry limit (~1.02g / combined >= 0.96)
            "unsupported_saturated",
            _build_tagged_lap(
                apex_lat_g=1.02,
                entry_lat_g=0.74,
                entry_long_g=-0.86,
                tyre_temp_c=82.0,
                compound="street",
            ),
        ),
        (
            "e30",
            e30_ggv,
            "street",
            # Lap 4: Overheated street tyres (101°C) + hot brakes (690°C)
            "unsupported_out_of_window",
            _build_tagged_lap(
                apex_lat_g=0.78,
                entry_lat_g=0.58,
                entry_long_g=-0.65,
                tyre_temp_c=101.0,
                brake_temp_c=690.0,
                compound="street",
            ),
        ),
        # Session 2 — McLaren MP4-12C GT3 (~1.50g, slick compound window 75-100°C)
        (
            "gt3",
            gt3_ggv,
            "slick",
            "unsupported_out_of_window",  # Lap 5: Cold slick out-lap (36°C)
            _build_tagged_lap(
                apex_lat_g=0.98,
                entry_lat_g=0.75,
                entry_long_g=-0.90,
                tyre_temp_c=36.0,
                compound="slick",
            ),
        ),
        (
            "gt3",
            gt3_ggv,
            "slick",
            # Lap 6: Warmed slick in-window (86°C) with genuine under-limit headroom (~1.02g)
            "valid_in_window",
            _build_tagged_lap(
                apex_lat_g=1.02,
                entry_lat_g=0.72,
                entry_long_g=-0.80,
                tyre_temp_c=86.0,
                compound="slick",
            ),
        ),
        (
            "gt3",
            gt3_ggv,
            "slick",
            # Lap 7: Warmed slick with combined entry braking+turn-in saturation
            "unsupported_saturated",
            _build_tagged_lap(
                apex_lat_g=1.45,
                entry_lat_g=1.05,
                entry_long_g=-1.38,
                tyre_temp_c=88.0,
                compound="slick",
            ),
        ),
        (
            "gt3",
            gt3_ggv,
            "slick",
            "unsupported_out_of_window",  # Lap 8: Wet regime (trackGripLevel=0.78, rain)
            _build_tagged_lap(
                apex_lat_g=0.95,
                entry_lat_g=0.70,
                entry_long_g=-0.85,
                tyre_temp_c=79.0,
                compound="slick",
                track_grip=0.78,
                weather="rain",
            ),
        ),
    ]
    assert len(eight_laps) == 8

    def _evaluate_mode(mode: str) -> dict[str, int]:
        unsupported_cues = 0
        out_of_window_primes = 0
        valid_cues = 0
        for session_id, ggv, compound, label, frames in eight_laps:
            arch = dict(base_archive)
            arch["car"] = {"id": session_id, "tyreCompound": compound}
            rt = build_coach_runtime(
                arch,
                use_environment=False,
                ggv_model=ggv,
                capability_gate_mode=mode,
            )
            assert rt is not None
            rt.ledger.assess_laps = 0
            rt.ledger.hysteresis = 1
            c0 = rt.refs[0].index
            pre_armed = label in {"unsupported_out_of_window", "valid_in_window"}
            if pre_armed:
                # Pre-arm corner 0 with EARLY_BRAKE to test PRIME-time abstention on out-of-window
                # laps vs PRIME emission on valid in-window laps.
                st0 = rt.ledger._states.setdefault(c0, CornerState(c0))
                st0.status = Status.ARMED
                st0.root = RootError.EARLY_BRAKE
                st0.time_lost_s = 5.0
                rt.ledger.begin_lap(1)
                rt.ledger._speak_set = {c0}

            advisories = []
            for f in frames:
                advisories.extend(rt.observe({**f, "lap": 1}))

            prime_fired = sum(
                1
                for a in advisories
                if a.detail.get("coach") == "prime"
                and a.detail.get("root") in {str(RootError.EARLY_BRAKE), str(RootError.SLOW_APEX)}
            )
            diagnosed_demand = sum(
                1
                for r in rt.refs
                if (not pre_armed or r.index != c0)
                and (cst := rt.ledger.state(r.index)) is not None
                and cst.root in {RootError.EARLY_BRAKE, RootError.SLOW_APEX}
            )
            if label.startswith("unsupported"):
                unsupported_cues += diagnosed_demand + prime_fired
                if label == "unsupported_out_of_window":
                    out_of_window_primes += prime_fired
            else:
                valid_cues += diagnosed_demand + prime_fired
        return {
            "unsupported_cues": unsupported_cues,
            "out_of_window_primes": out_of_window_primes,
            "valid_cues": valid_cues,
        }

    baseline_res = _evaluate_mode("baseline")
    denom_res = _evaluate_mode("ggv_denominator_only")
    cond_res = _evaluate_mode("condition_indexed")

    assert baseline_res["unsupported_cues"] > 0
    assert baseline_res["valid_cues"] > 0

    # Denominator-only (b) suppresses pure apex lateral saturation, but still leaks combined-entry
    # and all cold/overheat/wet unsupported cues (< 50% suppression).
    denom_suppression = 1.0 - (denom_res["unsupported_cues"] / baseline_res["unsupported_cues"])
    assert denom_suppression < 0.50

    # Condition-indexed gate (c) must suppress >= 80% of baseline unsupported demand-increasing cues
    # (including 100% PRIME abstention on out-of-window laps) while retaining >= 70% of valid cues.
    cond_suppression = 1.0 - (cond_res["unsupported_cues"] / baseline_res["unsupported_cues"])
    valid_retention = cond_res["valid_cues"] / baseline_res["valid_cues"]

    assert cond_suppression >= 0.80
    assert cond_res["out_of_window_primes"] == 0
    assert valid_retention >= 0.70
