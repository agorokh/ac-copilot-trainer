"""Actual WS factory through baselines/trials with synthetic dispatches, never audio."""

from __future__ import annotations

import asyncio
import json

from websockets.asyncio.server import serve

from tests.test_coaching_practice_bootstrap import _scoped_raw_reference
from tests.test_human_session import ASSISTANCE
from tests.test_server_human_practice import _session_frame, _tick
from tests.test_server_human_practice import study as study
from tests.test_server_practice_activation import _peer, _send
from tools.ai_sidecar import server
from tools.ai_sidecar.external_protocol import AUTH_HEADER
from tools.ai_sidecar.voice.dispatch import VoiceDispatch
from tools.human_session import PRACTICE_COMBO, HumanSessionPermit, close_campaign

CATALOG = {
    "corner_catalog_available": True,
    "corner_catalog": [{"corner_id": "T7", "s0": 0.2, "s1": 0.8, "brake_spline": 0.2}],
    "corner_catalog_car_id": PRACTICE_COMBO[0],
    "corner_catalog_track_id": PRACTICE_COMBO[1],
    "corner_catalog_layout": "",
    "corner_catalog_reference_source": "synthetic_native_catalog",
    "corner_catalog_reference_lap_ms": 60000,
}


async def _complete_lap(ws, root, clock, ordinal, *, baseline_gap=False, cued=False):
    origin = 1000 + (ordinal - 1) * 60.25
    if ordinal == 1:
        clock.now = origin
        await _send(ws, _tick(ordinal, **CATALOG))
    for elapsed in range(250, 60001, 250):
        clock.now = origin + elapsed / 1000
        await _send(ws, _tick(ordinal, elapsed, **CATALOG))
        if cued and elapsed == 2500:
            # Exercise the real server dispatch callback with explicitly synthetic
            # evidence. No scheduler, playback device or acoustic output is claimed.
            server._on_voice_dispatch(
                VoiceDispatch(
                    seq=ordinal,
                    clip_id=f"synthetic-dispatch-{ordinal}",
                    kind="no_trail",
                    urgency="prepare",
                    register="calm",
                    corner=7,
                    text="Synthetic instruction",
                    duration_ms=500.0,
                    t_wall_ms=0.0,
                    t_mono_ms=clock.now * 1000,
                    instructional=True,
                )
            )
            await asyncio.sleep(0)
    clock.now = origin + 60.25
    await _send(ws, _tick(ordinal + 1, **CATALOG))
    record = _scoped_raw_reference(ordinal)
    record["conditions"]["weatherType"] = 15
    if baseline_gap:
        steer = record["trace"]["fields"].index("steer")
        for row in record["trace"]["samples"]:
            row[steer] = 0.0
    path = root / f"lap_factory_progression_{ordinal}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    completion = {
        "protocol": "ac_copilot_trainer.v1",
        "event": "lap_complete",
        "lap": ordinal,
        "lapTimeMs": 60000,
        "archivePath": str(path),
        "brainOnly": True,
    }
    await _send(ws, completion)
    assert path.read_bytes() == before
    return completion


async def _inspection(port, *, token=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        header = f"{AUTH_HEADER}: {token}\r\n" if token else ""
        writer.write(
            (
                "GET /coach/practice HTTP/1.1\r\nHost: localhost\r\n"
                + header
                + "Connection: close\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 2)
        headers, body = response.split(b"\r\n\r\n", 1)
        return int(headers.split(b" ")[1]), json.loads(body) if headers.startswith(
            b"HTTP/1.1 200"
        ) else None
    finally:
        writer.close()
        await writer.wait_closed()


def test_production_factory_reaches_existing_curriculum_after_three_measured_baselines(
    study, monkeypatch
):
    permit_path, root, ledger, clock = study
    # The limiter captures its clock at module construction. Advance that clock
    # with the same synthetic native time; retain its real rate-limit algorithm.
    monkeypatch.setattr(server._peripheral_rate_limiter, "_clock", clock.monotonic)

    async def scenario():
        monkeypatch.setattr(server, "_event_loop", asyncio.get_running_loop())
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            port = listener.sockets[0].getsockname()[1]
            async with _peer(port) as ws:
                await _send(ws, _session_frame())
                await _send(
                    ws,
                    {
                        "v": 1,
                        "type": "state.snapshot",
                        "topic": "coaching.snapshot",
                        "payload": CATALOG,
                    },
                )
                collector = server._human_practice_session
                assert collector is not None
                assert collector.drill_id == "trail-brake-entry"
                await _complete_lap(ws, root, clock, 1)
                await _complete_lap(ws, root, clock, 2)
                runtime = server._coach_runtime
                assert runtime is not None and runtime.practice is collector
                assert runtime.corner_identity["labels"] == {0: "T7"}
                for ordinal in (3, 4, 5):
                    await _complete_lap(ws, root, clock, ordinal, baseline_gap=True)
                status = collector.status()
                assert status["phase"] == "cued", status
                assert status["observed_laps"] == 5 and status["baseline_laps"] == 3
                assert status["cued_attempts"] == 0
                target = runtime.ledger.drill_target
                assert target is not None and target.drill_id == "trail-brake-entry"
                assert target.metric == "trail_brake_frac" and target.trail_brake_frac > 0.12
                assert target.to_dict()["source"] == "operator_attested_session_practice"
                assert runtime is server._coach_runtime and runtime.ledger is collector.ledger
                for ordinal in (6, 7, 8):
                    await _complete_lap(ws, root, clock, ordinal, cued=True)
                assert collector.status()["phase"] == "retention"
                assert not collector.instruction_allowed
                await _complete_lap(ws, root, clock, 9)
                await _complete_lap(ws, root, clock, 10)
                status = collector.status()
                assert status["phase"] == "passed", status
                assert status["observed_laps"] == 10 and status["baseline_laps"] == 3
                assert status["cued_successes"] == 3 and status["retention_successes"] == 2
                assert len(status["voice_evidence"]) == 3
                assert [row["lap_n"] for row in status["evidence"]] == list(range(1, 11))
                capture = HumanSessionPermit.read_status(permit_path, private=True)
                assert capture["phase"] == "closed" and capture["attempted_laps"] == 10
                assert not capture["end_confirmed"]
                assert len(capture["accepted_laps"]) == 10
                assert len(json.loads(ledger.read_bytes())["entries"]) == 10
                assert server.public_voice_runtime_status()["practice_drill"]["phase"] == (
                    "awaiting_end_declaration"
                )
                code, _ = await _inspection(port)
                assert code == 401
                code, receipt = await _inspection(port, token="synthetic-test-token")
                assert code == 200 and receipt["experimental_outcome"] == "unverified"
                assert receipt["human_session"]["driver_id"] == "synthetic-private-driver"
                assert receipt["g3_human_improvement"] == "unverified"
                close_campaign(
                    permit_path,
                    {"driver_id": "synthetic-private-driver", "assistance": dict(ASSISTANCE)},
                )
                _, receipt = await _inspection(port, token="synthetic-test-token")
                assert receipt["experimental_outcome"] == "passed"
                assert receipt["outcome_basis"] == "operator_attested_session_practice"
                assert receipt["g3_human_improvement"] == "unverified"
                assert "synthetic-private-driver" not in json.dumps(
                    server.public_voice_runtime_status()
                )
                changed = {**ASSISTANCE, "tc_level": "changed after capture"}
                close_campaign(
                    permit_path, {"driver_id": "synthetic-private-driver", "assistance": changed}
                )
                _, receipt = await _inspection(port, token="synthetic-test-token")
                assert receipt["experimental_outcome"] == "unverified"
                assert (
                    server.public_voice_runtime_status()["practice_drill"]["phase"] == "unverified"
                )

    asyncio.run(scenario())


def test_production_factory_reports_no_gap_without_inventing_an_unknown_curriculum(
    study, monkeypatch
):
    _, root, _, clock = study
    monkeypatch.setattr(server._peripheral_rate_limiter, "_clock", clock.monotonic)

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            async with _peer(listener.sockets[0].getsockname()[1]) as ws:
                await _send(ws, _session_frame())
                await _send(
                    ws,
                    {
                        "v": 1,
                        "type": "state.snapshot",
                        "topic": "coaching.snapshot",
                        "payload": CATALOG,
                    },
                )
                collector = server._human_practice_session
                for ordinal in range(1, 6):
                    await _complete_lap(ws, root, clock, ordinal)
                status = collector.status()
                assert status["phase"] == "unavailable", status
                assert status["reason"] == "drill_baseline_already_in_target_band"
                assert status["observed_laps"] == 5 and status["baseline_laps"] == 3
                assert collector.ledger.drill is None
                assert status["reason"] != "unknown_curriculum_drill"

    asyncio.run(scenario())
