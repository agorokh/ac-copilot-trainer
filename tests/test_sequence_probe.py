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

import asyncio
import json

from tools.ac_harness.sequence_probe import (
    DEFAULT_CONTINUOUS_TOPICS,
    STRICT_LIFECYCLE_TOPICS,
    evaluate_sequence,
    frames_from_jsonl,
    intervention_summary,
    tap_frames,
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


# ------------------------------------------------------------------- require_lap (--wait-lap)
def test_require_lap_fails_when_lap_absent():
    # --wait-lap waited for a lap; if it timed out (lap absent) the probe must FAIL, not pass with
    # lap as a note — otherwise --wait-lap could false-green the lap producer (codex on #191).
    frames = [_f("connection"), _f("tire_temps"), _f("coaching.snapshot")]
    r = evaluate_sequence(frames, require_lap=True)
    assert r.ok is False
    lap = next(c for c in r.checks if c.name == "present:lap")
    assert lap.ok is False


def test_require_lap_passes_when_lap_present():
    r = evaluate_sequence(_good_stream(), require_lap=True)
    assert r.ok is True
    assert any(c.name == "present:lap" and c.ok for c in r.checks)


# --------------------------------------------------------------------------- jsonl loader
def test_frames_from_jsonl_round_trip(tmp_path):
    p = tmp_path / "frames.jsonl"
    lines = [json.dumps(_f(t)) for t in ("connection", "session", "lap")]
    lines.insert(2, "")  # blank line -> skipped
    lines.append("{not valid json")  # invalid -> skipped
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    frames = frames_from_jsonl(str(p))
    assert [f["topic"] for f in frames] == ["connection", "session", "lap"]


# --------------------------------------------------------------------------- #577 timed-lap helpers
def _timed_lap(ms: int | float | None) -> dict:
    frame = _f("lap")
    frame["payload"] = {"last_lap_ms": ms}
    return frame


def test_is_timed_lap_frame_requires_snapshot_lap_topic_and_positive_time():
    from tools.ac_harness.sequence_probe import is_timed_lap_frame

    assert is_timed_lap_frame(_timed_lap(91234)) is True
    assert is_timed_lap_frame(_timed_lap(None)) is False  # out-lap / teleport boundary
    assert is_timed_lap_frame(_timed_lap(0)) is False
    assert is_timed_lap_frame(_timed_lap("nope")) is False
    assert is_timed_lap_frame(_f("lap")) is False  # no payload time
    assert is_timed_lap_frame(_f("tire_temps")) is False
    assert is_timed_lap_frame(_other("lap")) is False  # non-snapshot never counts


def test_timed_lap_times_ms_orders_and_skips_untimed_boundaries():
    from tools.ac_harness.sequence_probe import timed_lap_times_ms

    frames = [
        _f("connection"),
        _timed_lap(None),  # out-lap boundary: no time, not counted
        _timed_lap(95000),
        _f("coaching.snapshot"),
        _timed_lap(92500.7),  # float ms from the wire -> int
        _other("lap"),  # diagnostic frame: never counts
        _timed_lap(91800),
    ]
    assert timed_lap_times_ms(frames) == [95000, 92500, 91800]
    assert timed_lap_times_ms([]) == []


# --- #531 Part D: electronics-intervention evidence -------------------------------------------
#
# The harness's in-run tap was structurally BLIND to `telemetry_tick`: ticks are routed by CLIENT
# CLASS, not by `state.subscribe`, and the tap connected with no class. So Part D's TC/ABS
# intervention criterion could never be evidenced from the prescribed capture path — a prior
# session attributed the never-observed flash to the driver being too clean, but the recorder
# could not have seen it either way. These pin the evidence semantics.


def _tick(**payload: object) -> dict:
    """A `telemetry_tick` as an observer-class peer receives it (peripheral frame, not a topic)."""
    return {"v": 1, "type": "telemetry_tick", "payload": dict(payload)}


def test_intervention_summary_counts_fired_idle_and_absent_separately() -> None:
    frames = [
        _tick(tc_active=True, abs_active=False),
        _tick(tc_active=False, abs_active=False),
        _tick(tc_active=False),  # abs omitted entirely -> absent, NOT idle
    ]
    summary = intervention_summary(frames)
    assert summary["telemetry_ticks"] == 3
    tc = summary["flags"]["tc_active"]
    assert (tc["true"], tc["false"], tc["absent"]) == (1, 2, 0)
    assert tc["fired"] is True and tc["observed"] is True
    abs_ = summary["flags"]["abs_active"]
    assert (abs_["true"], abs_["false"], abs_["absent"]) == (0, 2, 1)
    # Never fired, but the producer DID emit it as a real boolean -> the CSP name resolves.
    assert abs_["fired"] is False and abs_["observed"] is True


def test_intervention_summary_absent_is_not_idle() -> None:
    """A car without the system (M3 GT2 has no ABS) reads `absent`, never `false`.

    This is the distinction that makes a typo'd CSP field name detectable: a wrong name degrades
    to nil and the key is dropped, so it would read `absent` — identical to a car that lacks the
    hardware. Collapsing absent into false would report a broken producer as a clean idle lap.
    """
    summary = intervention_summary([_tick(tc_active=False), _tick(tc_active=False)])
    abs_ = summary["flags"]["abs_active"]
    assert abs_["absent"] == 2
    assert abs_["false"] == 0
    assert abs_["observed"] is False  # never emitted as a boolean at all


def test_intervention_summary_ignores_non_tick_frames() -> None:
    """State snapshots share the stream; only `telemetry_tick` frames carry the flags."""
    summary = intervention_summary([_f("tire_temps"), _f("lap"), _tick(tc_active=True)])
    assert summary["telemetry_ticks"] == 1
    assert summary["flags"]["tc_active"]["true"] == 1


def test_intervention_summary_empty_stream_is_zero_not_crash() -> None:
    summary = intervention_summary([])
    assert summary["telemetry_ticks"] == 0
    for flag in ("tc_active", "abs_active"):
        assert summary["flags"][flag]["fired"] is False
        assert summary["flags"][flag]["observed"] is False


def test_intervention_summary_tolerates_malformed_tick_payload() -> None:
    """A tick with a non-dict payload must not crash the evidence pass mid-drive."""
    summary = intervention_summary(
        [{"v": 1, "type": "telemetry_tick", "payload": None}, _tick(tc_active=True)]
    )
    assert summary["telemetry_ticks"] == 1


def test_tap_frames_is_classless_by_default_and_allows_explicit_opt_in(monkeypatch) -> None:
    """A generic topic tap must not silently join the high-rate peripheral stream."""
    seen: list[str | None] = []

    class _FakeHarnessClient:
        def __init__(self, url: str, *, client_class: str | None = None) -> None:
            del url
            seen.append(client_class)
            self.frames: list[dict] = []

        async def connect(self, **kwargs) -> None:  # noqa: ANN003
            del kwargs

        async def hello(self, **kwargs) -> dict:  # noqa: ANN003
            del kwargs
            return {"type": "hello_ack"}

        async def subscribe(self, topics: list[str]) -> None:
            del topics

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "tools.ai_sidecar.harness_client.HarnessClient",
        _FakeHarnessClient,
    )
    asyncio.run(tap_frames(seconds=0))
    asyncio.run(tap_frames(seconds=0, client_class="observer"))
    assert seen == [None, "observer"]
