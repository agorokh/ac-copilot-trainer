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


def test_predicted_lap_needs_best_and_fresh_delta() -> None:
    tracker, clock = _tracker()
    tracker.note_lap({"lap": 4, "best_lap_ms": 112275.0, "last_lap_ms": 113000.0})
    assert "predicted_lap_ms" not in (tracker.snapshot() or {})

    tracker.note_delta({"delta_s": 0.5, "spline": 0.3})
    snap = tracker.snapshot()
    assert snap["predicted_lap_ms"] == 112775
    assert snap["delta_s"] == 0.5
    assert snap["lap"] == 4

    # The delta producer stopping drops the prediction — never a frozen value.
    clock.t += DELTA_FRESH_S + 1
    snap = tracker.snapshot()
    assert "predicted_lap_ms" not in snap
    assert "delta_s" not in snap
    assert snap["best_lap_ms"] == 112275.0


def test_negative_delta_predicts_faster_lap_but_never_nonpositive() -> None:
    tracker, _clock = _tracker()
    tracker.note_lap({"best_lap_ms": 100000.0})
    tracker.note_delta({"delta_s": -1.2})
    assert tracker.snapshot()["predicted_lap_ms"] == 98800

    tracker.note_delta({"delta_s": -200.0})  # nonsense reference: prediction suppressed
    assert "predicted_lap_ms" not in tracker.snapshot()


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
