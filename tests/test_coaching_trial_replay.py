"""Offline replay of lap archives through CoachRuntime with the exposure journal (#989)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.ai_sidecar import coaching_trial_replay as replay
from tools.ai_sidecar.coaching_runtime import build_coach_runtime
from tools.ai_sidecar.coaching_trial import assemble_approaches, read_journal
from tools.coaching_lake.coaching_effect import feasibility_report

REF_PATH = Path(__file__).resolve().parent / "fixtures" / "magione_gt3r_reference.json"
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="reference trace fixture missing")

_DEFICITS = [10.0, 12.0, 8.0, 11.0, 9.0, 13.0]  # km/h lost at T3 on successive laps


def _lap(base: dict, *, session: str, lap_n: int, deficit: float | None, refs) -> dict:
    record = copy.deepcopy(base)
    record["session_uuid"] = session
    record["lap_uuid"] = f"{session}-lap-{lap_n}"
    record["lap"]["lap_n"] = lap_n
    if deficit is not None:
        fields = record["trace"]["fields"]
        spline_i, speed_i = fields.index("spline"), fields.index("speed")
        for corner, scale in ((2, 1.0), (4, 0.6)):
            ref = refs[corner]
            for row in record["trace"]["samples"]:
                if ref.spline_lo <= row[spline_i] <= ref.spline_hi:
                    row[speed_i] = max(5.0, row[speed_i] - deficit * scale)
    return record


@pytest.fixture
def laps_dir(tmp_path) -> Path:
    base = json.loads(REF_PATH.read_text(encoding="utf-8"))
    runtime = build_coach_runtime(base, use_environment=False)
    refs = {r.index: r for r in runtime.refs}
    directory = tmp_path / "journal" / "laps"
    directory.mkdir(parents=True)

    def write(record: dict) -> None:
        (directory / f"lap_{record['lap_uuid']}.json").write_text(json.dumps(record))

    write(_lap(base, session="reference-session", lap_n=1, deficit=None, refs=refs))
    for index in range(3):
        for lap_n, deficit in enumerate(_DEFICITS, start=1):
            write(_lap(base, session=f"session-{index}", lap_n=lap_n, deficit=deficit, refs=refs))
    partial = _lap(base, session="session-0", lap_n=99, deficit=None, refs=refs)
    partial["generator"] = {"tt_reference": {"partial": True}}
    write(partial)
    (directory / "lap_broken.json").write_text("{not json")
    return directory


def _digests(directory: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}


def test_discovery_groups_eligible_sessions_and_names_every_rejection(laps_dir):
    sessions, eligible, rejected = replay.discover_sessions([laps_dir])
    assert [s.session_uuid for s in sessions] == ["session-0", "session-1", "session-2"]
    assert all([lap.lap_n for lap in s.laps] == [1, 2, 3, 4, 5, 6] for s in sessions)
    assert len(eligible) == 19  # 18 session laps + the lone reference lap
    reasons = {Path(r["path"]).name: r["reason"] for r in rejected}
    assert reasons["lap_broken.json"].startswith("unreadable")
    assert reasons["lap_session-0-lap-99.json"] == "analysis: partial_tt_reference"
    assert reasons["lap_reference-session-lap-1.json"] == "session_shorter_than_5_eligible_laps"
    reference = replay.choose_reference(sessions[0], eligible)
    assert reference is not None and reference.record["session_uuid"] != "session-0"


def test_replay_writes_journals_without_touching_archives(laps_dir, tmp_path, capsys):
    before = _digests(laps_dir)
    out = tmp_path / "out"
    assert replay.main(["--laps-dir", str(laps_dir), "--out", str(out)]) == 0
    assert _digests(laps_dir) == before  # archives are immutable
    assert "replayed 3 session(s)" in capsys.readouterr().out

    manifest = json.loads((out / "manifest.json").read_text())
    assert len(manifest["sessions"]) == 3 and not manifest["sessions_without_reference"]
    journals = []
    for summary in manifest["sessions"]:
        assert summary["default_output_identical"] is True
        assert summary["reference"]["sha256"] == before["lap_reference-session-lap-1.json"]
        assert [lap["sha256"] for lap in summary["laps"]] == [
            before[f"lap_{summary['session_uuid']}-lap-{n}.json"] for n in range(1, 7)
        ]
        events = read_journal(out / summary["journal"])
        assert len(events) == summary["events"]
        journals.append(events)
        approaches = assemble_approaches(events)
        assert approaches and all(a["outcome"] is not None for a in approaches)
        assert {a["corner"] for a in approaches} == {2, 4}
        assert [e["lap_n"] for e in events if e["event"] == "lap"] == [1, 2, 3, 4, 5, 6]
    # identical sessions, identical coaching
    assert len({s["advisory_stream_sha256"] for s in manifest["sessions"]}) == 1

    report = feasibility_report(journals, sims=20, perms=19, seed=1)
    assert report["sessions_replayed"] == 3
    assert report["armed_approaches"]["pooled"]["usable_approaches"] > 0
    assert report["decision"]["verdict"] in {"proceed", "inconclusive", "stop"}


def test_replay_refuses_unsafe_output_locations(laps_dir, tmp_path):
    with pytest.raises(SystemExit):
        replay.main(["--laps-dir", str(laps_dir), "--out", str(laps_dir / "out")])
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(SystemExit):
        replay.main(["--laps-dir", str(laps_dir), "--out", str(existing)])
    assert not (laps_dir / "out").exists()


def test_session_without_another_sessions_reference_is_reported(laps_dir, tmp_path):
    for path in laps_dir.glob("lap_session-[12]-*.json"):
        path.unlink()
    (laps_dir / "lap_reference-session-lap-1.json").unlink()
    out = tmp_path / "out"
    assert replay.main(["--laps-dir", str(laps_dir), "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["sessions"] == []
    assert manifest["sessions_without_reference"] == ["session-0"]


def test_a_journal_that_changes_coaching_is_an_error(laps_dir, monkeypatch):
    sessions, eligible, _ = replay.discover_sessions([laps_dir])
    reference = replay.choose_reference(sessions[0], eligible)
    stock = replay.TrialRecorder.observe

    def meddling(self, frame, *, t_ms=None):
        return stock(self, frame, t_ms=t_ms)[:0]  # a recorder that swallows cues

    monkeypatch.setattr(replay.TrialRecorder, "observe", meddling)
    with pytest.raises(replay.ReplayError, match="coaching_output_changed_by_journal"):
        replay.replay_session(sessions[0], reference, journal_path=None)
