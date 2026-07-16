"""#531 Part D remainder: fused race.status tracker (fuel / best / delta / predicted lap)."""

from __future__ import annotations

from tools.ai_sidecar.race_status import DELTA_FRESH_S, RaceStatusTracker


class _Clock:
    def __init__(self) -> None:
        self.t = 50.0

    def __call__(self) -> float:
        return self.t


def _tracker() -> tuple[RaceStatusTracker, _Clock]:
    clock = _Clock()
    return RaceStatusTracker(clock=clock), clock


def test_empty_tracker_snapshots_none() -> None:
    tracker, _clock = _tracker()
    assert tracker.snapshot() is None
    assert tracker.snapshot_if_changed() is None


def test_fuel_fields_pass_through_and_persist_across_missing_frames() -> None:
    tracker, _clock = _tracker()
    tracker.note_fuel({"fuel_l": 42.0, "fuel_per_lap_l": 2.6, "laps_remaining": 16.15})
    tracker.note_fuel(None)  # a frame without the fuel channel keeps the measurement

    snap = tracker.snapshot()
    assert snap == {"fuel_l": 42.0, "fuel_per_lap_l": 2.6, "laps_remaining": 16.15}


def test_fuel_cleared_when_channel_live_but_burn_reset() -> None:
    """Lap rollback / refuel: fuel_status() goes None while the channel still reports — the
    prior stint's numbers must drop, not freeze (Codex on PR #615)."""
    tracker, _clock = _tracker()
    tracker.note_fuel({"fuel_l": 42.0, "fuel_per_lap_l": 2.6, "laps_remaining": 16.15})
    tracker.note_fuel(None, channel_live=True)
    assert tracker.snapshot() is None


def test_predicted_lap_needs_reference_baseline_and_fresh_delta() -> None:
    """Predicted = the delta's OWN reference lap + the gap — never the stint best, which is
    the wrong baseline under an imported reference (Codex on PR #615)."""
    tracker, clock = _tracker()
    tracker.note_lap({"lap": 4, "best_lap_ms": 112275.0, "last_lap_ms": 113000.0})
    assert "predicted_lap_ms" not in (tracker.snapshot() or {})

    # A delta WITHOUT its baseline never predicts — even with a stint best on file.
    tracker.note_delta({"delta_s": 0.5, "spline": 0.3})
    assert "predicted_lap_ms" not in tracker.snapshot()

    # A 90 s reference chased at +5 s predicts ~95 s, NOT stint-best 112 s + 5.
    tracker.note_delta({"delta_s": 5.0, "spline": 0.3, "reference_lap_ms": 90000.0})
    snap = tracker.snapshot()
    assert snap["predicted_lap_ms"] == 95000
    assert snap["delta_s"] == 5.0
    assert snap["lap"] == 4

    # The delta producer stopping drops the prediction — never a frozen value.
    clock.t += DELTA_FRESH_S + 1
    snap = tracker.snapshot()
    assert "predicted_lap_ms" not in snap
    assert "delta_s" not in snap
    assert snap["best_lap_ms"] == 112275.0


def test_negative_delta_predicts_faster_lap_but_never_nonpositive() -> None:
    tracker, _clock = _tracker()
    tracker.note_delta({"delta_s": -1.2, "reference_lap_ms": 100000.0})
    assert tracker.snapshot()["predicted_lap_ms"] == 98800

    # nonsense reference: prediction suppressed
    tracker.note_delta({"delta_s": -200.0, "reference_lap_ms": 100000.0})
    assert "predicted_lap_ms" not in tracker.snapshot()


def test_session_replay_does_not_reset_but_identity_change_does() -> None:
    """The bridge re-emits `session` to late subscribers — only a REAL identity change may
    drop the fusion (Codex on PR #615)."""
    tracker, _clock = _tracker()
    ident = {"car_id": "911", "track_id": "magione", "session_index": 0}
    tracker.note_session(ident)
    tracker.note_fuel({"fuel_l": 10.0, "fuel_per_lap_l": 2.0, "laps_remaining": 5.0})
    tracker.note_lap({"best_lap_ms": 112000.0})

    tracker.note_session(dict(ident))  # replay to a late subscriber: state survives
    assert tracker.snapshot() is not None

    tracker.note_session({"car_id": "m3", "track_id": "magione", "session_index": 0})
    assert tracker.snapshot() is None


def test_lap_sentinels_ignored() -> None:
    tracker, _clock = _tracker()
    tracker.note_lap({"best_lap_ms": 0, "last_lap_ms": -5, "lap": -1})
    assert tracker.snapshot() is None


def test_snapshot_if_changed_dedups_identical_payloads() -> None:
    tracker, _clock = _tracker()
    tracker.note_fuel({"fuel_l": 10.0, "fuel_per_lap_l": 2.0, "laps_remaining": 5.0})

    assert tracker.snapshot_if_changed() is not None
    assert tracker.snapshot_if_changed() is None  # unchanged -> quiet

    tracker.note_fuel({"fuel_l": 9.5, "fuel_per_lap_l": 2.0, "laps_remaining": 4.75})
    assert tracker.snapshot_if_changed() is not None


def test_reset_clears_everything() -> None:
    tracker, _clock = _tracker()
    tracker.note_fuel({"fuel_l": 10.0, "fuel_per_lap_l": 2.0, "laps_remaining": 5.0})
    tracker.note_lap({"best_lap_ms": 90000.0})
    tracker.note_delta({"delta_s": 0.1})
    assert tracker.snapshot() is not None

    tracker.reset()
    assert tracker.snapshot() is None
