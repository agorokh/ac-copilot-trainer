"""Coach v2 keystones — diagnosis classifier + ledger state machine.

These encode the council's correctness contracts as executable assertions:
- coach the ROOT (earliest in the causal chain), not the symptom it causes;
- a single noisy pass never speaks (hysteresis);
- acknowledge a fix once, then go silent; regression re-arms.
"""

from __future__ import annotations

from tools.ai_sidecar.coaching_diagnosis import (
    Diagnosis,
    RootError,
    classify_root_error,
    severity,
)
from tools.ai_sidecar.coaching_ledger import CoachingLedger, Status
from tools.ai_sidecar.lap_dynamics import CornerSignature


def _sig(**over) -> CornerSignature:
    """A reference-ish corner signature; override fields to model a driver's mistake."""
    base = dict(
        index=0,
        entry_i=0,
        apex_i=10,
        exit_i=20,
        apex_spline=0.30,
        min_speed_kmh=80.0,
        entry_speed_kmh=180.0,
        exit_speed_kmh=150.0,
        peak_lat_g=1.4,
        peak_brake_g=1.2,
        peak_accel_g=0.8,
        brake_point_spline=0.250,
        brake_to_apex_m=60.0,
        throttle_on_spline=0.360,
        apex_to_throttle_m=30.0,
        trail_brake_frac=0.40,
        max_abs_steer=0.6,
        direction="right",
    )
    base.update(over)
    return CornerSignature(**base)


# --- diagnosis classifier -------------------------------------------------------------------------
def test_on_reference_is_silence():
    ref = _sig()
    assert classify_root_error(_sig(), ref).root is RootError.NONE


def test_early_brake_diagnosed():
    ref = _sig()
    cand = _sig(brake_point_spline=0.235)  # braked 0.015 spline early (> 0.004 floor)
    assert classify_root_error(cand, ref).root is RootError.EARLY_BRAKE


def test_late_brake_diagnosed():
    ref = _sig()
    cand = _sig(brake_point_spline=0.270)
    assert classify_root_error(cand, ref).root is RootError.LATE_BRAKE


def test_slow_apex_diagnosed():
    ref = _sig()
    cand = _sig(min_speed_kmh=74.0)  # 6 km/h under (> 3 floor), brake/trail on reference
    assert classify_root_error(cand, ref).root is RootError.SLOW_APEX


def test_late_throttle_diagnosed():
    ref = _sig()
    cand = _sig(throttle_on_spline=0.380)  # 0.020 later (> 0.006 floor)
    assert classify_root_error(cand, ref).root is RootError.LATE_THROTTLE


def test_no_trail_diagnosed():
    ref = _sig()
    cand = _sig(trail_brake_frac=0.10)  # ref trails 0.40, driver barely (deficit 0.30 > 0.15)
    assert classify_root_error(cand, ref).root is RootError.NO_TRAIL


def test_root_not_symptom_early_brake_beats_slow_apex():
    """Braking early CAUSES the slow apex. Coach the cause, not the consequence (Mistral 6A)."""
    ref = _sig()
    cand = _sig(brake_point_spline=0.235, min_speed_kmh=72.0)  # both errors present
    assert classify_root_error(cand, ref).root is RootError.EARLY_BRAKE


def test_phrase_and_anchor_present():
    assert Diagnosis(RootError.EARLY_BRAKE).phrase == "Brake later."
    assert Diagnosis(RootError.EARLY_BRAKE).anchor == "brake"
    assert Diagnosis(RootError.LATE_THROTTLE).anchor == "apex"


def test_v2_kinds_disjoint_from_legacy_observer_kinds():
    """M2: v2 advisory kinds must not collide with the legacy observer cue kinds, or the resolver
    mis-routes — this is why RootError.LATE_BRAKE is "brake_late", not "late_brake"."""
    legacy = {"late_brake", "brake_release", "apex_deficit"}
    v2_roots = {r.value for r in RootError if r is not RootError.NONE}
    assert v2_roots.isdisjoint(legacy), f"v2/legacy kind collision: {v2_roots & legacy}"


def test_severity_grades_by_magnitude():
    """severity() escalates register with the measured margin (P2)."""
    minor = Diagnosis(RootError.EARLY_BRAKE, {"brake_delta_spline": -0.006})
    gross = Diagnosis(RootError.EARLY_BRAKE, {"brake_delta_spline": -0.030})
    assert severity(minor)[0] == "firm"
    assert severity(gross)[0] == "critical"
    assert severity(gross)[1] > severity(minor)[1]  # higher intensity for the bigger miss


# --- ledger state machine -------------------------------------------------------------------------
EB = Diagnosis(RootError.EARLY_BRAKE)
CLEAN = Diagnosis(RootError.NONE)


def _drive_error_for(ledger: CoachingLedger, corner: int, n_laps: int, diag: Diagnosis):
    """Drive ``n_laps`` recording ``diag`` at ``corner`` each lap (no prime queried)."""
    for lap in range(1, n_laps + 1):
        ledger.begin_lap(lap)
        ledger.record_pass(corner, diag, time_lost_s=0.3, valid=True)


def test_single_noisy_pass_never_speaks():
    led = CoachingLedger()
    led.begin_lap(3)  # past assess laps
    led.record_pass(1, EB, time_lost_s=0.3, valid=True)  # one bad pass only
    led.begin_lap(4)
    assert led.due_prime(1) is None  # hysteresis (needs 2) → silence


def test_two_consecutive_passes_then_primes():
    led = CoachingLedger()
    _drive_error_for(led, 1, 2, EB)  # laps 1-2: error twice → armed
    assert led.state(1).status is Status.ARMED
    led.begin_lap(3)
    assert led.due_prime(1) is RootError.EARLY_BRAKE  # speaks on lap 3 approach
    assert led.state(1).status is Status.PRIMED


def test_assess_laps_are_silent():
    led = CoachingLedger()
    led.begin_lap(1)
    led.record_pass(1, EB, time_lost_s=0.3, valid=True)
    led.begin_lap(2)
    led.record_pass(1, EB, time_lost_s=0.3, valid=True)  # armed by end of lap 2
    # but lap 2 is an assess lap → still silent even though armed
    assert led.due_prime(1) is None


def test_fix_acknowledged_once_then_silence():
    led = CoachingLedger()
    _drive_error_for(led, 1, 2, EB)
    led.begin_lap(3)
    assert led.due_prime(1) is RootError.EARLY_BRAKE
    led.record_pass(1, EB, time_lost_s=0.3, valid=True)  # still wrong on lap 3
    # lap 4: driver FIXES it
    led.begin_lap(4)
    led.due_prime(1)  # re-primed (still primed, not yet fixed)
    events = led.record_pass(1, CLEAN, time_lost_s=0.0, valid=True)
    assert [e.kind for e in events] == ["confirm"]  # "Good." once
    # lap 5: should be silent (healing), and a second clean pass retires it
    led.begin_lap(5)
    assert led.due_prime(1) is None
    led.record_pass(1, CLEAN, time_lost_s=0.0, valid=True)
    assert led.state(1).status is Status.RETIRED


def test_regression_after_retire_rearms():
    led = CoachingLedger()
    # build to RETIRED via the public path
    _drive_error_for(led, 1, 2, EB)
    led.begin_lap(3)
    led.due_prime(1)
    led.record_pass(1, CLEAN, time_lost_s=0.0, valid=True)
    led.begin_lap(4)
    led.record_pass(1, CLEAN, time_lost_s=0.0, valid=True)
    assert led.state(1).status is Status.RETIRED
    # regress
    led.begin_lap(5)
    led.record_pass(1, EB, time_lost_s=0.4, valid=True)
    assert led.state(1).status is Status.ARMED  # re-armed immediately


def test_invalid_pass_does_not_poison_ledger():
    led = CoachingLedger()
    led.begin_lap(3)
    led.record_pass(1, EB, time_lost_s=5.0, valid=False)  # out-lap / off-track
    assert led.state(1) is None  # nothing recorded


def test_lap_budget_caps_spoken_cues():
    led = CoachingLedger(lap_budget=4)
    # arm 6 corners with increasing time lost
    for c in range(1, 7):
        _drive_error_for_corner(led, c, EB, time_lost=c * 0.1)
    led.begin_lap(3)
    spoken = [c for c in range(1, 7) if led.due_prime(c) is not None]
    assert len(spoken) == 4  # only top-4 by time lost
    assert set(spoken) == {3, 4, 5, 6}  # the biggest losses


def _drive_error_for_corner(led: CoachingLedger, corner: int, diag: Diagnosis, *, time_lost: float):
    for lap in (1, 2):
        led.begin_lap(lap)
        led.record_pass(corner, diag, time_lost_s=time_lost, valid=True)
