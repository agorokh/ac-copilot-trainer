"""Cue-exposure journal (issue #989 stage 0): recording never changes coaching, every ARMED
approach and commit is journaled, and the journal fails closed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.ai_sidecar import coaching_runtime
from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError
from tools.ai_sidecar.coaching_ledger import CoachingLedger, CornerState, Status
from tools.ai_sidecar.coaching_runtime import build_coach_runtime
from tools.ai_sidecar.coaching_trial import (
    ASSIGNMENT_AS_DELIVERED,
    ExposureJournal,
    JournalWriteError,
    RecordingLedger,
    TrialRecorder,
    TrialSeamError,
    assemble_approaches,
    attach_recording_ledger,
    pass_margins,
    read_journal,
    targeted_error,
)

REF_PATH = Path(__file__).resolve().parent / "fixtures" / "magione_gt3r_reference.json"
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="reference trace fixture missing")


def _archive() -> dict:
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


def _lap_frames() -> list[dict]:
    trace = _archive()["trace"]
    return [dict(zip(trace["fields"], row, strict=True)) for row in trace["samples"]]


def _runtime(*, assess=1, hysteresis=1, budget=4, **kwargs):
    runtime = build_coach_runtime(_archive(), use_environment=False, **kwargs)
    assert runtime is not None
    runtime.ledger.assess_laps = assess
    runtime.ledger.hysteresis = hysteresis
    runtime.ledger.lap_budget = budget
    runtime.ledger.begin_lap(1)
    return runtime


def _slow_apex(frames: list[dict], ref, *, kmh: float) -> None:
    for frame in frames:
        if ref.spline_lo <= frame["spline"] <= ref.spline_hi:
            frame["speed"] = max(5.0, frame["speed"] - kmh)


def _stint(runtime, deficits_by_lap: list[dict[int, float]]) -> list[list[dict]]:
    """One lap of frames per entry; each entry maps corner index -> apex deficit (km/h)."""
    refs = {r.index: r for r in runtime.refs}
    laps = []
    for deficits in deficits_by_lap:
        frames = _lap_frames()
        for corner, kmh in deficits.items():
            _slow_apex(frames, refs[corner], kmh=kmh)
        laps.append(frames)
    return laps


def _drive(observe, laps: list[list[dict]]) -> bytes:
    stream = []
    for lap_i, frames in enumerate(laps, start=1):
        for frame in frames:
            stream.extend(asdict(a) for a in observe({**frame, "lap": lap_i}))
    return json.dumps(stream, sort_keys=True).encode("utf-8")


_STINT = [{2: 10.0, 4: 12.0}, {2: 9.0, 4: 14.0}, {2: 11.0, 4: 3.0}, {2: 2.0, 4: 13.0}, {2: 1.0}]


def test_recording_does_not_change_coaching_output_or_ledger_state():
    plain = _runtime()
    baseline = _drive(plain.observe, _stint(plain, _STINT))
    assert b'"coach": "prime"' in baseline  # the scenario really coaches

    for journal in (ExposureJournal(), None):  # journal on, and journal off
        recorded = _runtime()
        recorder = TrialRecorder(recorded, journal=journal, session_id="s1")
        assert _drive(recorder.observe, _stint(recorded, _STINT)) == baseline
        assert isinstance(recorded.ledger, RecordingLedger)
        assert recorded.ledger._states == plain.ledger._states
        assert recorded.ledger._speak_set == plain.ledger._speak_set
        assert recorded.ledger._spoken_this_lap == plain.ledger._spoken_this_lap


def test_every_armed_approach_and_commit_is_journaled(monkeypatch):
    """Oracle: spy on the stock ledger and on the runtime's own anchor-crossing test."""
    peeks: set[tuple[int, int]] = set()
    commits: list[tuple[int, int, str]] = []
    crossings = 0
    stock_armed, stock_due = CoachingLedger.armed_root, CoachingLedger.due_prime
    stock_crossed = coaching_runtime._crossed

    def spy_armed(self, corner):
        root = stock_armed(self, corner)
        if root is not None:
            peeks.add((self._lap, corner))
        return root

    def spy_due(self, corner):
        root = stock_due(self, corner)
        if root is not None:
            commits.append((self._lap, corner, str(root)))
        return root

    def spy_crossed(prev, cur, target):  # the runtime only calls this for an armed root
        nonlocal crossings
        hit = stock_crossed(prev, cur, target)
        crossings += hit
        return hit

    monkeypatch.setattr(CoachingLedger, "armed_root", spy_armed)
    monkeypatch.setattr(CoachingLedger, "due_prime", spy_due)
    monkeypatch.setattr(coaching_runtime, "_crossed", spy_crossed)

    runtime = _runtime()
    journal = ExposureJournal()
    recorder = TrialRecorder(runtime, journal=journal, session_id="s1")
    _drive(recorder.observe, _stint(runtime, _STINT))
    recorder.finish()

    approaches = assemble_approaches(journal.events)
    assert peeks and {(a["lap"], a["corner"]) for a in approaches} == peeks
    assert len(approaches) == len(peeks)  # exactly one record per ARMED (lap, corner)
    journaled_commits = sorted(
        (e["lap"], e["corner"], e["root"]) for e in journal.events if e["event"] == "commit"
    )
    assert journaled_commits == sorted(commits)
    assert crossings == len(commits)  # nothing gated here: every crossing became a commit
    for approach in approaches:
        assert approach["assignment"] == ASSIGNMENT_AS_DELIVERED
        assert approach["session"] == "s1"
        assert approach["root"] == str(RootError.SLOW_APEX)
        assert approach["eligibility"] == "eligible"
        assert approach["committed"] and approach["emitted"]
        assert approach["outcome"] is not None  # the pass that followed is attached


def test_outcome_carries_targeted_error_magnitude_and_corner_time():
    runtime = _runtime()
    journal = ExposureJournal()
    recorder = TrialRecorder(runtime, journal=journal, session_id="s1")
    _drive(recorder.observe, _stint(runtime, [{2: 10.0}, {2: 10.0}, {2: 6.0}]))
    by_lap = {a["lap"]: a for a in assemble_approaches(journal.events) if a["corner"] == 2}
    assert sorted(by_lap) == [2, 3]  # lap 1 is the assess lap
    assert by_lap[2]["outcome"]["targeted_error"] == pytest.approx(10.0, abs=0.2)
    assert by_lap[3]["outcome"]["targeted_error"] == pytest.approx(6.0, abs=0.2)
    for approach in by_lap.values():
        outcome = approach["outcome"]
        assert outcome["targeted_error_unit"] == "km/h"
        assert outcome["pass_measured"] is True and outcome["pass_valid"] is True
        assert outcome["corner_time_s"] > 0.5
        assert set(outcome["margins"]) == {
            "brake_delta_spline",
            "trail_deficit",
            "apex_deficit_kmh",
            "throttle_delta_spline",
        }
    # Same frames, same clock: the corner-time segment is identical on both passes.
    assert by_lap[2]["outcome"]["corner_time_s"] == pytest.approx(
        by_lap[3]["outcome"]["corner_time_s"]
    )


def test_runtime_gate_before_commit_is_journaled_without_a_commit(monkeypatch):
    """The runtime can gate a PRIME before asking the ledger. The approach is still journaled;
    the anchor-crossing instant is the part the ledger seam cannot see (stage 1 needs a hook).
    """
    crossings = 0
    stock_crossed = coaching_runtime._crossed

    def spy_crossed(prev, cur, target):
        nonlocal crossings
        hit = stock_crossed(prev, cur, target)
        crossings += hit
        return hit

    monkeypatch.setattr(coaching_runtime, "_crossed", spy_crossed)
    runtime = _runtime(assess=0, traffic_gate_mode="replay")  # no traffic context: PRIME gated
    runtime.ledger._states[2] = CornerState(
        2, root=RootError.SLOW_APEX, status=Status.ARMED, time_lost_s=9.0
    )
    runtime.ledger.begin_lap(1)
    journal = ExposureJournal()
    recorder = TrialRecorder(runtime, journal=journal, session_id="s1")
    _drive(recorder.observe, _stint(runtime, [{2: 10.0}]))
    recorder.finish()

    (approach,) = assemble_approaches(journal.events)
    assert crossings == 1  # the car did cross the armed anchor
    assert not [e for e in journal.events if e["event"] == "commit"]
    assert approach["committed"] is False and approach["emitted"] is False
    assert approach["eligibility"].startswith("runtime_gated:traffic")
    assert approach["outcome"]["pass_valid"] is False


def test_off_pace_reference_commits_without_emitting():
    runtime = _runtime()
    runtime.reference_lap_ms = 100_000.0
    runtime.note_completed_lap(90_000.0)  # the driver is faster than the reference
    journal = ExposureJournal()
    recorder = TrialRecorder(runtime, journal=journal, session_id="s1")
    stream = _drive(recorder.observe, _stint(runtime, [{2: 10.0}, {2: 10.0}]))
    assert b'"coach": "prime"' not in stream
    (approach,) = assemble_approaches(journal.events)
    assert approach["committed"] is True and approach["emitted"] is False


def test_session_reset_closes_open_approaches_and_keeps_identities_unique():
    runtime = _runtime()
    journal = ExposureJournal()
    recorder = TrialRecorder(runtime, journal=journal, session_id="s1")
    laps = _stint(runtime, [{2: 10.0}, {2: 10.0}])
    _drive(recorder.observe, [laps[0], laps[1][:200]])  # stop early in lap 2: T3 armed, no pass
    runtime.reset()
    _drive(recorder.observe, _stint(runtime, [{2: 10.0}, {2: 10.0}]))
    recorder.finish()
    approaches = assemble_approaches(journal.events)  # raises on a duplicate identity
    assert [a["closed_reason"] for a in approaches if a["outcome"] is None] == ["session_reset"]
    assert len({a["approach_id"] for a in approaches}) == len(approaches) == 2


def test_file_journal_is_exclusive_and_append_only(tmp_path):
    path = tmp_path / "s1.trial.jsonl"
    journal = ExposureJournal(path)
    journal.append("session", session="s1")
    journal.append("lap", session="s1", lap=1)
    journal.close()
    assert [e["seq"] for e in read_journal(path)] == [0, 1]
    with pytest.raises(JournalWriteError, match="journal_open_failed"):
        ExposureJournal(path)  # an existing journal is never reopened or truncated
    assert len(read_journal(path)) == 2


def test_write_failure_latches_and_stops_the_recorder(tmp_path):
    runtime = _runtime()
    journal = ExposureJournal(tmp_path / "s1.trial.jsonl")
    recorder = TrialRecorder(runtime, journal=journal, session_id="s1")
    journal._handle.close()  # the disk goes away mid-session
    with pytest.raises(JournalWriteError):
        _drive(recorder.observe, _stint(runtime, [{2: 10.0}, {2: 10.0}]))
    assert journal.failed
    with pytest.raises(JournalWriteError, match="journal_failed_earlier"):
        journal.append("lap", session="s1")


def test_non_finite_values_cannot_be_journaled():
    journal = ExposureJournal()
    with pytest.raises(JournalWriteError):
        journal.append("outcome", targeted_error=float("nan"))
    assert journal.failed and journal.events == []


def test_read_journal_rejects_malformed_lines(tmp_path):
    path = tmp_path / "bad.trial.jsonl"
    path.write_text('{"schema":"coaching_trial_journal_v1","seq":0,"event":"lap"}\nnot json\n')
    with pytest.raises(ValueError, match="journal_line_invalid"):
        read_journal(path)
    path.write_text('{"schema":"something_else"}\n')
    with pytest.raises(ValueError, match="journal_schema_unsupported"):
        read_journal(path)


def _armed(approach_id="s1:0:2:2"):
    return {"event": "armed", "approach_id": approach_id, "session": "s1", "lap": 2, "corner": 2}


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([_armed(), _armed()], "duplicate_or_missing_approach_identity"),
        ([{"event": "armed", "approach_id": None}], "duplicate_or_missing_approach_identity"),
        ([{"event": "outcome", "approach_id": "ghost"}], "outcome_without_armed_approach"),
        (
            [
                _armed(),
                {"event": "outcome", "approach_id": "s1:0:2:2", "targeted_error": 1.0},
                {"event": "outcome", "approach_id": "s1:0:2:2", "targeted_error": 1.0},
            ],
            "duplicate_pass_outcome",
        ),
        (
            [_armed(), {"event": "outcome", "approach_id": "s1:0:2:2", "targeted_error": -1.0}],
            "non_finite_or_negative_targeted_error",
        ),
        (
            [
                _armed(),
                {"event": "outcome", "approach_id": "s1:0:2:2", "targeted_error": float("inf")},
            ],
            "non_finite_or_negative_targeted_error",
        ),
    ],
)
def test_assemble_rejects_corrupt_journals(events, message):
    with pytest.raises(ValueError, match=message):
        assemble_approaches(events)


def test_attach_refuses_a_practice_runtime_and_an_active_drill():
    runtime = _runtime()
    runtime.practice = object()
    with pytest.raises(ValueError, match="practice_runtime"):
        attach_recording_ledger(runtime, journal=None, session_id="s1")
    ledger = CoachingLedger()
    ledger.drill = object()
    with pytest.raises(ValueError, match="active_drill"):
        RecordingLedger.adopt(ledger, journal=None, session_id="s1")


def test_missing_runtime_seam_raises_instead_of_guessing():
    ledger = RecordingLedger(journal=ExposureJournal(), session_id="s1", assess_laps=0)
    ledger._states[2] = CornerState(2, root=RootError.SLOW_APEX, status=Status.ARMED)
    ledger.begin_lap(1)
    assert ledger.armed_root(2) is RootError.SLOW_APEX
    ledger.bind_runtime(SimpleNamespace(refs=[], ref_sigs={}, last_pass_capability={}))
    with pytest.raises(TrialSeamError, match="runtime_pass_state_unavailable"):
        ledger.record_pass(2, Diagnosis(RootError.NONE), time_lost_s=0.0, valid=True)


def test_margins_and_targeted_error():
    runtime = _runtime()
    ref = runtime.ref_sigs[2]
    assert pass_margins(ref, ref) == {
        "brake_delta_spline": 0.0 if ref.brake_point_spline is not None else None,
        "trail_deficit": 0.0,
        "apex_deficit_kmh": 0.0,
        "throttle_delta_spline": 0.0 if ref.throttle_on_spline is not None else None,
    }
    margins = {"brake_delta_spline": -0.02, "apex_deficit_kmh": 7.5, "trail_deficit": -0.1}
    assert targeted_error("early_brake", margins) == pytest.approx(0.02)
    assert targeted_error("brake_late", margins) == 0.0  # braked early: no late-brake error
    assert targeted_error("slow_apex", margins) == 7.5
    assert targeted_error("no_trail", margins) == 0.0
    assert targeted_error("late_throttle", margins) is None  # not measured on this pass
    assert targeted_error("none", margins) is None
