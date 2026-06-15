"""L0 regression for the #190 L1.5 WS-sequence probe (`tools/ac_harness/sequence_probe.py`).

`evaluate_sequence` is a pure function over a frame stream, so the declared-topic presence + the
session-before-lap ordering contract are exercised here with synthetic streams — no AC, no sidecar.
The live tap is gated (in-sim on a real drive) and not covered in CI.
"""

from __future__ import annotations

import json

from tools.ac_harness.sequence_probe import (
    DEFAULT_REQUIRED_TOPICS,
    evaluate_sequence,
    frames_from_jsonl,
)


def _f(topic: str) -> dict:
    """A published topic frame as the tap receives it (ws_bridge.publishTopic envelope)."""
    return {"v": 1, "type": "state.snapshot", "topic": topic, "payload": {}}


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


def test_good_stream_passes():
    r = evaluate_sequence(_good_stream())
    assert r.ok is True
    assert all(c.ok for c in r.checks)
    assert r.counts["delta"] == 2
    assert r.counts["tire_temps"] == 2


def test_all_required_topics_present_in_good_stream():
    r = evaluate_sequence(_good_stream())
    present = {c.name for c in r.checks if c.ok and c.name.startswith("present:")}
    for topic in DEFAULT_REQUIRED_TOPICS:
        assert f"present:{topic}" in present


def test_lap_before_session_fails_ordering():
    # lap emitted before any session violates the #182 lifecycle contract.
    frames = [
        _f("connection"),
        _f("lap"),
        _f("session"),
        _f("delta"),
        _f("tire_temps"),
        _f("coaching.snapshot"),
    ]
    r = evaluate_sequence(frames)
    assert r.ok is False
    order = next(c for c in r.checks if c.name == "order:session-before-lap")
    assert order.ok is False


def test_lap_without_session_fails():
    frames = [_f("connection"), _f("lap"), _f("delta"), _f("tire_temps"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames)
    assert r.ok is False
    order = next(c for c in r.checks if c.name == "order:session-before-lap")
    assert order.ok is False
    assert "no session" in order.detail


def test_missing_continuous_topic_fails_presence():
    # No tire_temps at all (e.g. the rr=0-class data-source failure) -> presence check fails.
    frames = [_f("connection"), _f("session"), _f("lap"), _f("delta"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames)
    assert r.ok is False
    tt = next(c for c in r.checks if c.name == "present:tire_temps")
    assert tt.ok is False
    assert tt.detail == "never seen"


def test_empty_stream_fails_all_presence():
    r = evaluate_sequence([])
    assert r.ok is False
    # all required-topic presence checks fail; no ordering check (no lap)
    assert all(not c.ok for c in r.checks if c.name.startswith("present:"))
    assert not any(c.name == "order:session-before-lap" for c in r.checks)


def test_non_topic_and_malformed_frames_ignored():
    # Control frames (no topic) and non-dicts must not break evaluation or inflate counts.
    frames = [
        {"v": 1, "type": "hello-ack"},  # no topic
        "garbage",  # non-dict
        _f("connection"),
        _f("session"),
        _f("lap"),
        _f("delta"),
        _f("tire_temps"),
        _f("coaching.snapshot"),
    ]
    r = evaluate_sequence(frames)
    assert r.ok is True
    assert r.counts["connection"] == 1


def test_setup_active_not_required():
    # setup.active is event-driven (only on a setup change), so a clean lap without it still passes.
    r = evaluate_sequence(_good_stream())
    assert r.ok is True
    assert "setup.active" not in DEFAULT_REQUIRED_TOPICS


def test_frames_from_jsonl_round_trip(tmp_path):
    p = tmp_path / "frames.jsonl"
    lines = [json.dumps(_f(t)) for t in ("connection", "session", "lap")]
    lines.insert(2, "")  # blank line -> skipped
    lines.append("{not valid json")  # invalid -> skipped
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    frames = frames_from_jsonl(str(p))
    assert [f["topic"] for f in frames] == ["connection", "session", "lap"]
