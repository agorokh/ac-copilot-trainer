"""Tablet GT dashboard endpoint tests (issue #531 Phase 1 — Parts A/B/C-min).

Covers the /tablet/dash page route, the vendored-font allow-list routes (same
no-traversal discipline as the voice clip routes), the token gate parity, the
browser-class ``telemetry_tick`` routing (Part B), the ``rpm_max`` validator
extension (Part C-min), and the A133 perf contract encoded as page invariants
(no CDN, no box-shadow/filter/blur — the acceptance criteria of #531).
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

import pytest

from tools.ai_sidecar import external_protocol as ep
from tools.ai_sidecar import server
from tools.ai_sidecar.server import (
    _TABLET_DASH_FONT_FILES,
    _TABLET_DASH_FONTS_DIR,
    _TABLET_DASH_PAGE_PATH,
    _reset_external_state,
    make_process_request,
)


@pytest.fixture(autouse=True)
def _isolated_sidecar_state():
    _reset_external_state()
    yield
    _reset_external_state()


class _FakeHeaders(dict):
    def __delitem__(self, key):  # tolerate deleting a missing default header
        if key in self:
            dict.__delitem__(self, key)
        else:
            raise KeyError(key)


class _FakeResponse:
    def __init__(self, status: HTTPStatus, text: str) -> None:
        self.status = status
        self.headers = _FakeHeaders()
        self.body = text.encode("utf-8")


class _FakeConnection:
    def respond(self, status: HTTPStatus, text: str) -> _FakeResponse:
        return _FakeResponse(status, text)


class _FakeRequest:
    def __init__(self, path: str, headers: dict[str, str] | None = None) -> None:
        self.path = path
        self.headers: dict[str, str] = headers or {}


def _get(path: str, *, token: str | None = None, headers: dict[str, str] | None = None):
    handler = make_process_request(token)
    return handler(_FakeConnection(), _FakeRequest(path, headers))


# --------------------------------------------------------------------------------------------
# HTTP: page + fonts
# --------------------------------------------------------------------------------------------


def test_http_dash_page_served() -> None:
    resp = _get("/tablet/dash")
    assert resp.status == HTTPStatus.OK
    assert "text/html" in resp.headers.get("Content-Type", "")
    body = resp.body.decode("utf-8")
    assert "tablet-dash" in body  # hello client id
    assert '"browser"' in body  # client_class (Part B routing key)
    assert "setup.spinner.list" in body  # per-car electronics ranges request
    assert "telemetry_tick" in body


def test_dash_page_is_offline_kiosk_and_a133_safe() -> None:
    """#531 acceptance: fonts/framework vendored (no CDN) and the shipped CSS contains no
    box-shadow / CSS filter / backdrop-filter / mix-blend (A133 GPU budget)."""
    body = _TABLET_DASH_PAGE_PATH.read_text(encoding="utf-8")
    # The header comment documents these constraints (and so names the banned tokens);
    # the contract applies to shipped CSS/markup, so scan with comments stripped.
    lowered = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).lower()
    for banned in (
        # offline kiosk: no external resource loads (the loopback deployment URL in the
        # header comment is documentation, not a fetch)
        "fonts.googleapis",
        "fonts.gstatic",
        'src="http',
        "src='http",
        'href="http',
        "href='http",
        'url("http',
        "url('http",
        "url(http",
        "@import",
        # A133 GPU budget (#531 acceptance: perf on target)
        "box-shadow",
        "backdrop-filter",
        "mix-blend",
        "filter:",
        "webgl",
    ):
        assert banned not in lowered, f"forbidden token in shipped dash page: {banned!r}"
    # Every font the page references is served from the local allow-list.
    assert "/dash/fonts/" in body
    for name in _TABLET_DASH_FONT_FILES:
        assert (_TABLET_DASH_FONTS_DIR / name).is_file(), f"vendored font missing: {name}"


def test_dash_vendored_fonts_match_canonical_copies() -> None:
    """The dash fonts are vendored copies of the Racing Atelier faces shipped with the
    trainer content — byte-identical, so a token/face update cannot silently drift."""
    # fonts -> web -> dash -> ai_sidecar -> tools -> repo root
    repo_root = _TABLET_DASH_FONTS_DIR.parents[4]
    canonical = repo_root / "src" / "ac_copilot_trainer" / "content" / "fonts"
    assert canonical.is_dir(), canonical
    for name in _TABLET_DASH_FONT_FILES:
        vendored = (_TABLET_DASH_FONTS_DIR / name).read_bytes()
        source = (canonical / name).read_bytes()
        assert vendored == source, f"vendored font drifted from canonical: {name}"


def test_http_font_serving_is_allowlisted() -> None:
    name = sorted(_TABLET_DASH_FONT_FILES)[0]
    ok = _get(f"/dash/fonts/{name}")
    assert ok.status == HTTPStatus.OK
    assert ok.headers.get("Content-Type") == "font/ttf"
    assert ok.headers.get("Content-Length") == str(len(ok.body))
    assert len(ok.body) > 1000
    # Unknown / traversal names never resolve, including after percent-decoding.
    assert _get("/dash/fonts/Nope.ttf").status == HTTPStatus.NOT_FOUND
    assert _get("/dash/fonts/../web/tablet_dash.html").status == HTTPStatus.NOT_FOUND
    assert _get("/dash/fonts/..%2F..%2Fserver.py").status == HTTPStatus.NOT_FOUND


def test_http_dash_routes_token_gated_for_non_loopback() -> None:
    """Same trust model as /tablet/voice: with a token configured, non-loopback clients
    need X-AC-Copilot-Token; the USB adb-reverse loopback deployment passes untokened."""
    name = sorted(_TABLET_DASH_FONT_FILES)[0]
    assert _get("/tablet/dash", token="sekret").status == HTTPStatus.UNAUTHORIZED
    assert _get(f"/dash/fonts/{name}", token="sekret").status == HTTPStatus.UNAUTHORIZED
    ok = _get("/tablet/dash", token="sekret", headers={"X-AC-Copilot-Token": "sekret"})
    assert ok.status == HTTPStatus.OK
    assert _get("/tablet/dash").status == HTTPStatus.OK  # no token configured


# --------------------------------------------------------------------------------------------
# Protocol: routing classes + rpm_max (Part B / C-min)
# --------------------------------------------------------------------------------------------


def test_telemetry_tick_classes_include_browser_but_haptics_unchanged() -> None:
    assert ep.CLIENT_CLASS_BROWSER in ep.TELEMETRY_TICK_CLIENT_CLASSES
    assert ep.PHYSICAL_CLIENT_CLASSES <= ep.TELEMETRY_TICK_CLIENT_CLASSES
    assert ep.CLIENT_CLASS_BROWSER not in ep.HAPTIC_CLIENT_CLASSES
    assert ep.CLIENT_CLASS_VOICE not in ep.TELEMETRY_TICK_CLIENT_CLASSES


def _tick_frame(**payload_overrides) -> dict:
    payload = {
        "speed_kmh": 187.0,
        "rpm": 6789.0,
        "throttle": 0.4,
        "brake": 0.0,
        "steer": 0.1,
        "gear": 4,
        "lat_g": 0.2,
        "long_g": -0.1,
    }
    payload.update(payload_overrides)
    return {"v": 1, "type": ep.TYPE_TELEMETRY_TICK, "seq": 1, "payload": payload}


def test_validate_telemetry_tick_accepts_rpm_max_and_rejects_bad() -> None:
    assert ep.validate_inbound(_tick_frame(rpm_max=8500.0)) is None
    assert ep.validate_inbound(_tick_frame()) is None  # optional: absent stays valid
    err = ep.validate_inbound(_tick_frame(rpm_max=-1))
    assert err is not None and "rpm_max" in err
    err = ep.validate_inbound(_tick_frame(rpm_max="high"))
    assert err is not None and "rpm_max" in err


# --------------------------------------------------------------------------------------------
# WS routing: a browser-class peer receives telemetry_tick; a voice-class peer does not
# --------------------------------------------------------------------------------------------

websockets = pytest.importorskip("websockets")
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.asyncio.server import serve as ws_serve  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@asynccontextmanager
async def _running_sidecar() -> AsyncIterator[int]:
    port = _free_port()
    _reset_external_state()
    try:
        async with ws_serve(
            lambda ws: server._handler(ws, reply_coaching=False),
            "127.0.0.1",
            port,
        ):
            yield port
    finally:
        _reset_external_state()


async def _hello(ws, client: str, client_class: str) -> None:
    await ws.send(
        json.dumps({"v": 1, "type": "hello", "client": client, "client_class": client_class})
    )
    ack = json.loads(await ws.recv())
    assert ack["type"] == "hello_ack"


def test_ws_telemetry_tick_routed_to_browser_not_voice() -> None:
    async def _t() -> tuple[dict, bool]:
        async with _running_sidecar() as port:
            url = f"ws://127.0.0.1:{port}"
            async with (
                ws_connect(url) as lua,
                ws_connect(url) as dash,
                ws_connect(url) as voice,
            ):
                await _hello(lua, "trainer-lua", "lua")
                await _hello(dash, "tablet-dash", "browser")
                await _hello(voice, "tablet-voice", "voice")
                await lua.send(json.dumps(_tick_frame(rpm_max=8500.0)))
                got = json.loads(await asyncio.wait_for(dash.recv(), timeout=3.0))
                voice_got_frame = True
                try:
                    await asyncio.wait_for(voice.recv(), timeout=0.5)
                except TimeoutError:
                    voice_got_frame = False
                return got, voice_got_frame

    got, voice_got_frame = asyncio.run(_t())
    assert got["type"] == ep.TYPE_TELEMETRY_TICK
    assert got["payload"]["rpm_max"] == 8500.0
    assert not voice_got_frame


def test_ws_identity_snapshot_replayed_to_late_subscriber() -> None:
    """#531 Part B: `setup.active` is event-driven — a tablet that connects AFTER the driver
    loaded a setup must still learn the current setup name. The sidecar caches the latest
    identity snapshot and replays it on state.subscribe. Continuous streams are excluded."""

    async def _t() -> dict:
        async with _running_sidecar() as port:
            url = f"ws://127.0.0.1:{port}"
            async with ws_connect(url) as lua:
                await _hello(lua, "trainer-lua", "lua")
                await lua.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "state.snapshot",
                            "topic": "setup.active",
                            "payload": {"name": "enduro-long-run", "path": "x.ini"},
                        }
                    )
                )
                await asyncio.sleep(0.1)  # let the relay/caching settle
                async with ws_connect(url) as dash:
                    await _hello(dash, "tablet-dash", "browser")
                    await dash.send(
                        json.dumps(
                            {
                                "v": 1,
                                "type": "state.subscribe",
                                "topics": ["setup.active", "delta", "lap"],
                            }
                        )
                    )
                    frame = json.loads(await asyncio.wait_for(dash.recv(), timeout=3.0))
                    return frame

    frame = asyncio.run(_t())
    assert frame["type"] == "state.snapshot"
    assert frame["topic"] == "setup.active"
    assert frame["payload"]["name"] == "enduro-long-run"


def test_identity_replay_topics_exclude_continuous_streams() -> None:
    assert "setup.active" in ep.IDENTITY_REPLAY_TOPICS
    assert "session" in ep.IDENTITY_REPLAY_TOPICS
    for continuous in ("delta", "tire_temps", "coaching.snapshot", "lap"):
        assert continuous not in ep.IDENTITY_REPLAY_TOPICS
    assert ep.IDENTITY_REPLAY_TOPICS <= ep.KNOWN_TOPICS
