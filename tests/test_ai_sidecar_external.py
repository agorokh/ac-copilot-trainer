"""External-client extension tests for the AI sidecar (issue #81).

Covers:
- ``make_token_check`` returns ``None`` when no token is configured.
- Argparse refuses ``--external-bind`` without ``--token``.
- ``external_protocol.validate_inbound`` enforces the v1 envelope contract.
- WS upgrade rejects on missing token, accepts with matching token.
- Hub fan-out: ``config.set`` from peer A reaches peer B and the simulated
  ack from B reaches A.
- Action with unknown name surfaces as an ``error`` frame from the sidecar.

Tests use plain ``asyncio.run`` — repo has no pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

websockets = pytest.importorskip("websockets")
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.asyncio.server import serve as ws_serve  # noqa: E402

from tools.ai_sidecar import external_protocol as ep  # noqa: E402
from tools.ai_sidecar.server import (  # noqa: E402
    _handler,
    _is_loopback,
    _RateLimiter,
    _reset_external_state,
    make_token_check,
)
from tools.ai_sidecar.setup_optimizer import rebuild_experiments  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _write_setup_lap(
    lap_dir: Path,
    name: str,
    setup_hash: str,
    lap_ms: int,
    front_bias: int,
) -> Path:
    lap_dir.mkdir(parents=True, exist_ok=True)
    path = lap_dir / f"lap_20260616-000000_{name}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lap_uuid": name,
                "session_uuid": "sess",
                "exported_at": "2026-06-16T00:00:00Z",
                "car": {"id": "ks_porsche_911_gt3_r_2016"},
                "track": {"id": "magione"},
                "conditions": {"trackGripLevel": 0.98},
                "lap": {"lap_n": 1, "lap_ms": lap_ms, "is_valid": True},
                "setup": {
                    "hash": setup_hash,
                    "path": f"C:/setups/{setup_hash}.ini",
                    "snapshot": {
                        "FRONT_BIAS.VALUE": str(front_bias),
                        "WING_2.VALUE": "9",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@asynccontextmanager
async def _running_sidecar(token: str | None = None) -> AsyncIterator[int]:
    port = _free_port()
    process_request = make_token_check(token)
    _reset_external_state()
    try:
        async with ws_serve(
            lambda ws: _handler(ws, reply_coaching=True),
            "127.0.0.1",
            port,
            process_request=process_request,
        ):
            yield port
    finally:
        _reset_external_state()


def _telemetry_tick(**payload_overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "speed_kmh": 112.0,
        "rpm": 5400.0,
        "gear": 3,
        "throttle": 0.72,
        "brake": 0.84,
        "steer": -0.13,
        "lat_g": 0.42,
        "long_g": -0.78,
        "lap_time_ms": 42123.0,
        "abs_active": True,
        "tyre_temps_c": {"fl": 74.1, "fr": 73.8, "rl": 72.4, "rr": 72.9},
    }
    payload.update(payload_overrides)
    return {
        "v": 1,
        "type": ep.TYPE_TELEMETRY_TICK,
        "seq": 7,
        "ts_sim": 123.45,
        "payload": payload,
    }


def _haptic_event(**overrides: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "v": 1,
        "type": ep.TYPE_HAPTIC_EVENT,
        "event": "pedal_rumble",
        "channel": "pedal",
        "intensity": 0.8,
        "duration_ms": 80,
        "ts_sim": 123.45,
    }
    frame.update(overrides)
    return frame


def test_make_token_check_returns_none_without_token() -> None:
    assert make_token_check(None) is None
    assert make_token_check("") is None


def test_is_loopback_classification() -> None:
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("localhost")
    assert _is_loopback("::1")
    assert not _is_loopback("0.0.0.0")
    assert not _is_loopback("192.168.1.10")


def test_validate_inbound_accepts_known_types() -> None:
    assert ep.validate_inbound({"v": 1, "type": "hello", "client": "screen-01"}) is None
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "hello",
                "client": "uno-haptics-01",
                "client_class": ep.CLIENT_CLASS_HAPTICS,
            }
        )
        is None
    )
    assert ep.validate_inbound({"v": 1, "type": "config.get", "key": "hudEnabled"}) is None
    assert (
        ep.validate_inbound({"v": 1, "type": "config.set", "key": "hudEnabled", "value": True})
        is None
    )
    assert ep.validate_inbound({"v": 1, "type": "action", "name": "toggleFocusPractice"}) is None
    assert ep.validate_inbound({"v": 1, "type": "state.subscribe", "topics": ["lap"]}) is None
    assert (
        ep.validate_inbound(
            {"v": 1, "type": "setup.experiment.record", "archive_path": "journal/laps/lap_1.json"}
        )
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.experiment.store",
                "store_path": "journal/setup_experiments/experiments.jsonl",
            }
        )
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.compare",
                "baseline_setup": "old",
                "candidate_setup": "new",
            }
        )
        is None
    )
    assert ep.validate_inbound({"v": 1, "type": "setup.suggest", "track_id": "magione"}) is None
    assert ep.validate_inbound({"v": 1, "type": "setup.spinner.list"}) is None
    assert (
        ep.validate_inbound(
            {"v": 1, "type": "setup.spinner.set", "section": "FRONT_BIAS", "value": 65}
        )
        is None
    )
    assert ep.validate_inbound(_telemetry_tick()) is None
    assert ep.validate_inbound(_telemetry_tick(slip=-0.35)) is None
    assert ep.validate_inbound(_telemetry_tick(tyre_temps_c={"fl": 74.1})) is None
    assert ep.validate_inbound(_haptic_event()) is None


def test_validate_inbound_rejects_invalid() -> None:
    assert "unsupported envelope version" in (ep.validate_inbound({"type": "hello"}) or "")
    assert "unsupported envelope version" in (
        ep.validate_inbound({"v": True, "type": "hello", "client": "screen-01"}) or ""
    )
    assert "non-empty 'client'" in (ep.validate_inbound({"v": 1, "type": "hello"}) or "")
    assert "unknown client_class" in (
        ep.validate_inbound({"v": 1, "type": "hello", "client": "x", "client_class": "toaster"})
        or ""
    )
    assert "non-empty 'key'" in (ep.validate_inbound({"v": 1, "type": "config.get"}) or "")
    assert "value" in (ep.validate_inbound({"v": 1, "type": "config.set", "key": "k"}) or "")
    assert "unknown action" in (
        ep.validate_inbound({"v": 1, "type": "action", "name": "rmRfRoot"}) or ""
    )
    assert "unknown topic" in (
        ep.validate_inbound({"v": 1, "type": "state.subscribe", "topics": ["pit_window"]}) or ""
    )
    assert "archive_path" in (
        ep.validate_inbound({"v": 1, "type": "setup.experiment.record"}) or ""
    )
    assert "store_path" in (ep.validate_inbound({"v": 1, "type": "setup.experiment.store"}) or "")
    assert "baseline_setup" in (ep.validate_inbound({"v": 1, "type": "setup.compare"}) or "")
    assert "section" in (
        ep.validate_inbound({"v": 1, "type": "setup.spinner.set", "value": 66}) or ""
    )
    assert "finite number" in (
        ep.validate_inbound(
            {"v": 1, "type": "setup.spinner.set", "section": "FRONT_BIAS", "value": "66"}
        )
        or ""
    )
    assert "payload" in (ep.validate_inbound({"v": 1, "type": "telemetry_tick"}) or "")
    assert "throttle must be <= 1" in (ep.validate_inbound(_telemetry_tick(throttle=1.2)) or "")
    assert "lap_time_ms must be >= 0" in (
        ep.validate_inbound(_telemetry_tick(lap_time_ms=-1)) or ""
    )
    assert "requires at least one corner" in (
        ep.validate_inbound(_telemetry_tick(tyre_temps_c={})) or ""
    )
    assert "not a known corner" in (
        ep.validate_inbound(_telemetry_tick(tyre_temps_c={"front_left": 74.1})) or ""
    )
    assert "tyre_temps_c.fl requires a finite number" in (
        ep.validate_inbound(_telemetry_tick(tyre_temps_c={"fl": "hot"})) or ""
    )
    assert "intensity must be <= 1" in (ep.validate_inbound(_haptic_event(intensity=1.4)) or "")
    assert "unknown type" in (ep.validate_inbound({"v": 1, "type": "explode"}) or "")


def test_external_bind_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argparse refuses --external-bind without --token (SystemExit)."""
    from tools.ai_sidecar import server as srv

    monkeypatch.delenv("AC_COPILOT_SIDECAR_TOKEN", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["ai_sidecar", "--external-bind", "0.0.0.0", "--port", "0"],
    )
    with pytest.raises(SystemExit):
        srv.main()


def test_external_bind_accepts_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rig-screen auto-start can keep the token in the process environment."""
    from tools.ai_sidecar import server as srv

    seen: dict[str, object] = {}

    async def fake_run(
        host: str, port: int, reply: bool, token: str | None, setup_store: str | None
    ):
        seen.update(
            {
                "host": host,
                "port": port,
                "reply": reply,
                "token": token,
                "setup_store": setup_store,
            }
        )

    monkeypatch.setenv("AC_COPILOT_SIDECAR_TOKEN", "env-token")
    monkeypatch.setattr(srv, "_run", fake_run)

    def fake_wire_voice(
        ref_path: str | None,
        bank_dir: str | None,
        *,
        tts_enabled: bool,
        tts_rate: int | None,
        tts_volume: float | None,
        voice_backend: str | None,
        voice_device: str | None,
        voice_host_api: str | None,
        voice_verbosity: str | None,
    ) -> None:
        del (
            ref_path,
            bank_dir,
            tts_enabled,
            tts_rate,
            tts_volume,
            voice_backend,
            voice_device,
            voice_host_api,
            voice_verbosity,
        )

    monkeypatch.setattr(srv, "_wire_voice", fake_wire_voice)
    monkeypatch.setattr(
        "sys.argv",
        ["ai_sidecar", "--external-bind", "0.0.0.0", "--port", "0"],
    )

    srv.main()

    assert seen == {
        "host": "0.0.0.0",
        "port": 0,
        "reply": True,
        "token": "env-token",
        "setup_store": None,
    }


def test_main_wires_voice_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Content Manager autostart inherits voice env without fragile batch quoting."""
    from tools.ai_sidecar import server as srv

    seen: dict[str, object] = {}

    async def fake_run(
        host: str, port: int, reply: bool, token: str | None, setup_store: str | None
    ):
        del host, port, reply, token, setup_store

    def fake_wire_voice(
        ref_path: str | None,
        bank_dir: str | None,
        *,
        tts_enabled: bool,
        tts_rate: int | None,
        tts_volume: float | None,
        voice_backend: str | None,
        voice_device: str | None,
        voice_host_api: str | None,
        voice_verbosity: str | None,
    ) -> None:
        seen["ref_path"] = ref_path
        seen["bank_dir"] = bank_dir
        seen["tts_enabled"] = tts_enabled
        seen["tts_rate"] = tts_rate
        seen["tts_volume"] = tts_volume
        seen["voice_backend"] = voice_backend
        seen["voice_device"] = voice_device
        seen["voice_host_api"] = voice_host_api
        seen["voice_verbosity"] = voice_verbosity

    monkeypatch.setenv("AC_COPILOT_REFERENCE_ARCHIVE", "ref.json")
    monkeypatch.setenv("AC_COPILOT_VOICE_BANK", "voice-bank")
    monkeypatch.setenv("AC_COPILOT_VOICE_TTS", "1")
    monkeypatch.setattr(srv, "_run", fake_run)
    monkeypatch.setattr(srv, "_wire_voice", fake_wire_voice)
    monkeypatch.setattr("sys.argv", ["ai_sidecar", "--host", "127.0.0.1", "--port", "0"])

    srv.main()

    assert seen == {
        "ref_path": "ref.json",
        "bank_dir": "voice-bank",
        "tts_enabled": True,
        "tts_rate": None,
        "tts_volume": None,
        "voice_backend": None,
        "voice_device": None,
        "voice_host_api": None,
        "voice_verbosity": None,
    }


def test_non_loopback_host_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.ai_sidecar import server as srv

    monkeypatch.delenv("AC_COPILOT_SIDECAR_TOKEN", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        ["ai_sidecar", "--host", "0.0.0.0", "--port", "0"],
    )
    with pytest.raises(SystemExit):
        srv.main()


def test_upgrade_rejected_without_token() -> None:
    token_check = make_token_check("s3cret")
    assert token_check is not None

    class _Conn:
        remote_address = ("192.168.1.50", 12345)

    class _Req:
        headers = {}

    response = token_check(_Conn(), _Req())
    assert response is not None
    if isinstance(response, tuple):
        assert response[0] == 401
    else:
        assert response.status_code == 401


def test_upgrade_accepted_with_token() -> None:
    async def _run() -> dict:
        async with _running_sidecar(token="s3cret") as port:
            async with ws_connect(
                f"ws://127.0.0.1:{port}/",
                additional_headers={
                    ep.AUTH_HEADER: "s3cret",
                    ep.CLIENT_HEADER: "test-client",
                },
            ) as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "test"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(raw)

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_HELLO_ACK
    assert "config.set" in ack["capabilities"]


def test_upgrade_accepted_with_token_for_non_loopback_peer() -> None:
    token_check = make_token_check("s3cret")
    assert token_check is not None

    class _Conn:
        remote_address = ("192.168.1.50", 12345)

    class _Req:
        headers = {
            ep.AUTH_HEADER: "s3cret",
            ep.CLIENT_HEADER: "test-client",
        }

    assert token_check(_Conn(), _Req()) is None


def test_upgrade_accepted_without_token_on_loopback() -> None:
    async def _run() -> dict:
        async with _running_sidecar(token="s3cret") as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "test"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(raw)

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_HELLO_ACK


def test_action_with_unknown_name_rejected() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "x"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(json.dumps({"v": 1, "type": "action", "name": "nukeFleet"}))
                err_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(err_raw)

    err = asyncio.run(_run())
    assert err["type"] == ep.TYPE_ERROR
    assert "unknown action" in err["message"]


def test_malformed_external_envelope_returns_error() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1}))
                err_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(err_raw)

    err = asyncio.run(_run())
    assert err["type"] == ep.TYPE_ERROR
    assert "requires non-empty string 'type'" in err["message"]


def test_external_peer_non_object_payload_returns_external_error() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "x"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send("[]")
                err_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(err_raw)

    err = asyncio.run(_run())
    assert err["v"] == ep.ENVELOPE_VERSION
    assert err["type"] == ep.TYPE_ERROR
    assert "root must be a JSON object" in err["message"]


def test_coaching_cue_subscribe_ok_without_loopback_lua_peer() -> None:
    async def _run() -> None:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "hello",
                            "client": "voice-client",
                            "client_class": ep.CLIENT_CLASS_VOICE,
                        }
                    )
                )
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "state.subscribe",
                            "topics": [ep.TOPIC_COACHING_CUE],
                        }
                    )
                )
                # Sidecar-only subscribe is a silent no-op: no ack and no error frame.
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(ws.recv(), timeout=2.0)

    asyncio.run(_run())


def test_external_request_errors_when_no_loopback_lua_peer() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "screen"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "config.set",
                            "key": "hudEnabled",
                            "value": False,
                        }
                    )
                )
                err_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(err_raw)

    err = asyncio.run(_run())
    assert err["type"] == ep.TYPE_ERROR
    assert "no loopback Lua peer connected" in err["message"]


def test_setup_experiment_record_and_suggest_roundtrip(tmp_path: Path) -> None:
    async def _run() -> dict:
        from tools.ai_sidecar import server as srv

        srv._setup_experiment_store_path = None
        lap_dir = tmp_path / "journal" / "laps"
        first = _write_setup_lap(lap_dir, "lap-a", "old", 100_000, 64)
        second = _write_setup_lap(lap_dir, "lap-b", "new", 98_000, 66)
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                for lap_path in (first, second):
                    await ws.send(
                        json.dumps(
                            {
                                "v": 1,
                                "type": "setup.experiment.record",
                                "archive_path": str(lap_path),
                            }
                        )
                    )
                    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                    assert ack["type"] == ep.TYPE_SETUP_EXPERIMENT_RECORD_ACK
                    assert ack["ok"] is True
                await ws.send(json.dumps({"v": 1, "type": "setup.suggest"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(raw)

    result = asyncio.run(_run())
    assert result["type"] == ep.TYPE_SETUP_SUGGEST_RESULT
    assert result["ok"] is True
    assert result["candidate"]["changed_params"]


def test_setup_experiment_store_registration_loads_rebuilt_rows(tmp_path: Path) -> None:
    async def _run() -> tuple[dict, dict]:
        from tools.ai_sidecar import server as srv

        srv._setup_experiment_store_path = None
        lap_dir = tmp_path / "journal" / "laps"
        _write_setup_lap(lap_dir, "lap-a", "old", 100_000, 64)
        _write_setup_lap(lap_dir, "lap-b", "new", 98_000, 66)
        rebuilt = rebuild_experiments(lap_dir)
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.experiment.store",
                            "store_path": rebuilt["store_path"],
                        }
                    )
                )
                store_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                await ws.send(json.dumps({"v": 1, "type": "setup.suggest"}))
                suggest = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                return store_ack, suggest

    store_ack, suggest = asyncio.run(_run())
    assert store_ack["type"] == ep.TYPE_SETUP_EXPERIMENT_STORE_ACK
    assert store_ack["ok"] is True
    assert store_ack["records"] == 2
    assert suggest["type"] == ep.TYPE_SETUP_SUGGEST_RESULT
    assert suggest["ok"] is True
    assert suggest["candidate"]["changed_params"]


def test_setup_store_registration_returns_error_when_count_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    def _boom(_store_path: Path) -> int:
        raise OSError("permission denied")

    monkeypatch.setattr(srv, "_setup_store_record_count", _boom)
    store = tmp_path / "journal" / "setup_experiments" / "experiments.jsonl"

    async def _run() -> dict:
        srv._setup_experiment_store_path = None
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.experiment.store",
                            "store_path": str(store),
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    try:
        result = asyncio.run(_run())
    finally:
        srv._setup_experiment_store_path = None

    assert result["type"] == ep.TYPE_SETUP_EXPERIMENT_STORE_ACK
    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_setup_record_returns_error_when_store_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    def _boom(_archive_path: str) -> dict:
        raise OSError("disk full")

    monkeypatch.setattr(srv, "_record_lap_archive_safe", _boom)
    lap_path = tmp_path / "journal" / "laps" / "lap_20260616-000001_lap-a.json"

    async def _run() -> dict:
        srv._setup_experiment_store_path = None
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.experiment.record",
                            "archive_path": str(lap_path),
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    try:
        result = asyncio.run(_run())
    finally:
        srv._setup_experiment_store_path = None

    assert result["type"] == ep.TYPE_SETUP_EXPERIMENT_RECORD_ACK
    assert result["ok"] is False
    assert "disk full" in result["error"]


def test_setup_record_preserves_seeded_store_for_suggest(tmp_path: Path) -> None:
    from tools.ai_sidecar import server as srv

    seed_dir = tmp_path / "seed" / "journal" / "laps"
    _write_setup_lap(seed_dir, "seed-a", "old", 100_000, 64)
    _write_setup_lap(seed_dir, "seed-b", "new", 98_000, 66)
    seeded = rebuild_experiments(seed_dir)
    seeded_store = Path(seeded["store_path"])

    live_lap = _write_setup_lap(
        tmp_path / "live" / "journal" / "laps", "live-a", "live", 99_000, 65
    )

    async def _run() -> tuple[dict, dict]:
        async with _running_sidecar() as port:
            srv._setup_experiment_store_path = seeded_store
            srv._setup_experiment_store_seeded = True
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.experiment.record",
                            "archive_path": str(live_lap),
                        }
                    )
                )
                record_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                await ws.send(json.dumps({"v": 1, "type": "setup.suggest"}))
                suggest = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                return record_ack, suggest

    try:
        record_ack, suggest = asyncio.run(_run())
    finally:
        srv._setup_experiment_store_path = None
        srv._setup_experiment_store_seeded = False

    assert record_ack["type"] == ep.TYPE_SETUP_EXPERIMENT_RECORD_ACK
    assert record_ack["ok"] is True
    assert record_ack["active_store_path"] == str(seeded_store)
    assert record_ack["store_path"] != str(seeded_store)
    assert suggest["type"] == ep.TYPE_SETUP_SUGGEST_RESULT
    assert suggest["ok"] is True
    assert suggest["experiments_used"] == 2


def test_setup_compare_returns_error_when_store_load_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    def _boom(_store_path: Path, **_kwargs: object) -> dict:
        raise OSError("permission denied")

    monkeypatch.setattr(srv, "_compare_setup_store", _boom)

    async def _run() -> dict:
        srv._setup_experiment_store_path = (
            tmp_path / "journal" / "setup_experiments" / "experiments.jsonl"
        )
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.compare",
                            "baseline_setup": "old",
                            "candidate_setup": "new",
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    try:
        result = asyncio.run(_run())
    finally:
        srv._setup_experiment_store_path = None

    assert result["type"] == ep.TYPE_SETUP_COMPARE_RESULT
    assert result["ok"] is False
    assert "permission denied" in result["error"]


def test_config_set_round_trip_via_hub() -> None:
    """Two peers: A sends config.set, B receives it; B's ack reaches A."""

    async def _run() -> tuple[dict, dict]:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as a,
                ws_connect(f"ws://127.0.0.1:{port}/") as b,
            ):
                for s, name in [(a, "client-a"), (b, "client-b")]:
                    await s.send(json.dumps({"v": 1, "type": "hello", "client": name}))
                    await asyncio.wait_for(s.recv(), timeout=2.0)  # hello_ack

                await a.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "config.set",
                            "key": "hudEnabled",
                            "value": False,
                        }
                    )
                )
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(a.recv(), timeout=0.1)
                forwarded = json.loads(await asyncio.wait_for(b.recv(), timeout=2.0))

                await b.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "config.ack",
                            "key": "hudEnabled",
                            "applied": True,
                        }
                    )
                )
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(b.recv(), timeout=0.1)
                ack_back = json.loads(await asyncio.wait_for(a.recv(), timeout=2.0))
                return forwarded, ack_back

    forwarded, ack_back = asyncio.run(_run())
    assert forwarded["type"] == "config.set"
    assert forwarded["key"] == "hudEnabled"
    assert forwarded["value"] is False
    assert ack_back["type"] == "config.ack"
    assert ack_back["applied"] is True


def test_telemetry_tick_routes_to_physical_clients_and_generates_haptic_event() -> None:
    """Fixture telemetry from Lua reaches physical clients and derives a haptic event."""

    async def _hello(ws, client: str, client_class: str | None = None) -> dict:
        frame: dict[str, object] = {"v": 1, "type": "hello", "client": client}
        if client_class is not None:
            frame["client_class"] = client_class
        await ws.send(json.dumps(frame))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    async def _run() -> tuple[dict, dict, dict]:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as lua,
                ws_connect(f"ws://127.0.0.1:{port}/") as screen,
                ws_connect(f"ws://127.0.0.1:{port}/") as haptics,
            ):
                await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                await _hello(screen, "ac-copilot-screen-01")
                await _hello(haptics, "uno-haptics-01", ep.CLIENT_CLASS_HAPTICS)

                await lua.send(json.dumps(_telemetry_tick(), separators=(",", ":")))
                screen_frame = json.loads(await asyncio.wait_for(screen.recv(), timeout=2.0))
                haptics_first = json.loads(await asyncio.wait_for(haptics.recv(), timeout=2.0))
                haptics_second = json.loads(await asyncio.wait_for(haptics.recv(), timeout=2.0))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(lua.recv(), timeout=0.1)
                return screen_frame, haptics_first, haptics_second

    screen_frame, haptics_first, haptics_second = asyncio.run(_run())
    assert screen_frame["type"] == ep.TYPE_TELEMETRY_TICK
    assert screen_frame["payload"]["speed_kmh"] == 112.0
    assert haptics_first["type"] == ep.TYPE_TELEMETRY_TICK
    assert haptics_second["type"] == ep.TYPE_HAPTIC_EVENT
    assert haptics_second["event"] == "pedal_rumble"
    assert haptics_second["channel"] == "pedal"
    assert haptics_second["intensity"] == pytest.approx(0.84)
    assert ep.validate_inbound(haptics_second) is None


def test_telemetry_tick_without_ts_sim_still_generates_haptic_event() -> None:
    """Derived haptic events omit absent timestamps instead of failing validation."""

    async def _hello(ws, client: str, client_class: str) -> None:
        await ws.send(
            json.dumps({"v": 1, "type": "hello", "client": client, "client_class": client_class})
        )
        await asyncio.wait_for(ws.recv(), timeout=2.0)

    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as lua,
                ws_connect(f"ws://127.0.0.1:{port}/") as haptics,
            ):
                await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                await _hello(haptics, "uno-haptics-01", ep.CLIENT_CLASS_HAPTICS)
                frame = _telemetry_tick(abs_active=False, brake=0.0, slip=-0.35)
                frame.pop("ts_sim")

                await lua.send(json.dumps(frame, separators=(",", ":")))
                haptics_first = json.loads(await asyncio.wait_for(haptics.recv(), timeout=2.0))
                haptics_second = json.loads(await asyncio.wait_for(haptics.recv(), timeout=2.0))
                assert haptics_first["type"] == ep.TYPE_TELEMETRY_TICK
                return haptics_second

    event = asyncio.run(_run())
    assert event["type"] == ep.TYPE_HAPTIC_EVENT
    assert event["event"] == "slip_buzz"
    assert event["intensity"] == pytest.approx(0.35)
    assert "ts_sim" not in event
    assert ep.validate_inbound(event) is None


def test_haptic_event_routes_only_to_haptics_class_clients() -> None:
    async def _hello(ws, client: str, client_class: str) -> None:
        await ws.send(
            json.dumps({"v": 1, "type": "hello", "client": client, "client_class": client_class})
        )
        await asyncio.wait_for(ws.recv(), timeout=2.0)

    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as lua,
                ws_connect(f"ws://127.0.0.1:{port}/") as screen,
                ws_connect(f"ws://127.0.0.1:{port}/") as haptics,
            ):
                await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                await _hello(screen, "screen-01", ep.CLIENT_CLASS_SCREEN)
                await _hello(haptics, "uno-haptics-01", ep.CLIENT_CLASS_HAPTICS)
                await lua.send(json.dumps(_haptic_event(), separators=(",", ":")))
                routed = json.loads(await asyncio.wait_for(haptics.recv(), timeout=2.0))
                for ws in (lua, screen):
                    with pytest.raises(asyncio.TimeoutError):
                        await asyncio.wait_for(ws.recv(), timeout=0.1)
                return routed

    routed = asyncio.run(_run())
    assert routed["type"] == ep.TYPE_HAPTIC_EVENT
    assert routed["event"] == "pedal_rumble"


def test_telemetry_tick_with_no_physical_client_is_noop_not_lua_echo() -> None:
    async def _run() -> None:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as lua:
                await lua.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "hello",
                            "client": "trainer-lua",
                            "client_class": ep.CLIENT_CLASS_LUA,
                        }
                    )
                )
                await asyncio.wait_for(lua.recv(), timeout=2.0)
                await lua.send(json.dumps(_telemetry_tick(), separators=(",", ":")))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(lua.recv(), timeout=0.1)

    asyncio.run(_run())


def test_peripheral_rate_limiter_blocks_until_interval_elapsed() -> None:
    now = [100.0]
    limiter = _RateLimiter(clock=lambda: now[0])
    assert limiter.allow(("telemetry_tick",), max_hz=20.0)
    assert not limiter.allow(("telemetry_tick",), max_hz=20.0)
    now[0] += 0.049
    assert not limiter.allow(("telemetry_tick",), max_hz=20.0)
    now[0] += 0.001
    assert limiter.allow(("telemetry_tick",), max_hz=20.0)
