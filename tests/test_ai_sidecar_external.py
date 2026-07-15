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
import os
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
    _handle_external_frame,
    _handle_setup_experiment_frame,
    _handler,
    _is_loopback,
    _RateLimiter,
    _reset_external_state,
    make_token_check,
)
from tools.ai_sidecar.setup_optimizer import rebuild_experiments  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_rig_ac_copilot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the operator's rig ``AC_COPILOT_*`` env vars so tests assert against code
    defaults, not the local machine.

    Without this, a configured rig (e.g. ``AC_COPILOT_SIDECAR_SERIAL_PORT=COM6`` from
    #463) leaks into the sidecar's parsed defaults and reds otherwise-green tests
    (issue #481). A test that needs a specific var still sets it via
    ``monkeypatch.setenv``, which runs after this clear and therefore overrides it.
    """
    for key in list(os.environ):
        if key.upper().startswith("AC_COPILOT_"):
            monkeypatch.delenv(key, raising=False)


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
    *,
    car_id: str = "ks_porsche_911_gt3_r_2016",
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
                "car": {"id": car_id},
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
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.advice",
                "complaint": "loose on exit",
                "setup_snapshot": {"FRONT_BIAS.VALUE": "66"},
            }
        )
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.diff",
                "baseline_snapshot": {"FRONT_BIAS.VALUE": "66"},
                "candidate_snapshot": {"FRONT_BIAS.VALUE": "64"},
            }
        )
        is None
    )
    assert ep.validate_inbound({"v": 1, "type": "setup.closed_loop", "param": "FRONT_BIAS"}) is None
    assert ep.validate_inbound({"v": 1, "type": "se.search", "limit": 10}) is None
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "session.review.generate",
                "lap_dir": "journal/laps",
                "session": "sess",
                "reference_source": "track-titan",
                "reference_file": "lap_tt.json",
            }
        )
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "se.download",
                "setup_id": 42,
                "car_id": "ks_porsche_911_gt3_r_2016",
                "track_id": "magione",
            }
        )
        is None
    )
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
    # #531 Part D live vitals + the TC/ABS intervention flags the dashboard flashes on.
    assert ep.validate_inbound(_telemetry_tick(tc_active=True, abs_active=False)) is None
    assert (
        ep.validate_inbound(
            _telemetry_tick(
                tyre_pressures_psi={"fl": 27.4, "fr": 27.6, "rl": 26.1, "rr": 26.3},
                brake_temps_c={"fl": 310.0, "fr": 312.0, "rl": 280.0, "rr": 282.0},
                tyre_wear_pct={"fl": 0.0, "fr": 25.0, "rl": 75.0, "rr": 100.0},
            )
        )
        is None
    )
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
    assert "complaint" in (ep.validate_inbound({"v": 1, "type": "setup.advice"}) or "")
    advice_snapshot_error = ep.validate_inbound(
        {"v": 1, "type": "setup.advice", "complaint": "loose"}
    )
    assert advice_snapshot_error == "setup.advice requires object 'setup_snapshot'"
    assert "complaint must be <=" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.advice",
                "complaint": "x" * (ep.MAX_SETUP_ADVICE_COMPLAINT_LEN + 1),
                "setup_snapshot": {"FRONT_BIAS.VALUE": "66"},
            }
        )
        or ""
    )
    diff_snapshot_error = ep.validate_inbound({"v": 1, "type": "setup.diff"})
    assert diff_snapshot_error == "setup.diff requires object 'baseline_snapshot'"
    assert "param" in (ep.validate_inbound({"v": 1, "type": "setup.closed_loop"}) or "")
    assert "entries" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.advice",
                "complaint": "loose",
                "setup_snapshot": {
                    f"PARAM_{idx}.VALUE": idx for idx in range(ep.MAX_SETUP_SNAPSHOT_KEYS + 1)
                },
            }
        )
        or ""
    )
    assert "bytes" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.diff",
                "baseline_snapshot": {"FRONT_BIAS.VALUE": "66"},
                "candidate_snapshot": {"ABOUT.NOTES": "x" * (ep.MAX_SETUP_SNAPSHOT_BYTES + 1)},
            }
        )
        or ""
    )
    assert "JSON-serializable" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "setup.advice",
                "complaint": "loose",
                "setup_snapshot": {"ABOUT.NOTES": "\ud800"},
            }
        )
        or ""
    )
    assert "limit must be <= 40" in (
        ep.validate_inbound({"v": 1, "type": "se.search", "limit": 80}) or ""
    )
    assert "lap_dir" in (ep.validate_inbound({"v": 1, "type": "session.review.generate"}) or "")
    assert "output_dir" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "session.review.generate",
                "lap_dir": "journal/laps",
                "output_dir": "journal/reports",
            }
        )
        or ""
    )
    assert "reference_source" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "session.review.generate",
                "lap_dir": "journal/laps",
                "reference_source": "aliens",
            }
        )
        or ""
    )
    assert "reference_file" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "session.review.generate",
                "lap_dir": "journal/laps",
                "reference_file": "../lap_tt.json",
            }
        )
        or ""
    )
    assert "positive integer 'setup_id'" in (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "se.download",
                "setup_id": "42",
                "car_id": "ks_porsche_911_gt3_r_2016",
            }
        )
        or ""
    )
    assert "non-empty 'car_id'" in (
        ep.validate_inbound({"v": 1, "type": "se.download", "setup_id": 42}) or ""
    )
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
    assert "tc_active must be a boolean" in (
        ep.validate_inbound(_telemetry_tick(tc_active="on")) or ""
    )
    assert "tyre_pressures_psi.rr requires a finite number" in (
        ep.validate_inbound(_telemetry_tick(tyre_pressures_psi={"rr": None})) or ""
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
        host: str,
        port: int,
        reply: bool,
        token: str | None,
        setup_store: str | None,
        setup_exchange_endpoint: str | None,
        user_setups_root: str | None,
        serial_port: str | None,
        serial_baud: int,
    ):
        seen.update(
            {
                "host": host,
                "port": port,
                "reply": reply,
                "token": token,
                "setup_store": setup_store,
                "setup_exchange_endpoint": setup_exchange_endpoint,
                "user_setups_root": user_setups_root,
                "serial_port": serial_port,
                "serial_baud": serial_baud,
            }
        )

    monkeypatch.setenv("AC_COPILOT_SIDECAR_TOKEN", "env-token")
    monkeypatch.setattr(srv, "_run", fake_run)

    def fake_wire_voice(config: srv.VoiceRuntimeConfig) -> None:
        del config

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
        "setup_exchange_endpoint": None,
        "user_setups_root": None,
        "serial_port": None,
        "serial_baud": 115200,
    }


def test_main_wires_voice_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Content Manager autostart inherits voice env without fragile batch quoting."""
    from tools.ai_sidecar import server as srv

    seen: dict[str, object] = {}

    async def fake_run(
        host: str,
        port: int,
        reply: bool,
        token: str | None,
        setup_store: str | None,
        setup_exchange_endpoint: str | None,
        user_setups_root: str | None,
        serial_port: str | None,
        serial_baud: int,
    ):
        del host, port, reply, token, setup_store, setup_exchange_endpoint, user_setups_root
        del serial_port, serial_baud

    def fake_wire_voice(config: srv.VoiceRuntimeConfig) -> None:
        seen["ref_path"] = config.reference_path
        seen["bank_dir"] = config.bank_dir
        seen["tts_enabled"] = config.tts_enabled
        seen["tts_rate"] = config.tts_rate
        seen["tts_volume"] = config.tts_volume
        seen["voice_backend"] = config.backend
        seen["voice_device"] = config.device
        seen["voice_host_api"] = config.host_api
        seen["voice_verbosity"] = config.verbosity

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


def test_remote_hello_hides_loopback_only_capabilities() -> None:
    class _RemoteWebsocket:
        remote_address = ("192.168.1.50", 49152)

        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

    async def _run() -> dict[str, object]:
        _reset_external_state()
        ws = _RemoteWebsocket()
        await _handle_external_frame(
            ws,
            {
                "v": 1,
                "type": "hello",
                "client": "screen",
                "client_class": ep.CLIENT_CLASS_SCREEN,
            },
        )
        return ws.sent[0]

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_HELLO_ACK
    assert ep.TYPE_SETUP_DIFF in ack["capabilities"]
    assert ep.TYPE_SETUP_CLOSED_LOOP not in ack["capabilities"]


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


def test_external_validation_exception_returns_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    class _Websocket:
        remote_address = ("127.0.0.1", 49152)

        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

    def _boom(_data: dict[str, object]) -> str | None:
        raise RecursionError("deep snapshot")

    async def _run() -> dict[str, object]:
        ws = _Websocket()
        monkeypatch.setattr(srv, "validate_inbound", _boom)
        await srv._handle_external_frame(
            ws,
            {"v": 1, "type": ep.TYPE_SETUP_ADVICE, "complaint": "loose"},
        )
        return ws.sent[0]

    err = asyncio.run(_run())
    assert err["type"] == ep.TYPE_ERROR
    assert "invalid frame: RecursionError" in str(err["message"])


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


def test_setup_exchange_search_and_download_are_sidecar_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    class _FakeSetupExchangeClient:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint

        def search(self, **_kwargs: object) -> dict[str, object]:
            return {
                "ok": True,
                "endpoint": self.endpoint,
                "setups": [{"setup_id": 42, "name": "Fast race", "downloads": 7}],
                "count": 1,
                "total": 1,
            }

        def download_setup(self, setup_id: int) -> dict[str, object]:
            return {"setup_id": setup_id, "name": "Fast race", "data": "[HEADER]\nVERSION=1"}

    monkeypatch.setattr(srv, "SetupExchangeClient", _FakeSetupExchangeClient)
    srv._setup_exchange_endpoint = "https://se.example.test"
    srv._setup_exchange_user_setups_root = tmp_path / "Documents" / "Assetto Corsa" / "setups"

    async def _run() -> tuple[dict, dict]:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "hello",
                            "client": "screen",
                            "client_class": ep.CLIENT_CLASS_SCREEN,
                        }
                    )
                )
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "se.search",
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                        }
                    )
                )
                search = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "se.download",
                            "setup_id": 42,
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                            "name": "Fast race",
                        }
                    )
                )
                download = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                return search, download

    try:
        search, download = asyncio.run(_run())
    finally:
        srv._setup_exchange_endpoint = None
        srv._setup_exchange_user_setups_root = None

    assert search["type"] == ep.TYPE_SETUP_EXCHANGE_SEARCH_RESULT
    assert search["ok"] is True
    assert search["setups"][0]["setup_id"] == 42
    assert download["type"] == ep.TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK
    assert download["ok"] is True
    assert Path(download["path"]).read_text(encoding="utf-8") == "[HEADER]\nVERSION=1\n"


def test_setup_exchange_download_oserror_returns_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    class _FakeSetupExchangeClient:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint

    def fail_install(**_kwargs: object) -> dict[str, object]:
        raise PermissionError("permission denied")

    monkeypatch.setattr(srv, "SetupExchangeClient", _FakeSetupExchangeClient)
    monkeypatch.setattr(srv, "download_and_install_setup", fail_install)
    srv._setup_exchange_endpoint = "https://se.example.test"
    srv._setup_exchange_user_setups_root = tmp_path / "Documents" / "Assetto Corsa" / "setups"

    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "hello",
                            "client": "screen",
                            "client_class": ep.CLIENT_CLASS_SCREEN,
                        }
                    )
                )
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "se.download",
                            "setup_id": 42,
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                            "name": "Fast race",
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    try:
        ack = asyncio.run(_run())
    finally:
        srv._setup_exchange_endpoint = None
        srv._setup_exchange_user_setups_root = None

    assert ack["type"] == ep.TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK
    assert ack["ok"] is False
    assert ack["setup_id"] == 42
    assert "failed to install setup" in ack["error"]
    assert "permission denied" in ack["error"]


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


def test_setup_advice_and_diff_roundtrip() -> None:
    async def _run() -> tuple[dict, dict]:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.advice",
                            "complaint": "car is loose on exit",
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                            "setup_snapshot": {
                                "FRONT_BIAS.VALUE": "66",
                                "TRACTION_CONTROL.VALUE": "3",
                                "DIFF_POWER.VALUE": "40",
                            },
                        }
                    )
                )
                advice = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.diff",
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                            "baseline_snapshot": {
                                "FRONT_BIAS.VALUE": "66",
                                "TRACTION_CONTROL.VALUE": "3",
                            },
                            "candidate_snapshot": {
                                "FRONT_BIAS.VALUE": "64",
                                "TRACTION_CONTROL.VALUE": "4",
                            },
                        }
                    )
                )
                diff = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                return advice, diff

    advice, diff = asyncio.run(_run())
    assert advice["type"] == ep.TYPE_SETUP_ADVICE_RESULT
    assert advice["ok"] is True
    assert advice["suggestions"][0]["section"] == "TRACTION_CONTROL"
    assert advice["suggestions"][0]["target"] == 4.0
    assert diff["type"] == ep.TYPE_SETUP_DIFF_RESULT
    assert diff["ok"] is True
    assert diff["changed_count"] == 2
    assert any("Brake bias" in line for line in diff["display_lines"])


def test_setup_diff_roundtrip_uses_snapshot_car_model_for_schema() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.diff",
                            "baseline_snapshot": {
                                "CAR.MODEL": "ks_porsche_911_gt3_r_2016",
                                "CAMBER_LF.VALUE": "-18",
                            },
                            "candidate_snapshot": {
                                "CAR.MODEL": "ks_porsche_911_gt3_r_2016",
                                "CAMBER_LF.VALUE": "-19",
                            },
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    diff = asyncio.run(_run())
    assert diff["type"] == ep.TYPE_SETUP_DIFF_RESULT
    assert diff["ok"] is True
    row = diff["rows"][0]
    assert row["units"] == "deg"
    assert row["from_display"] == "-1.8"
    assert row["to_display"] == "-1.9"


def test_setup_diff_roundtrip_preserves_snapshot_car_mismatch() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.diff",
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "baseline_snapshot": {
                                "CAR.MODEL": "ks_porsche_911_gt3_r_2016",
                                "FRONT_BIAS.VALUE": "66",
                            },
                            "candidate_snapshot": {
                                "CAR.MODEL": "bmw_z4_gt3",
                                "FRONT_BIAS.VALUE": "64",
                            },
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    diff = asyncio.run(_run())
    assert diff["type"] == ep.TYPE_SETUP_DIFF_RESULT
    assert diff["ok"] is False
    assert diff["status"] == "car_mismatch"
    assert diff["baseline"]["car_id"] == "ks_porsche_911_gt3_r_2016"
    assert diff["candidate"]["car_id"] == "bmw_z4_gt3"


def test_setup_advice_roundtrip_uses_snapshot_car_model_for_schema() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.advice",
                            "complaint": "rear locks on entry",
                            "setup_snapshot": {
                                "CAR.MODEL": "ks_porsche_911_gt3_r_2016",
                                "FRONT_BIAS.VALUE": "70",
                                "BRAKE_POWER_MULT.VALUE": "100",
                                "ABS.VALUE": "7",
                            },
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    advice = asyncio.run(_run())
    assert advice["type"] == ep.TYPE_SETUP_ADVICE_RESULT
    assert advice["ok"] is True
    assert all(suggestion["section"] != "FRONT_BIAS" for suggestion in advice["suggestions"])
    assert advice["suggestions"][0]["section"] == "BRAKE_POWER_MULT"


def test_setup_closed_loop_roundtrip(tmp_path: Path) -> None:
    async def _run() -> dict:
        from tools.ai_sidecar import server as srv

        srv._setup_experiment_store_path = None
        lap_dir = tmp_path / "journal" / "laps"
        first = _write_setup_lap(lap_dir, "lap-a", "old", 100_000, 64)
        second = _write_setup_lap(lap_dir, "lap-b", "new", 98_000, 65)
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
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.closed_loop",
                            "param": "FRONT_BIAS",
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    result = asyncio.run(_run())
    assert result["type"] == ep.TYPE_SETUP_CLOSED_LOOP_RESULT
    assert result["ok"] is True
    assert result["method"] == "one_param_measured_delta"
    assert result["previous_result"]["measured_delta_ms"] == 2000.0
    assert result["candidate"]["changed_params"]["FRONT_BIAS.VALUE"] == {
        "from": 65.0,
        "to": 66.0,
    }


def test_setup_closed_loop_roundtrip_uses_car_schema_bounds(tmp_path: Path) -> None:
    async def _run() -> dict:
        from tools.ai_sidecar import server as srv

        srv._setup_experiment_store_path = None
        lap_dir = tmp_path / "journal" / "laps"
        first = _write_setup_lap(lap_dir, "lap-a", "old", 100_000, 69)
        second = _write_setup_lap(lap_dir, "lap-b", "new", 98_000, 70)
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
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.closed_loop",
                            "param": "FRONT_BIAS",
                            "car_id": "ks_porsche_911_gt3_r_2016",
                            "track_id": "magione",
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    result = asyncio.run(_run())
    assert result["type"] == ep.TYPE_SETUP_CLOSED_LOOP_RESULT
    assert result["ok"] is False
    assert result["status"] == "at_param_bound"
    assert result["current"] == 70.0


def test_setup_closed_loop_roundtrip_infers_schema_from_records(tmp_path: Path) -> None:
    async def _run() -> dict:
        from tools.ai_sidecar import server as srv

        srv._setup_experiment_store_path = None
        lap_dir = tmp_path / "journal" / "laps"
        first = _write_setup_lap(lap_dir, "lap-a", "old", 100_000, 69)
        second = _write_setup_lap(lap_dir, "lap-b", "new", 98_000, 70)
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
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.closed_loop",
                            "param": "FRONT_BIAS",
                            "track_id": "magione",
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    result = asyncio.run(_run())
    assert result["type"] == ep.TYPE_SETUP_CLOSED_LOOP_RESULT
    assert result["ok"] is False
    assert result["status"] == "at_param_bound"
    assert result["current"] == 70.0


def test_setup_closed_loop_roundtrip_ignores_unknown_car_sentinel_for_schema(
    tmp_path: Path,
) -> None:
    async def _run() -> dict:
        from tools.ai_sidecar import server as srv

        srv._setup_experiment_store_path = None
        lap_dir = tmp_path / "journal" / "laps"
        unknown = _write_setup_lap(
            lap_dir,
            "lap-u",
            "unknown",
            101_000,
            68,
            car_id="unknown",
        )
        first = _write_setup_lap(lap_dir, "lap-a", "old", 100_000, 69)
        second = _write_setup_lap(lap_dir, "lap-b", "new", 98_000, 70)
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "lua"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                for lap_path in (unknown, first, second):
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
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "setup.closed_loop",
                            "param": "FRONT_BIAS",
                            "track_id": "magione",
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    result = asyncio.run(_run())
    assert result["type"] == ep.TYPE_SETUP_CLOSED_LOOP_RESULT
    assert result["ok"] is False
    assert result["status"] == "at_param_bound"
    assert result["current"] == 70.0


def test_setup_closed_loop_rejects_non_loopback_peer() -> None:
    class _RemoteWebsocket:
        remote_address = ("192.168.1.50", 49152)

        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

    async def _run() -> dict[str, object]:
        ws = _RemoteWebsocket()
        await _handle_setup_experiment_frame(
            ws,
            {
                "type": ep.TYPE_SETUP_CLOSED_LOOP,
                "param": "FRONT_BIAS",
            },
        )
        return ws.sent[0]

    result = asyncio.run(_run())
    assert result["type"] == ep.TYPE_SETUP_CLOSED_LOOP_RESULT
    assert result["ok"] is False
    assert "loopback-only" in str(result["error"])


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


def test_session_review_generate_publishes_result_snapshot_and_voice_cue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    class _FakeVoiceCoach:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def subscribe(self, advisory: object) -> None:
            self.messages.append(str(advisory.message))

    voice = _FakeVoiceCoach()
    calls: list[dict[str, object]] = []

    def _fake_generate(
        lap_dir: str,
        *,
        session: str,
        driver_id: str,
        output_dir: str | None = None,
        reference_source: str = "auto",
        reference_file: str | None = None,
    ) -> dict[str, object]:
        calls.append(
            {
                "lap_dir": lap_dir,
                "session": session,
                "driver_id": driver_id,
                "output_dir": output_dir,
                "reference_source": reference_source,
                "reference_file": reference_file,
            }
        )
        report_dir = tmp_path / "journal" / "reports"
        return {
            "ok": True,
            "markdown_path": str(report_dir / "session_sess.md"),
            "json_path": str(report_dir / "session_sess.json"),
            "html_path": str(report_dir / "session_sess.html"),
            "session_uuid": "sess",
            "car_id": "ks_porsche_911_gt3_r_2016",
            "track_id": "magione",
            "best_lap_ms": 98_000,
            "spoken_summary": "Session debrief for Magione: focus T1.",
            "screen_summary": ["T1: 0.74s - technique"],
            "problems": [],
            "next_session_prep": [],
            "reference": {"source_file": "lap_tt.json", "kind": "tt", "lap_ms": 97_000},
            "reference_selection": {
                "requested_source": "tt",
                "active": True,
                "active_source": "tt",
                "source_file": "lap_tt.json",
                "reason": "fastest valid same car/track tt reference",
            },
            "source": {"lap_dirs": [lap_dir]},
        }

    monkeypatch.setattr(srv, "_generate_session_review_safe", _fake_generate)
    srv.set_voice_coach(voice)
    lap_dir = tmp_path / "journal" / "laps"

    async def _hello(ws, client: str, client_class: str) -> None:
        await ws.send(
            json.dumps({"v": 1, "type": "hello", "client": client, "client_class": client_class})
        )
        await asyncio.wait_for(ws.recv(), timeout=2.0)

    async def _run() -> tuple[dict, list[dict], dict]:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as lua,
                ws_connect(f"ws://127.0.0.1:{port}/") as screen,
            ):
                await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                await _hello(screen, "screen-01", ep.CLIENT_CLASS_SCREEN)

                await lua.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": ep.TYPE_SESSION_REVIEW_GENERATE,
                            "lap_dir": str(lap_dir),
                            "session": "sess",
                            "reference_source": "tt",
                            "reference_file": "lap_tt.json",
                        }
                    )
                )
                ack = json.loads(await asyncio.wait_for(lua.recv(), timeout=2.0))
                frames = [
                    json.loads(await asyncio.wait_for(screen.recv(), timeout=2.0)),
                    json.loads(await asyncio.wait_for(screen.recv(), timeout=2.0)),
                ]
                async with ws_connect(f"ws://127.0.0.1:{port}/") as late_screen:
                    await _hello(late_screen, "screen-02", ep.CLIENT_CLASS_SCREEN)
                    await late_screen.send(
                        json.dumps(
                            {
                                "v": 1,
                                "type": "state.subscribe",
                                "topics": [ep.TOPIC_SESSION_REVIEW],
                            }
                        )
                    )
                    cached = json.loads(await asyncio.wait_for(late_screen.recv(), timeout=2.0))
                return ack, frames, cached

    try:
        ack, frames, cached = asyncio.run(_run())
    finally:
        srv.set_voice_coach(None)

    assert calls == [
        {
            "lap_dir": str(lap_dir),
            "session": "sess",
            "driver_id": "local-driver",
            "output_dir": None,
            "reference_source": "tt",
            "reference_file": "lap_tt.json",
        }
    ]
    assert ack["type"] == ep.TYPE_SESSION_REVIEW_RESULT
    assert ack["ok"] is True
    assert ack["markdown_path"].endswith("session_sess.md")
    assert ack["html_path"].endswith("session_sess.html")
    assert ack["reference"]["kind"] == "tt"
    assert ack["reference_selection"]["requested_source"] == "tt"
    review = next(frame for frame in frames if frame.get("topic") == ep.TOPIC_SESSION_REVIEW)
    cue = next(frame for frame in frames if frame.get("topic") == ep.TOPIC_COACHING_CUE)
    assert review["type"] == ep.TYPE_STATE_SNAPSHOT
    assert review["payload"]["session_uuid"] == "sess"
    assert "markdown_path" not in review["payload"]
    assert "json_path" not in review["payload"]
    assert "html_path" not in review["payload"]
    assert review["payload"]["markdown_file"] == "session_sess.md"
    assert review["payload"]["json_file"] == "session_sess.json"
    assert review["payload"]["html_file"] == "session_sess.html"
    assert review["payload"]["reference"]["kind"] == "tt"
    assert review["payload"]["reference_selection"]["active_source"] == "tt"
    assert cue["payload"]["kind"] == "session_review"
    assert cue["payload"]["message"] == "Session debrief for Magione: focus T1."
    assert "markdown_path" not in cue["payload"]["detail"]
    assert "json_path" not in cue["payload"]["detail"]
    assert "html_path" not in cue["payload"]["detail"]
    assert cue["payload"]["detail"]["markdown_file"] == "session_sess.md"
    assert cue["payload"]["detail"]["json_file"] == "session_sess.json"
    assert cue["payload"]["detail"]["html_file"] == "session_sess.html"
    assert cue["payload"]["detail"]["reference"]["kind"] == "tt"
    assert cue["payload"]["detail"]["reference_selection"]["active_source"] == "tt"
    assert cached == review
    assert voice.messages == ["Session debrief for Magione: focus T1."]


def test_session_review_generate_rejects_non_journal_laps_dir(tmp_path: Path) -> None:
    async def _run() -> dict:
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
                await lua.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": ep.TYPE_SESSION_REVIEW_GENERATE,
                            "lap_dir": str(tmp_path / "laps"),
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(lua.recv(), timeout=2.0))

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_SESSION_REVIEW_RESULT
    assert ack["ok"] is False
    assert "journal/laps" in ack["error"]


def test_failed_session_review_replaces_cached_snapshot_with_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    mode = ["ok"]

    def _fake_generate(
        lap_dir: str,
        *,
        session: str,
        driver_id: str,
        output_dir: str | None = None,
        reference_source: str = "auto",
        reference_file: str | None = None,
    ) -> dict[str, object]:
        del driver_id, output_dir, reference_source, reference_file
        if mode[0] == "fail":
            raise ValueError("session has no valid timed laps")
        report_dir = tmp_path / "journal" / "reports"
        return {
            "ok": True,
            "markdown_path": str(report_dir / "session_good.md"),
            "json_path": str(report_dir / "session_good.json"),
            "html_path": str(report_dir / "session_good.html"),
            "session_uuid": session,
            "car_id": "ks_porsche_911_gt3_r_2016",
            "track_id": "magione",
            "best_lap_ms": 98_000,
            "spoken_summary": "Session debrief: focus T1.",
            "screen_summary": ["T1: 0.74s - technique"],
            "problems": [],
            "next_session_prep": [],
            "source": {"lap_dirs": [lap_dir]},
        }

    monkeypatch.setattr(srv, "_generate_session_review_safe", _fake_generate)

    async def _hello(ws, client: str, client_class: str) -> None:
        await ws.send(
            json.dumps({"v": 1, "type": "hello", "client": client, "client_class": client_class})
        )
        await asyncio.wait_for(ws.recv(), timeout=2.0)

    async def _generate(lua, session: str) -> dict:
        await lua.send(
            json.dumps(
                {
                    "v": 1,
                    "type": ep.TYPE_SESSION_REVIEW_GENERATE,
                    "lap_dir": str(tmp_path / "journal" / "laps"),
                    "session": session,
                }
            )
        )
        return json.loads(await asyncio.wait_for(lua.recv(), timeout=2.0))

    async def _run() -> tuple[dict, dict, dict]:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as lua,
                ws_connect(f"ws://127.0.0.1:{port}/") as screen,
            ):
                await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                await _hello(screen, "screen-01", ep.CLIENT_CLASS_SCREEN)

                ok_ack = await _generate(lua, "sess-good")
                ok_snapshot = json.loads(await asyncio.wait_for(screen.recv(), timeout=2.0))
                json.loads(await asyncio.wait_for(screen.recv(), timeout=2.0))  # coaching.cue
                assert ok_ack["ok"] is True
                assert ok_snapshot["payload"]["ok"] is True

                mode[0] = "fail"
                fail_ack = await _generate(lua, "sess-empty")
                fail_snapshot = json.loads(await asyncio.wait_for(screen.recv(), timeout=2.0))

                async with ws_connect(f"ws://127.0.0.1:{port}/") as late_screen:
                    await _hello(late_screen, "screen-02", ep.CLIENT_CLASS_SCREEN)
                    await late_screen.send(
                        json.dumps(
                            {
                                "v": 1,
                                "type": "state.subscribe",
                                "topics": [ep.TOPIC_SESSION_REVIEW],
                            }
                        )
                    )
                    cached = json.loads(await asyncio.wait_for(late_screen.recv(), timeout=2.0))
                return fail_ack, fail_snapshot, cached

    fail_ack, fail_snapshot, cached = asyncio.run(_run())
    assert fail_ack["type"] == ep.TYPE_SESSION_REVIEW_RESULT
    assert fail_ack["ok"] is False
    assert "no valid timed laps" in fail_ack["error"]
    assert fail_snapshot["topic"] == ep.TOPIC_SESSION_REVIEW
    assert fail_snapshot["payload"]["ok"] is False
    assert fail_snapshot["payload"]["session_uuid"] == "sess-empty"
    assert "markdown_path" not in fail_snapshot["payload"]
    assert "html_path" not in fail_snapshot["payload"]
    assert cached == fail_snapshot


def test_session_review_generate_returns_structured_error_on_unexpected_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.ai_sidecar import server as srv

    def _boom(
        lap_dir: str,
        *,
        session: str,
        driver_id: str,
        output_dir: str | None = None,
        reference_source: str = "auto",
        reference_file: str | None = None,
    ) -> dict[str, object]:
        del lap_dir, session, driver_id, output_dir, reference_source, reference_file
        raise RuntimeError("analysis worker exploded")

    monkeypatch.setattr(srv, "_generate_session_review_safe", _boom)

    async def _run() -> dict:
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
                await lua.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": ep.TYPE_SESSION_REVIEW_GENERATE,
                            "lap_dir": str(tmp_path / "journal" / "laps"),
                        }
                    )
                )
                return json.loads(await asyncio.wait_for(lua.recv(), timeout=2.0))

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_SESSION_REVIEW_RESULT
    assert ack["ok"] is False
    assert "analysis worker exploded" in ack["error"]


def test_loopback_session_review_result_is_rejected_not_relayed() -> None:
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
            ):
                await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                await _hello(screen, "screen-01", ep.CLIENT_CLASS_SCREEN)
                await lua.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": ep.TYPE_SESSION_REVIEW_RESULT,
                            "ok": True,
                            "markdown_path": "C:/Users/driver/journal/reports/private.md",
                        }
                    )
                )
                err = json.loads(await asyncio.wait_for(lua.recv(), timeout=2.0))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(screen.recv(), timeout=0.1)
                return err

    err = asyncio.run(_run())
    assert err["type"] == ep.TYPE_ERROR
    assert "unknown type" in err["message"]


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
