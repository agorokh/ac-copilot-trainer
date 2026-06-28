"""M0 (#341) server wiring: live telemetry_tick -> RealtimeObserver -> coaching.cue fan-out."""

from __future__ import annotations

import asyncio
import json

import tools.ai_sidecar.server as server
from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar.external_protocol import TOPIC_COACHING_CUE, TYPE_STATE_SNAPSHOT
from tools.ai_sidecar.realtime_observer import Advisory


class _FakeObserver:
    def __init__(self, advisories):
        self._advisories = advisories
        self.seen: list[dict] = []

    def observe(self, frame):
        self.seen.append(frame)
        return self._advisories


def _capture_broadcast(monkeypatch):
    sent: list[tuple[dict, object]] = []

    async def _fake_broadcast(frame, *, exclude):
        sent.append((frame, exclude))

    monkeypatch.setattr(server, "_broadcast_external", _fake_broadcast)
    return sent


def test_publish_observer_cues_broadcasts_coaching_cue(monkeypatch):
    adv = Advisory(
        kind="late_brake", corner=3, spline=0.5, urgency="act", message="brake", detail={}
    )
    observer = _FakeObserver([adv])
    monkeypatch.setattr(server, "_observer", observer)
    sent = _capture_broadcast(monkeypatch)

    frame = {"type": "telemetry_tick", "payload": {"spline": 0.5, "speed_kmh": 100}}
    asyncio.run(server._publish_observer_cues(frame, exclude="ws-1"))

    assert observer.seen == [frame]
    assert len(sent) == 1
    cue_frame, exclude = sent[0]
    assert exclude == "ws-1"
    assert cue_frame["type"] == TYPE_STATE_SNAPSHOT
    assert cue_frame["topic"] == TOPIC_COACHING_CUE
    assert cue_frame["state"]["kind"] == "late_brake"
    assert cue_frame["state"]["corner"] == 3


def test_publish_observer_cues_noop_without_observer(monkeypatch):
    monkeypatch.setattr(server, "_observer", None)
    sent = _capture_broadcast(monkeypatch)
    asyncio.run(
        server._publish_observer_cues({"type": "telemetry_tick", "payload": {}}, exclude=None)
    )
    assert sent == []


def test_publish_observer_cues_swallows_observer_error(monkeypatch):
    class _Boom:
        def observe(self, frame):
            raise RuntimeError("boom")

    monkeypatch.setattr(server, "_observer", _Boom())
    sent = _capture_broadcast(monkeypatch)
    # must not raise — the peripheral path is never broken by an observer fault
    asyncio.run(
        server._publish_observer_cues({"type": "telemetry_tick", "payload": {}}, exclude=None)
    )
    assert sent == []


def test_load_observer_builds_from_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_observer", None)
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    server._load_observer(str(ref))
    assert server._observer is not None


def test_load_observer_missing_file_leaves_none(monkeypatch):
    monkeypatch.setattr(server, "_observer", object())
    server._load_observer("does-not-exist-9f3a.json")
    assert server._observer is None
