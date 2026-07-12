"""Semantic-timeliness metric tests (#522) — synthetic tap, no hardware."""

import json

from tools.ai_sidecar.voice.semantic_timeliness import analyze


def _write_tap(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _ticks(t0, seconds, spline0, spline1, speed, brake_at=None):
    """20 Hz ticks moving linearly spline0->spline1; optional brake onset time offset."""
    rows = []
    n = int(seconds * 20)
    for i in range(n + 1):
        f = i / n
        t = t0 + f * seconds * 1000.0
        brake = 0.0
        if brake_at is not None and t >= t0 + brake_at * 1000.0:
            brake = 0.8
        rows.append(
            {
                "t": t,
                "k": "tick",
                "spline": spline0 + f * (spline1 - spline0),
                "speed": speed,
                "brake": brake,
            }
        )
    return rows


def test_actionable_cue_and_coverage(tmp_path):
    t0 = 1_000_000.0
    # car covers spline 0.40->0.48 over 8 s at 90 km/h (25 m/s -> 200 m on a 2500 m track)
    rows = _ticks(t0, 8.0, 0.40, 0.48, 90.0, brake_at=6.0)
    mark = 0.46  # brake point ~150 m ahead of start
    rows.append(
        {
            "t": t0 + 1000.0,
            "k": "coaching.cue",
            "payload": {"kind": "late_brake", "urgency": "prepare", "spline": mark},
        }
    )
    rows.append(
        {
            "t": t0 + 1000.0,
            "k": "coaching.voice",
            "payload": {
                "seq": 1,
                "clip_id": "late_brake.prepare.calm.t01",
                "kind": "late_brake",
                "urgency": "prepare",
                "register": "calm",
                "duration_ms": 1200,
                "t_wall_ms": t0 + 1000.0,
            },
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0, audio_latency_s=0.1)
    assert report.summary.get("ACTIONABLE") == 1
    assert report.brake_events == 1 and report.brake_events_coached == 1
    assert all(report.assertions.values()), report.assertions


def test_after_fact_cue_fails_assertions(tmp_path):
    t0 = 2_000_000.0
    rows = _ticks(t0, 8.0, 0.40, 0.48, 90.0)
    mark = 0.405  # mark far behind the car by the time the cue sounds
    rows.append(
        {
            "t": t0 + 5000.0,
            "k": "coaching.cue",
            "payload": {"kind": "late_brake", "urgency": "act", "spline": mark},
        }
    )
    rows.append(
        {
            "t": t0 + 5000.0,
            "k": "coaching.voice",
            "payload": {
                "seq": 1,
                "clip_id": "late_brake.act.urgent.generic",
                "kind": "late_brake",
                "urgency": "act",
                "register": "urgent",
                "duration_ms": 380,
                "t_wall_ms": t0 + 5000.0,
            },
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0)
    assert report.summary.get("AFTER_FACT") == 1
    assert report.assertions["no_after_fact_brake_cues"] is False


def test_empty_tap_fails_evidence_assertion(tmp_path):
    """#523 review (Codex P2): an empty/no-voice tap proves nothing and must FAIL the gate."""
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, _ticks(1_000.0, 2.0, 0.1, 0.12, 80.0))  # a few ticks, zero cues
    report = analyze(tap, track_length_m=2500.0)
    assert report.assertions["evidence_present"] is False
