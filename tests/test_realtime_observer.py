"""Tests for the real-time observer core (tools.ai_sidecar.realtime_observer)."""

from __future__ import annotations

import math

import pytest

from tools.ai_sidecar.lap_dynamics import lap_trace_from_archive
from tools.ai_sidecar.realtime_observer import (
    _DEFAULT_TRACK_LENGTH_M,
    RealtimeObserver,
    _frames_from_lap_trace,
    build_observer_from_reference,
)
from tools.ai_sidecar.track_reference import CornerReference, add_corpus_lap, build_references


def _corner_archive(*, degrade: float = 0.0) -> dict:
    """One braking corner; ``degrade`` lowers the carried (apex/entry) speed."""
    radius, ds, n_pre, n_arc, n_post = 30.0, 2.0, 40, 30, 40
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z = 0.0, 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = []
    for i in range(n):
        if i < 25:
            v.append(55.0)
        elif i < apex_i:
            v.append(55.0 + (25.0 - 55.0) * (i - 25) / max(1, apex_i - 25) - degrade)
        elif i < n_pre + n_arc + 5:
            v.append(25.0 + (55.0 - 25.0) * (i - apex_i) / max(1, n_pre + n_arc + 5 - apex_i))
        else:
            v.append(55.0)
    brake = [0.8 if 25 <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_ms = [0.0]
    for i in range(1, n):
        t_ms.append(t_ms[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])) * 1000.0)
    total = ds * (n - 1)
    spline = [(ds * i) / total for i in range(n)]
    samples = [
        [spline[i], v[i] * 3.6, t_ms[i], throttle[i], brake[i], steer[i], 4, xs[i], 0.0, zs[i]]
        for i in range(n)
    ]
    return {
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "lengthM": total},
        "lap": {"lap_ms": int(t_ms[-1]), "is_valid": True},
        "trace": {
            "fields": [
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
            ],
            "samples": samples,
        },
    }


def _replay(observer: RealtimeObserver, archive: dict) -> list:
    lap = lap_trace_from_archive(archive)
    out = []
    for frame in _frames_from_lap_trace(lap):
        out.extend(observer.observe(frame))
    return out


def test_build_observer_returns_none_without_trace():
    assert build_observer_from_reference({}) is None


@pytest.mark.parametrize("track_length_m", [None, "bad", 0.0, -12.0, float("nan")])
def test_observer_defaults_invalid_track_length(track_length_m: object):
    obs = RealtimeObserver([], track_length_m=track_length_m)  # type: ignore[arg-type]

    assert obs._track_length_m == pytest.approx(_DEFAULT_TRACK_LENGTH_M)


def test_reference_lap_against_itself_emits_no_deficit():
    ref = _corner_archive()
    obs = build_observer_from_reference(ref)
    assert obs is not None
    advisories = _replay(obs, ref)
    # driven == reference: on target → no apex deficit, and no brake FAULT (urgent/critical "still
    # coasting past the point"). A *calm anticipatory* brake heads-up before the mark is expected
    # and correct (#368 AC a: the cue's audio onset lands before/at the brake point). This used to
    # assert "no late_brake at all" only because the synthetic corner had no detectable brake point
    # until the corner-segmentation fix gave every real corner a valid brake point.
    assert [a for a in advisories if a.kind == "apex_deficit"] == []
    fault_brakes = [
        a
        for a in advisories
        if a.kind == "late_brake" and a.register in ("alert", "urgent", "critical")
    ]
    assert fault_brakes == []
    for a in (a for a in advisories if a.kind == "late_brake"):
        assert a.register == "calm" and a.detail.get("anticipatory") is True


def test_slower_lap_triggers_apex_deficit():
    obs = build_observer_from_reference(_corner_archive(degrade=0.0))
    assert obs is not None
    advisories = _replay(obs, _corner_archive(degrade=10.0))  # carries much less speed
    deficits = [a for a in advisories if a.kind == "apex_deficit"]
    assert deficits, "a slower lap must produce at least one apex-deficit advisory"
    a = deficits[0]
    assert a.detail["deficit_kmh"] > 0
    assert a.detail["target_apex_kmh"] >= a.detail["min_speed_kmh"]
    assert a.detail["source"] == "corpus_best"  # honest: not a fabricated GGV optimum


def test_coasting_past_point_yields_one_prepare_then_silence():
    """#522: the live brake cue is ONE calm anticipatory heads-up per pass. Coasting past the
    point never draws a spoken imperative (after-the-fact noise); the miss is flagged for
    corner-exit grading instead."""
    ref_lap = lap_trace_from_archive(_corner_archive())
    refs = build_references(ref_lap)
    add_corpus_lap(refs, ref_lap)
    r = refs[0]
    assert r.best_brake_point_spline is not None
    obs = RealtimeObserver(refs)
    bp, apex = r.best_brake_point_spline, r.apex_spline
    mid = (bp + apex) / 2
    frames = [
        {"spline": bp - 0.01, "speed": 200.0, "brake": 0.0},
        {"spline": bp + 0.005, "speed": 200.0, "brake": 0.0},
        {"spline": mid, "speed": 195.0, "brake": 0.0},
    ]
    fired = [a for f in frames for a in obs.observe(f)]
    late = [a for a in fired if a.kind == "late_brake"]
    assert len(late) == 1, "exactly one heads-up per pass, never a past-point imperative"
    assert late[0].urgency == "prepare" and late[0].register == "calm"
    assert late[0].corner == r.index
    # user-facing label is 1-based: corner index 0 -> "T1", never "T0" (codex #294)
    assert "T1" in late[0].message and "T0" not in late[0].message


def test_brake_prepare_fires_before_brake_point():
    ref = CornerReference(
        index=0,
        apex_spline=0.50,
        spline_lo=0.40,
        spline_hi=0.60,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.45,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref], track_length_m=2500.0, brake_prepare_lead_s=1.0)
    # At 110 km/h, one second is 30.6 m, i.e. about 0.012 spline on a 2500 m track.
    out = obs.observe({"spline": 0.44, "speed": 110.0, "brake": 0.0})
    prepare = [a for a in out if a.kind == "late_brake" and a.urgency == "prepare"]
    assert prepare and prepare[0].spline == 0.45
    assert prepare[0].detail["lead_s"] == pytest.approx(0.82, abs=0.05)


def test_brake_prepare_is_not_post_fact_and_does_not_repeat():
    ref = CornerReference(
        index=0,
        apex_spline=0.50,
        spline_lo=0.40,
        spline_hi=0.60,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.45,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref], track_length_m=2500.0, brake_prepare_lead_s=1.0)
    assert obs.observe({"spline": 0.44, "speed": 110.0, "brake": 0.0})
    assert [
        a
        for a in obs.observe({"spline": 0.445, "speed": 110.0, "brake": 0.0})
        if a.urgency == "prepare"
    ] == []
    assert [
        a
        for a in obs.observe({"spline": 0.451, "speed": 110.0, "brake": 0.0})
        if a.urgency == "prepare"
    ] == []


def test_lap_wrap_resets_pass_state():
    obs = build_observer_from_reference(_corner_archive(degrade=0.0))
    assert obs is not None
    slow = _corner_archive(degrade=10.0)
    first = _replay(obs, slow)
    # second lap WITHOUT manual reset: the wrap (spline 1.0 -> ~0.0) must reset pass state
    second = _replay(obs, slow)
    assert [a for a in first if a.kind == "apex_deficit"], "lap 1 should advise"
    assert [a for a in second if a.kind == "apex_deficit"], "lap 2 should advise again after wrap"


def test_trail_brake_before_brake_point_is_not_flagged_late():
    # driver brakes EARLY (inside the window, before the corpus brake point) then releases before
    # apex — normal trail-brake / rotation; must NOT draw a "late brake" cue (codex #294)
    ref = CornerReference(
        index=0,
        apex_spline=0.50,
        spline_lo=0.40,
        spline_hi=0.60,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.45,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref])
    frames = [
        {"spline": 0.42, "speed": 120.0, "brake": 0.6},  # braked EARLY (in window, before bp 0.45)
        {"spline": 0.47, "speed": 95.0, "brake": 0.0},  # released, now past bp before apex
        {"spline": 0.49, "speed": 92.0, "brake": 0.0},
    ]
    fired = [a for f in frames for a in obs.observe(f)]
    assert [a for a in fired if a.kind == "late_brake"] == []


def test_brake_release_can_escalate_after_calm_threshold_crossing():
    ref = CornerReference(
        index=0,
        apex_spline=0.50,
        spline_lo=0.40,
        spline_hi=0.60,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.45,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref])

    calm = obs.observe({"spline": 0.52, "speed": 90.0, "brake": 0.46, "throttle": 0.0})
    urgent = obs.observe({"spline": 0.53, "speed": 88.0, "brake": 0.82, "throttle": 0.0})

    releases = [a for a in [*calm, *urgent] if a.kind == "brake_release"]
    assert [a.register for a in releases] == ["calm", "urgent"]
    assert releases[-1].urgency == "act"


def test_late_brake_fires_upstream_of_corner_window():
    # brake point upstream of turn-in (bp 0.30 < spline_lo 0.40): the anticipatory heads-up
    # must be cued for THAT mark, not delayed until the corner window begins (codex #294;
    # timing now via the #522 lead budget, so the cue arrives well before the mark).
    ref = CornerReference(
        index=0,
        apex_spline=0.45,
        spline_lo=0.40,
        spline_hi=0.55,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.30,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref])
    # inside the lead window (150 km/h x 3.2 s = 133 m = 0.053 spline on the default track)
    out = obs.observe({"spline": 0.28, "speed": 150.0, "brake": 0.0})
    late = [a for a in out if a.kind == "late_brake"]
    assert late and late[0].corner == 0
    assert late[0].urgency == "prepare"
    assert late[0].spline < ref.spline_lo  # cued upstream of turn-in, at the true mark


def _final_corner_ref() -> CornerReference:
    return CornerReference(
        index=0,
        apex_spline=0.95,
        spline_lo=0.90,
        spline_hi=0.99,
        optimal_apex_kmh=120.0,
        best_observed_apex_kmh=120.0,
        best_brake_point_spline=0.88,
        n_corpus=1,
    )


def test_wrap_shaped_pit_return_with_known_lap_is_not_graded():
    # wrap-SHAPED jump (0.92 -> 0.03) but the lap counter NEVER advances => pit/teleport; once the
    # car drives on past the wrap zone the deferred grading is discarded (codex #294 @155/@165)
    obs = RealtimeObserver([_final_corner_ref()])
    obs.observe({"spline": 0.92, "speed": 90.0, "brake": 0.5, "lap": 1})  # inside, slow
    out = []
    out += obs.observe({"spline": 0.03, "speed": 60.0, "brake": 0.0, "lap": 1})  # same lap -> defer
    out += obs.observe({"spline": 0.10, "speed": 70.0, "brake": 0.0, "lap": 1})  # still no advance
    out += obs.observe(
        {"spline": 0.40, "speed": 90.0, "brake": 0.0, "lap": 1}
    )  # drove on -> discard
    assert [a for a in out if a.kind == "apex_deficit"] == []


def test_wrap_with_delayed_lapcount_is_graded_on_the_next_frame():
    # CSP can expose the wrap-shaped spline drop ONE frame before lapCount advances. The drop frame
    # defers; the next frame (counter now advanced) must emit the held grading, not lose it (@165).
    obs = RealtimeObserver([_final_corner_ref()])
    obs.observe(
        {"spline": 0.92, "speed": 90.0, "brake": 0.5, "lap": 1}
    )  # inside, slow (deficit 30)
    drop = obs.observe(
        {"spline": 0.02, "speed": 150.0, "brake": 0.0, "lap": 1}
    )  # drop, counter lags
    nxt = obs.observe({"spline": 0.04, "speed": 150.0, "brake": 0.0, "lap": 2})  # counter advances
    assert [a for a in drop if a.kind == "apex_deficit"] == []  # deferred, not emitted yet
    deficits = [a for a in nxt if a.kind == "apex_deficit"]
    assert deficits and deficits[0].corner == 0 and deficits[0].detail["deficit_kmh"] > 0


def test_real_lap_completion_with_lap_advance_is_graded():
    # same wrap shape, but the lap counter advanced 1 -> 2 => a real lap completion; grade the
    # final corner that ended at the line (codex #294 @155)
    obs = RealtimeObserver([_final_corner_ref()])
    obs.observe(
        {"spline": 0.92, "speed": 90.0, "brake": 0.5, "lap": 1}
    )  # inside, slow (deficit 30)
    out = obs.observe({"spline": 0.03, "speed": 150.0, "brake": 0.0, "lap": 2})  # lap advanced
    deficits = [a for a in out if a.kind == "apex_deficit"]
    assert deficits and deficits[0].corner == 0
    assert deficits[0].detail["deficit_kmh"] > 0


def test_same_lap_rewind_is_not_graded_as_a_wrap():
    # a teleport/pit/replay rewind (prev 0.62 -> 0.05, NOT a start/finish wrap) inside a corner must
    # clear state WITHOUT emitting a spurious apex-deficit for the abandoned stint (codex #294)
    ref = CornerReference(
        index=0,
        apex_spline=0.65,
        spline_lo=0.60,
        spline_hi=0.70,
        optimal_apex_kmh=120.0,
        best_observed_apex_kmh=120.0,
        best_brake_point_spline=0.58,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref])
    obs.observe({"spline": 0.62, "speed": 80.0, "brake": 0.5})  # inside, slow
    rewind = obs.observe({"spline": 0.05, "speed": 90.0, "brake": 0.0})  # backward jump, NOT a wrap
    assert [a for a in rewind if a.kind == "apex_deficit"] == []


def test_ggv_only_reference_is_labelled_ggv_not_corpus():
    # a reference with NO corpus best (GGV theoretical optimum only) must NOT be mislabelled
    # "corpus_best" — the project's named over-claim failure mode (adversarial review #294)
    ref = CornerReference(
        index=0,
        apex_spline=0.5,
        spline_lo=0.4,
        spline_hi=0.6,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=None,  # GGV ceiling only
        best_brake_point_spline=None,
        n_corpus=0,
    )
    obs = RealtimeObserver([ref])
    obs.observe({"spline": 0.5, "speed": 70.0, "brake": 0.4})
    out = obs.observe({"spline": 0.7, "speed": 90.0, "brake": 0.0})
    deficits = [a for a in out if a.kind == "apex_deficit"]
    assert deficits
    assert deficits[0].detail["source"] == "ggv_optimum"
    assert "GGV" in deficits[0].message


def test_final_corner_graded_at_lap_wrap():
    # a corner whose window ends just before the start/finish line must still be graded at the wrap
    ref = CornerReference(
        index=0,
        apex_spline=0.95,
        spline_lo=0.90,
        spline_hi=0.99,
        optimal_apex_kmh=120.0,
        best_observed_apex_kmh=120.0,
        best_brake_point_spline=0.88,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref])
    obs.observe({"spline": 0.92, "speed": 100.0, "brake": 0.5})  # inside, slow (deficit ~20)
    obs.observe({"spline": 0.97, "speed": 100.0, "brake": 0.0})  # still inside, never exits > hi
    wrap = obs.observe({"spline": 0.02, "speed": 150.0, "brake": 0.0})  # lap wraps
    deficits = [a for a in wrap if a.kind == "apex_deficit"]
    assert deficits, "the final corner must be graded when the lap wraps"
    assert deficits[0].corner == 0
    assert deficits[0].detail["deficit_kmh"] > 0


def test_accepts_live_telemetry_tick_payload_shape():
    # the real telemetry_tick frame nests channels under payload with speed named speed_kmh
    ref = CornerReference(
        index=0,
        apex_spline=0.5,
        spline_lo=0.4,
        spline_hi=0.6,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.38,
        n_corpus=1,
    )
    obs = RealtimeObserver([ref])
    # payload-nested in-window slow sample, then exit → apex deficit
    obs.observe(
        {"type": "telemetry_tick", "payload": {"spline": 0.5, "speed_kmh": 70.0, "brake": 0.4}}
    )
    out = obs.observe(
        {"type": "telemetry_tick", "payload": {"spline": 0.7, "speed_kmh": 90.0, "brake": 0.0}}
    )
    deficits = [a for a in out if a.kind == "apex_deficit"]
    assert deficits and deficits[0].detail["deficit_kmh"] == 30.0  # 100 target - 70 carried


def test_malformed_frames_are_ignored():
    obs = build_observer_from_reference(_corner_archive())
    assert obs is not None
    assert obs.observe({}) == []
    assert obs.observe({"spline": "nope", "speed": None}) == []
    assert obs.observe({"spline": float("nan"), "speed": 100.0}) == []
    # telemetry_tick with no spline in payload (current high-rate contract) → can't locate → ignored
    assert obs.observe({"payload": {"speed_kmh": 100.0, "brake": 0.0}}) == []


# ---- issue #522: actionable cue timing ------------------------------------------------------


def _i522_ref():
    return CornerReference(
        index=0,
        apex_spline=0.50,
        spline_lo=0.40,
        spline_hi=0.60,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.45,
        n_corpus=1,
    )


def test_prepare_lead_default_covers_audibility_budget():
    """#522: the default lead is the full audibility budget (~3.2 s), so the prepare clip
    FINISHES with human reaction time to spare — not the old 0.8 s that made 0/8 cues
    actionable in the instrumented lap."""
    obs = RealtimeObserver([_i522_ref()], track_length_m=2500.0)  # default lead
    # 110 km/h = 30.6 m/s; 3.2 s = 97.8 m = 0.0391 spline -> window opens at ~0.4109.
    out = obs.observe({"spline": 0.412, "speed": 110.0, "brake": 0.0})
    prepare = [a for a in out if a.kind == "late_brake" and a.urgency == "prepare"]
    assert prepare, "prepare must fire ~3.2 s before the mark (issue #522)"
    assert prepare[0].detail["lead_s"] == pytest.approx(3.1, abs=0.15)
    # before the window opens: silence
    obs2 = RealtimeObserver([_i522_ref()], track_length_m=2500.0)
    assert obs2.observe({"spline": 0.405, "speed": 110.0, "brake": 0.0}) == []


def test_deep_past_point_imperative_is_silenced_and_graded_at_exit():
    """#522: past 40% of the brake zone a spoken imperative is after-the-fact noise — the
    observer stays SILENT and the miss is owned by corner-exit grading instead."""
    obs = RealtimeObserver([_i522_ref()], track_length_m=2500.0, brake_prepare_lead_s=1.0)
    out = obs.observe({"spline": 0.48, "speed": 140.0, "brake": 0.0})  # progress 0.6
    assert [a for a in out if a.kind == "late_brake"] == []
    out2 = obs.observe({"spline": 0.49, "speed": 130.0, "brake": 0.0})  # still silent
    assert [a for a in out2 if a.kind == "late_brake"] == []
    obs.observe({"spline": 0.50, "speed": 60.0, "brake": 0.0})  # slow apex
    exit_out = obs.observe({"spline": 0.61, "speed": 90.0, "brake": 0.0})
    deficits = [a for a in exit_out if a.kind == "apex_deficit"]
    assert deficits and deficits[0].detail["braked_late_uncoached"] is True
    assert "brake earlier next lap" in deficits[0].message


def test_no_live_imperative_even_on_hot_arrival():
    """#522: there is deliberately NO live brake-fault imperative — a driver braking exactly
    at the mark is indistinguishable from one about to miss it until the mark itself, so a
    spoken correction is either a false alarm or after-the-fact. Hot arrivals get the calm
    heads-up; the miss (if any) is owned by exit grading."""
    obs = RealtimeObserver([_i522_ref()], track_length_m=2500.0, brake_prepare_lead_s=1.0)
    first = obs.observe({"spline": 0.4405, "speed": 200.0, "brake": 0.0})
    late = [a for a in first if a.kind == "late_brake"]
    assert late and late[0].urgency == "prepare" and late[0].register == "calm"
    out = obs.observe({"spline": 0.458, "speed": 195.0, "brake": 0.0})  # hot, past the mark
    assert [a for a in out if a.kind == "late_brake"] == []


def test_late_brake_feedback_survives_without_apex_deficit():
    """#523 review (cursor HIGH): a driver who braked late but still carried target apex
    speed must STILL get the 'brake earlier' verdict at exit — the deferred feedback cannot
    depend on an apex deficit existing."""
    obs = RealtimeObserver([_i522_ref()], track_length_m=2500.0, brake_prepare_lead_s=1.0)
    obs.observe({"spline": 0.48, "speed": 140.0, "brake": 0.0})  # deep past bp -> silent+flag
    obs.observe({"spline": 0.50, "speed": 100.0, "brake": 0.0})  # apex AT target: no deficit
    exit_out = obs.observe({"spline": 0.61, "speed": 110.0, "brake": 0.0})
    assert [a for a in exit_out if a.kind == "apex_deficit"] == []
    late_info = [a for a in exit_out if a.kind == "late_brake" and a.urgency == "info"]
    assert late_info and late_info[0].detail["braked_late_uncoached"] is True
    assert "brake earlier next lap" in late_info[0].message
