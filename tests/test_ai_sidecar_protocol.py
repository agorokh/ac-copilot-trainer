"""Protocol helpers and WebSocket round-trip for AI sidecar (issue #45)."""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time

import pytest

import tools.ai_sidecar.protocol as proto
from tools.ai_sidecar.protocol import (
    EVENT_ANALYSIS_ERROR,
    EVENT_COACHING_RESPONSE,
    EVENT_CORNER_ADVICE,
    PROTOCOL_VERSION,
    build_brain_followup,
    prepare_outbound_message,
)


def _rich_corner_archive() -> dict:
    """A single-corner lap archive with per-wheel tyre temps + a conditions block (inline trace)."""
    radius, ds, n_pre, n_arc, n_post = 30.0, 2.0, 40, 30, 40
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z, xs, zs = 0.0, 0.0, 0.0, [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = [55.0 if i < 25 else (25.0 if apex_i - 3 <= i <= apex_i + 3 else 45.0) for i in range(n)]
    brake = [0.8 if 25 <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_ms = [0.0]
    for i in range(1, n):
        t_ms.append(t_ms[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])) * 1000.0)
    spline = [(ds * i) / (ds * (n - 1)) for i in range(n)]
    fields = ["spline", "speed", "eMs", "throttle", "brake", "steer", "gear", "px", "py", "pz"]
    fields += ["tyreCoreTemp_fl", "tyreCoreTemp_fr", "tyreCoreTemp_rl", "tyreCoreTemp_rr"]
    samples = [
        [
            spline[i],
            v[i] * 3.6,
            t_ms[i],
            throttle[i],
            brake[i],
            steer[i],
            4,
            xs[i],
            0.0,
            zs[i],
            35.0,
            35.0,
            35.0,
            35.0,
        ]
        for i in range(n)
    ]
    return {
        "protocol": PROTOCOL_VERSION,
        "event": "lap_complete",
        "lap": 9,
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione"},
        "conditions": {"trackGripLevel": 0.90, "weatherType": "clear"},
        "trace": {"fields": fields, "samples": samples},
    }


def test_brain_followup_forwards_structured_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proto, "debrief_feature_enabled", lambda: True)
    out = build_brain_followup(_rich_corner_archive())
    assert out is not None
    assert out["debriefSource"] == "brain"
    # the integrated understanding blocks must reach live clients, not just the prose debrief
    assert out.get("tyres") is not None
    assert set(out["tyres"]["status"]) == {"fl", "fr", "rl", "rr"}
    assert out.get("conditions") is not None
    assert out["conditions"]["grip_band"] == "green"


def test_cpu_brain_remains_available_with_model_disabled(monkeypatch):
    monkeypatch.setattr(proto, "debrief_feature_enabled", lambda: False)
    out = build_brain_followup(_rich_corner_archive())
    assert out is not None and out["debriefSource"] == "brain"
    assert out["cornerAnalysis"]


def test_chat_provider_preserves_lua_narration_discriminator(monkeypatch):
    monkeypatch.setattr(proto, "debrief_feature_enabled", lambda: True)
    monkeypatch.setattr(proto, "compose_llm_debrief_only", lambda *args: "grounded prose")
    monkeypatch.setattr(proto, "inference_provider", lambda: "openai")
    out = proto.build_ollama_followup({"lap": 1}, [])
    assert out["debriefSource"] == "ollama"
    assert out["inferenceProvider"] == "openai"


def test_live_ws_drops_superseded_corner_without_overlapping_blocking_workers(monkeypatch):
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar import server as srv

    entered, release = threading.Event(), threading.Event()
    calls = []

    def hint(**kwargs):
        calls.append(kwargs["corner"])
        if kwargs["corner"] == "T1":
            entered.set()
            assert release.wait(3)
        return "HOLD STEADY"

    monkeypatch.setattr(proto, "compose_corner_hint", hint)
    monkeypatch.setattr(srv, "debrief_feature_enabled", lambda: False)
    monkeypatch.setattr(srv, "corner_hints_enabled", lambda: True)  # opt-in path (#854)

    async def run():
        async with websockets.serve(lambda ws: srv._handler(ws, True), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:

                def query(corner):
                    return json.dumps(
                        dict(
                            protocol=1,
                            event="corner_query",
                            corner=corner,
                            lap=1,
                            cur=100,
                            ref=100,
                            dist=80,
                            _inference_deadline=0,
                        )
                    )

                await ws.send(query("T1"))
                assert await asyncio.to_thread(entered.wait, 2)
                await ws.send(query("T2"))
                await ws.send(query("T3"))
                # A lap ack stays immediate while model work is blocked.
                await ws.send(json.dumps(dict(protocol=1, event="lap_complete", lap=2)))
                out = json.loads(await asyncio.wait_for(ws.recv(), 1))
                assert out["event"] == "coaching_response" and out["lap"] == 2
                await ws.send(query("T4"))
                release.set()
                advice = json.loads(await asyncio.wait_for(ws.recv(), 2))
                assert advice["corner"] == "T4"
                assert calls == ["T1", "T4"]
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), 0.1)

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_brain_followup_loads_history_paths_for_consistency(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(proto, "debrief_feature_enabled", lambda: True)
    laps_dir = tmp_path / "journal" / "laps"
    laps_dir.mkdir(parents=True)
    hist_path = laps_dir / "lap_history.json"
    history = _rich_corner_archive()
    history["lap"] = 8
    speed_idx = history["trace"]["fields"].index("speed")
    for sample in history["trace"]["samples"][40:60]:
        sample[speed_idx] *= 0.95
    hist_path.write_text(json.dumps(history), encoding="utf-8")
    inbound = _rich_corner_archive()
    inbound["historyArchivePaths"] = [str(hist_path)]
    out = build_brain_followup(inbound)
    assert out is not None
    diagnostics = out["cornerAnalysis"][0]["diagnostics"]
    assert diagnostics["consistency"]["available"] is True
    assert diagnostics["consistency"]["sample_count"] == 2


def test_brain_followup_forwards_sector_benchmarks_with_reference(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proto, "debrief_feature_enabled", lambda: True)
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)
    ref = laps / "lap_ref.json"
    ref.write_text(json.dumps(_rich_corner_archive()), encoding="utf-8")

    out = build_brain_followup(_rich_corner_archive() | {"referenceArchivePath": str(ref)})

    assert out is not None
    assert out.get("sectorDeltas")
    assert out["sectorDeltas"]["micro_sectors"][0]["label"] == "S1.1"
    assert out.get("superLap")
    assert out["superLap"]["segments"][0]["label"] == "S1.1"


def test_prepare_rejects_bad_protocol() -> None:
    out = prepare_outbound_message(
        {"protocol": 99, "event": "lap_complete", "lap": 1},
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR
    assert out["protocol"] == PROTOCOL_VERSION


def test_prepare_coaching_response_fixture() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "lap_complete",
            "lap": 4,
            "lapTimeMs": 91000,
            "coachingHints": ["a"],
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_COACHING_RESPONSE
    assert out["lap"] == 4
    # #854: no "Sidecar vN: ack lap" placeholder — a non-empty list replaces the trainer's own
    # rules-engine lines in the HUD.
    assert out["hints"] == []


def test_prepare_no_reply_mode() -> None:
    assert (
        prepare_outbound_message(
            {"protocol": PROTOCOL_VERSION, "event": "lap_complete", "lap": 1},
            reply_coaching=False,
        )
        is None
    )


def test_corner_query_respects_no_reply_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_k: "SHOULD NOT RUN")
    assert (
        prepare_outbound_message(
            {
                "protocol": PROTOCOL_VERSION,
                "event": "corner_query",
                "corner": "T1",
                "cur": 80,
                "ref": 70,
                "dist": 12,
            },
            reply_coaching=False,
        )
        is None
    )


def test_prepare_rejects_bool_protocol() -> None:
    out = prepare_outbound_message(
        {
            "protocol": True,
            "event": "corner_query",
            "corner": "T1",
            "cur": 80,
            "ref": 70,
            "dist": 12,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_rejects_oversized_label() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "X" * 80,
            "cur": 80,
            "ref": 70,
            "dist": 12,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_requires_protocol_field() -> None:
    out = prepare_outbound_message(
        {
            "event": "corner_query",
            "corner": "T1",
            "cur": 80,
            "ref": 70,
            "dist": 12,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_requires_cur_ref_dist_keys() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "T1",
            "cur": 80,
            "ref": 70,
            # missing dist
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_rejects_bool_speed() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "T1",
            "cur": True,
            "ref": 100,
            "dist": 10,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_silent_when_no_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_: None)
    assert (
        prepare_outbound_message(
            {
                "protocol": PROTOCOL_VERSION,
                "event": "corner_query",
                "corner": "T1",
                "cur": 80,
                "ref": 70,
                "dist": 12,
            },
            reply_coaching=True,
        )
        is None
    )


def test_corner_query_returns_advice_when_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_: "BRAKE EARLIER")
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "T1",
            "cur": 80,
            "ref": 70,
            "dist": 12,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_CORNER_ADVICE
    assert out["text"] == "BRAKE EARLIER"
    assert out["adviceSource"] == "model"  # in-race advice exists only as accepted model text


def test_corner_query_sends_nothing_without_model_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_: None)
    inbound = {"protocol": PROTOCOL_VERSION, "event": "corner_query", "corner": "T1"}
    inbound.update(cur=80, ref=70, dist=12)
    assert prepare_outbound_message(inbound, reply_coaching=True) is None


def test_sidecar_websocket_lap_complete_roundtrip() -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar.server import _handler

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "protocol": PROTOCOL_VERSION,
                            "event": "lap_complete",
                            "lap": 7,
                            "lapTimeMs": 95000,
                            "coachingHints": [],
                        },
                        separators=(",", ":"),
                    )
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["protocol"] == PROTOCOL_VERSION
                assert out["event"] == EVENT_COACHING_RESPONSE
                assert out["lap"] == 7
                # No placeholder: hints replace the trainer's rules lines (#854).
                assert out["hints"] == []

    asyncio.run(_go())


def test_sidecar_corner_query_is_not_sent_to_the_model_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#854: with inference on but in-race hints not opted in, a corner_query gets no reply
    and never reaches the model or the generation queue."""
    websockets = pytest.importorskip("websockets", minversion="12")
    import tools.ai_sidecar.protocol as proto
    from tools.ai_sidecar import server

    monkeypatch.setenv("AC_COPILOT_INFERENCE_ENABLE", "1")
    monkeypatch.delenv("AC_COPILOT_INFERENCE_CORNER_HINTS", raising=False)
    calls: list[dict] = []
    monkeypatch.setattr(proto, "compose_corner_hint", lambda **kw: calls.append(kw) or "ON PACE")
    submits: list[int] = []
    real_submit = server.LatestGenerationQueue.submit

    async def counting_submit(self, call, *, deadline, priority=0):
        submits.append(priority)
        return await real_submit(self, call, deadline=deadline, priority=priority)

    monkeypatch.setattr(server.LatestGenerationQueue, "submit", counting_submit)

    async def _go() -> None:
        async with websockets.serve(
            lambda w: server._handler(w, reply_coaching=True), "127.0.0.1", 0
        ) as srv:
            port = srv.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                query = {"protocol": PROTOCOL_VERSION, "event": "corner_query", "corner": "T1"}
                query.update(cur=80, ref=70, dist=40, lap=0)
                await ws.send(json.dumps(query))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), timeout=0.5)

    asyncio.run(_go())
    assert calls == [] and submits == []


def test_post_lap_generation_outranks_in_race_hints() -> None:
    from tools.ai_sidecar import server

    assert server._NARRATION_PRIORITY > server._BETWEEN_LAP_PRIORITY > server._CORNER_HINT_PRIORITY

    async def _go() -> None:
        import threading

        queue = server.LatestGenerationQueue()
        entered, release = threading.Event(), threading.Event()

        def busy():
            entered.set()
            release.wait(2)

        active = asyncio.create_task(queue.submit(busy, deadline=time.monotonic() + 5))
        await asyncio.to_thread(entered.wait, 2)
        narration = asyncio.create_task(
            queue.submit(
                lambda: "narration",
                deadline=time.monotonic() + 5,
                priority=server._NARRATION_PRIORITY,
            )
        )
        await asyncio.sleep(0)
        corner = await queue.submit(
            lambda: "corner", deadline=time.monotonic() + 5, priority=server._CORNER_HINT_PRIORITY
        )
        release.set()
        assert corner is None  # a corner hint cannot displace pending narration
        assert await narration == "narration"
        await active

    asyncio.run(_go())


def test_sidecar_brain_only_lap_complete_skips_generic_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar import server as srv
    from tools.ai_sidecar.server import _handler

    def _brain(inbound: dict) -> dict:
        return {
            "protocol": PROTOCOL_VERSION,
            "event": EVENT_COACHING_RESPONSE,
            "lap": inbound.get("lap"),
            "hints": [{"kind": "general", "text": "brain"}],
            "debrief": "archive-backed brain",
            "debriefSource": "brain",
            "cornerAnalysis": [{"index": 1, "headline": "T1", "attributions": []}],
            "balance": {"coaching": "ok"},
        }

    monkeypatch.setattr(srv, "build_brain_followup", _brain)

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "protocol": PROTOCOL_VERSION,
                            "event": "lap_complete",
                            "lap": 7,
                            "lapTimeMs": 95000,
                            "archivePath": "journal/laps/lap_test.json",
                            "brainOnly": True,
                        },
                        separators=(",", ":"),
                    )
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["event"] == EVENT_COACHING_RESPONSE
                assert out["debriefSource"] == "brain"
                assert out["debrief"] == "archive-backed brain"
                assert out["hints"][0]["text"] == "brain"
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.recv(), timeout=0.1)

    asyncio.run(_go())


def test_sidecar_non_object_json_gets_analysis_error() -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar.server import _handler

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send("[]")
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["event"] == EVENT_ANALYSIS_ERROR
                assert out["message"] == "root must be a JSON object"

    asyncio.run(_go())


def test_sidecar_invalid_json_gets_analysis_error() -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar.server import _handler

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send("{not json")
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["event"] == EVENT_ANALYSIS_ERROR

    asyncio.run(_go())
