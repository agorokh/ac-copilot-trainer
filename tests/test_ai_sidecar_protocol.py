"""Protocol helpers and WebSocket round-trip for AI sidecar (issue #45)."""

from __future__ import annotations

import asyncio
import json
import math

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
    assert isinstance(out["hints"], list)
    assert out["hints"][0]["text"]


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
                assert len(out["hints"]) >= 1

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
