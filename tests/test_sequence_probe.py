"""L0 regression for the L1.5 WS-sequence probe (`tools/ac_harness/sequence_probe.py`).

The probe is Part E of EPIC #154, verifying the #180 producer pipeline. `evaluate_sequence` is a
pure function over a frame stream, so the continuous-stream presence, the state.snapshot-only
filter, the conditional-lifecycle handling, and the session-before-lap ordering are exercised here
with synthetic streams — no AC, no sidecar. The live tap is gated (in-sim on a real drive), not CI.

Two modes: default "window" (ad-hoc / mid-session tap) requires only the continuous streams and
treats session/lap/delta as conditional notes; `strict_lifecycle=True` (controlled tap from session
start) also requires session + lap and strictly enforces session→lap ordering. `delta` is never
required (it depends on a reference lap), only ever a note.
"""

from __future__ import annotations

import json

from tools.ac_harness.sequence_probe import (
    DEFAULT_CONTINUOUS_TOPICS,
    STRICT_LIFECYCLE_TOPICS,
    evaluate_sequence,
    frames_from_jsonl,
)


def _f(topic: str) -> dict:
    """A published topic frame as the tap receives it (ws_bridge.publishTopic envelope)."""
    return {"v": 1, "type": "state.snapshot", "topic": topic, "payload": {}}


def _other(topic: str) -> dict:
    """A non-snapshot frame that merely carries a topic key (must NOT count)."""
    return {"v": 1, "type": "diagnostic", "topic": topic}


def _good_stream() -> list[dict]:
    # connection heartbeat, session before lap, then continuous streams — a normal drive.
    return [
        _f("connection"),
        _f("session"),
        _f("delta"),
        _f("tire_temps"),
        _f("coaching.snapshot"),
        _f("lap"),
        _f("delta"),
        _f("tire_temps"),
    ]


# --------------------------------------------------------------------------- default "window" mode
def test_good_stream_passes():
    r = evaluate_sequence(_good_stream())
    assert r.ok is True
    assert all(c.ok for c in r.checks)
    assert r.counts["delta"] == 2
    assert r.counts["tire_temps"] == 2


def test_continuous_topics_are_required_checks():
    r = evaluate_sequence(_good_stream())
    check_names = {c.name for c in r.checks}
    for topic in DEFAULT_CONTINUOUS_TOPICS:
        assert f"present:{topic}" in check_names


def test_missing_continuous_topic_fails():
    # No tire_temps at all (e.g. the rr=0-class data-source failure) -> continuous presence fails.
    frames = [_f("connection"), _f("session"), _f("lap"), _f("delta"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames)
    assert r.ok is False
    tt = next(c for c in r.checks if c.name == "present:tire_temps")
    assert tt.ok is False
    assert tt.detail == "never seen"


def test_non_snapshot_frames_do_not_count():
    # A diagnostic/client frame carrying topic="lap"/"tire_temps" must NOT satisfy the contract.
    frames = [
        _f("connection"),
        _f("coaching.snapshot"),
        _other("tire_temps"),  # not a snapshot -> tire_temps still missing
        _other("lap"),  # not a snapshot -> lap not counted
    ]
    r = evaluate_sequence(frames)
    assert r.ok is False
    assert "tire_temps" not in r.counts  # the diagnostic frame did not inflate the count
    assert "lap" not in r.counts


def test_lap_without_session_is_ok_in_window_mode():
    # Mid-session tap: a `lap` with no `session` is the session-event-preceded-the-tap case, NOT a
    # violation (the exact situation the live operator drive surfaced). Continuous present -> PASS.
    frames = [_f("connection"), _f("lap"), _f("delta"), _f("tire_temps"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames)
    assert r.ok is True
    assert not any(c.name == "order:session-before-lap" for c in r.checks)
    assert any("mid-session" in n for n in r.notes)


def test_session_lap_delta_reported_as_notes_in_window_mode():
    r = evaluate_sequence(_good_stream())
    note_text = " ".join(r.notes)
    for topic in ("session", "lap", "delta"):
        assert topic in note_text


def test_session_after_lap_fails_ordering():
    # If BOTH are observed and session comes AFTER lap, that IS a real ordering violation.
    frames = [_f("connection"), _f("lap"), _f("session"), _f("tire_temps"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames)
    assert r.ok is False
    order = next(c for c in r.checks if c.name == "order:session-before-lap")
    assert order.ok is False


def test_empty_stream_fails_continuous_presence():
    r = evaluate_sequence([])
    assert r.ok is False
    assert all(not c.ok for c in r.checks if c.name.startswith("present:"))
    assert not any(c.name == "order:session-before-lap" for c in r.checks)


def test_non_topic_and_malformed_frames_ignored():
    frames = [{"v": 1, "type": "hello-ack"}, "garbage", *_good_stream()]
    r = evaluate_sequence(frames)
    assert r.ok is True
    assert r.counts["connection"] == 1


def test_setup_active_not_required():
    assert "setup.active" not in DEFAULT_CONTINUOUS_TOPICS
    assert "setup.active" not in STRICT_LIFECYCLE_TOPICS


# --------------------------------------------------------------------------- strict_lifecycle mode
def test_strict_requires_session_and_lap():
    r = evaluate_sequence(_good_stream(), strict_lifecycle=True)
    assert r.ok is True
    names = {c.name for c in r.checks}
    for topic in STRICT_LIFECYCLE_TOPICS:
        assert f"present:{topic}" in names
    assert "order:session-before-lap" in names


def test_strict_fails_on_missing_session():
    frames = [_f("connection"), _f("lap"), _f("delta"), _f("tire_temps"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames, strict_lifecycle=True)
    assert r.ok is False
    sess = next(c for c in r.checks if c.name == "present:session")
    assert sess.ok is False
    order = next(c for c in r.checks if c.name == "order:session-before-lap")
    assert order.ok is False


def test_strict_does_not_require_delta():
    # delta needs a reference lap; requiring it would false-fail a healthy no-reference session.
    # A full session→lap with NO delta must still PASS in strict mode (delta stays a note).
    frames = [_f("connection"), _f("session"), _f("lap"), _f("tire_temps"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames, strict_lifecycle=True)
    assert r.ok is True
    assert not any(c.name == "present:delta" for c in r.checks)
    assert any(n.startswith("delta:") for n in r.notes)


# --------------------------------------------------------------------------- jsonl loader
def test_frames_from_jsonl_round_trip(tmp_path):
    p = tmp_path / "frames.jsonl"
    lines = [json.dumps(_f(t)) for t in ("connection", "session", "lap")]
    lines.insert(2, "")  # blank line -> skipped
    lines.append("{not valid json")  # invalid -> skipped
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    frames = frames_from_jsonl(str(p))
    assert [f["topic"] for f in frames] == ["connection", "session", "lap"]
