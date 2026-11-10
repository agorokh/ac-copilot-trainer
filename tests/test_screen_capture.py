"""Rig-screen framebuffer capture: protocol validation and PNG reassembly (#86)."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import zlib

import pytest

from tools.ai_sidecar import external_protocol as ep
from tools.screen_capture import CaptureError, assemble, rgb565_to_png


def chunk(offset, data, *, total, done, width=2, height=2, **extra):
    frame = {
        "v": 1,
        "type": "screen.capture.chunk",
        "capture_id": "cap-1",
        "width": width,
        "height": height,
        "format": "rgb565",
        "offset": offset,
        "total": total,
        "data": base64.b64encode(data).decode(),
        "done": done,
    }
    frame.update(extra)
    return frame


def test_capture_request_and_chunk_validate():
    assert ep.validate_inbound({"v": 1, "type": "screen.capture", "capture_id": "cap-1"}) is None
    assert ep.validate_inbound(chunk(0, b"\x00" * 8, total=8, done=True)) is None


@pytest.mark.parametrize(
    "frame",
    [
        {"v": 1, "type": "screen.capture"},
        {"v": 1, "type": "screen.capture", "capture_id": "bad id\n"},
        {"v": 1, "type": "screen.capture", "capture_id": "x" * 65},
        chunk(0, b"", total=8, done=True, capture_id=""),
        chunk(0, b"", total=0, done=True),
        chunk(9, b"", total=8, done=True),
        chunk(0, b"", total=8, done="yes"),
        chunk(0, b"", total=8, done=True, width=True),
        chunk(0, b"", total=8, done=True, height=4096),
        chunk(0, b"", total=ep.MAX_SCREEN_CAPTURE_BYTES + 1, done=True),
        {
            **chunk(0, b"", total=8, done=True),
            "data": "A" * (ep.MAX_SCREEN_CAPTURE_CHUNK_CHARS + 9),
        },
        chunk(0, b"", total=8, done=True, error="x" * 201),
    ],
)
def test_malformed_capture_frames_are_rejected(frame):
    assert ep.validate_inbound(frame) is not None


class _Peer:
    remote_address = ("127.0.0.1", 49152)

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def test_sidecar_routes_request_to_screens_and_chunks_back_to_requester_only():
    from tools.ai_sidecar import server as srv

    async def run():
        srv._reset_external_state()
        try:
            screen, tool, lua = _Peer(), _Peer(), _Peer()
            for peer, client, cls in (
                (screen, "ac-copilot-screen-01", ep.CLIENT_CLASS_SCREEN),
                (tool, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
                (lua, "browser", ep.CLIENT_CLASS_BROWSER),
            ):
                await srv._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": client, "client_class": cls}
                )
                peer.sent.clear()
            request = {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            await srv._handle_external_frame(tool, request)
            assert screen.sent == [request]
            assert tool.sent == [] and lua.sent == []

            part = chunk(0, b"\x00" * 4, total=8, done=False)
            last = chunk(4, b"\x00" * 4, total=8, done=True)
            await srv._handle_external_frame(screen, part)
            await srv._handle_external_frame(screen, last)
            assert tool.sent == [part, last]
            assert lua.sent == []
            # The finished capture is forgotten; a stray late chunk goes nowhere.
            await srv._handle_external_frame(screen, part)
            assert tool.sent == [part, last]

            # Only a rig screen may answer.
            await srv._handle_external_frame(lua, part)
            assert lua.sent[-1]["type"] == ep.TYPE_ERROR
            assert tool.sent == [part, last]
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_sidecar_admits_one_capture_at_a_time_and_expires_a_stuck_one(monkeypatch):
    from tools.ai_sidecar import server as srv

    clock = [1000.0]
    monkeypatch.setattr(srv.time, "monotonic", lambda: clock[0])

    async def run():
        srv._reset_external_state()
        try:
            screen, first, second = _Peer(), _Peer(), _Peer()
            for peer, client, cls in (
                (screen, "ac-copilot-screen-01", ep.CLIENT_CLASS_SCREEN),
                (first, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
                (second, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
            ):
                await srv._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": client, "client_class": cls}
                )
                peer.sent.clear()
            await srv._handle_external_frame(
                first, {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            )
            await srv._handle_external_frame(
                second, {"v": 1, "type": "screen.capture", "capture_id": "cap-2"}
            )
            # The screen ignores a request while busy, so the sidecar must say so itself.
            assert [f["capture_id"] for f in screen.sent] == ["cap-1"]
            assert second.sent[0]["type"] == ep.TYPE_ERROR
            assert "already in progress" in second.sent[0]["message"]

            # A slow stream stays admitted past the stale window as long as chunks keep coming.
            for _ in range(3):
                clock[0] += srv.SCREEN_CAPTURE_STALE_S - 1
                await srv._handle_external_frame(
                    screen,
                    chunk(0, b"\x00" * 4, total=8, done=False, capture_id="cap-1"),
                )
            await srv._handle_external_frame(
                second, {"v": 1, "type": "screen.capture", "capture_id": "cap-2"}
            )
            assert [f["capture_id"] for f in screen.sent] == ["cap-1"]

            # A capture with no chunk for the stale window stops blocking.
            clock[0] += srv.SCREEN_CAPTURE_STALE_S + 1
            await srv._handle_external_frame(
                second, {"v": 1, "type": "screen.capture", "capture_id": "cap-3"}
            )
            assert [f["capture_id"] for f in screen.sent] == ["cap-1", "cap-3"]
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_requester_disconnect_frees_the_capture_slot():
    from tools.ai_sidecar import server as srv

    async def run():
        srv._reset_external_state()
        try:
            screen, gone, retry = _Peer(), _Peer(), _Peer()
            for peer, client, cls in (
                (screen, "ac-copilot-screen-01", ep.CLIENT_CLASS_SCREEN),
                (gone, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
                (retry, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
            ):
                await srv._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": client, "client_class": cls}
                )
                peer.sent.clear()
            await srv._handle_external_frame(
                gone, {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            )
            srv._drop_external_peer(gone)  # the CLI timed out and closed its socket
            await srv._handle_external_frame(
                retry, {"v": 1, "type": "screen.capture", "capture_id": "cap-2"}
            )
            assert [f["capture_id"] for f in screen.sent] == ["cap-1", "cap-2"]
            assert retry.sent == []
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_sidecar_reports_when_no_screen_is_connected():
    from tools.ai_sidecar import server as srv

    async def run():
        srv._reset_external_state()
        try:
            tool = _Peer()
            await srv._handle_external_frame(
                tool, {"v": 1, "type": "hello", "client": "screen-capture"}
            )
            tool.sent.clear()
            await srv._handle_external_frame(
                tool, {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            )
            assert tool.sent[0]["type"] == ep.TYPE_ERROR
            assert "no rig screen" in tool.sent[0]["message"]
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_cli_raises_the_sidecar_error_instead_of_timing_out(monkeypatch):
    from tools import screen_capture

    class _Client:
        def __init__(self, *_args, **_kwargs):
            self.replies = [ep.make_error("no rig screen connected", ref_type="screen.capture")]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def hello(self):
            return {"type": "hello_ack"}

        async def send(self, _frame):
            return None

        async def wait_for(self, predicate, **_kwargs):
            matched = [f for f in self.replies if predicate(f)]
            return matched[0] if matched else None

    monkeypatch.setattr(screen_capture, "HarnessClient", _Client)
    with pytest.raises(CaptureError, match="sidecar: no rig screen connected"):
        asyncio.run(screen_capture.capture("ws://x", None, wait_s=1.0))


def test_assemble_orders_chunks_and_checks_coverage():
    raw = bytes(range(8))
    chunks = [chunk(4, raw[4:], total=8, done=True), chunk(0, raw[:4], total=8, done=False)]
    assert assemble(chunks) == (raw, 2, 2)
    with pytest.raises(CaptureError, match="received 4 of 8"):
        assemble([chunk(0, raw[:4], total=8, done=True)])
    with pytest.raises(CaptureError, match="does not follow"):
        assemble([chunk(0, raw[:4], total=8, done=False), chunk(6, raw[6:], total=8, done=True)])


def test_assemble_surfaces_a_screen_error():
    with pytest.raises(CaptureError, match="psram alloc failed"):
        assemble([chunk(0, b"", total=8, done=True, error="psram alloc failed")])


def test_rgb565_to_png_decodes_both_byte_orders():
    # red, green, blue, white
    pixels = [0xF800, 0x07E0, 0x001F, 0xFFFF]
    for big_endian, fmt in ((False, "<"), (True, ">")):
        png = rgb565_to_png(struct.pack(f"{fmt}4H", *pixels), 2, 2, big_endian=big_endian)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        idat_len = struct.unpack(">I", png[33:37])[0]
        rows = zlib.decompress(png[41 : 41 + idat_len])
        assert rows == bytes([0, 255, 0, 0, 0, 255, 0, 0, 0, 0, 255, 255, 255, 255])


def test_touch_request_and_ack_validate():
    assert (
        ep.validate_inbound({"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 160, "y": 200})
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "screen.touch",
                "touch_id": "t-drag",
                "x": 160,
                "y": 420,
                "to_x": 160,
                "to_y": 180,
                "hold_ms": 260,
            }
        )
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "screen.touch.ack",
                "touch_id": "t-1",
                "ok": True,
                "x": 160,
                "y": 200,
                "hold_ms": 80,
            }
        )
        is None
    )
    assert (
        ep.validate_inbound(
            {
                "v": 1,
                "type": "screen.touch.ack",
                "touch_id": "t-1",
                "ok": False,
                "error": "preempted by hardware touch",
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "frame",
    [
        {"v": 1, "type": "screen.touch", "x": 10, "y": 10},
        {"v": 1, "type": "screen.touch", "touch_id": "bad\n", "x": 10, "y": 10},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": -1, "y": 10},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 320, "y": 10},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 10, "y": 480},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": True, "y": 10},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 10, "y": 10, "to_x": 20},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 10, "y": 10, "hold_ms": 5},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 10, "y": 10, "hold_ms": 1001},
        {"v": 1, "type": "screen.touch", "touch_id": "t-1", "x": 10, "y": 10, "extra": 1},
        {"v": 1, "type": "screen.touch.ack", "touch_id": "t-1", "ok": True},
        {"v": 1, "type": "screen.touch.ack", "touch_id": "t-1", "ok": False},
        {"v": 1, "type": "screen.touch.ack", "touch_id": "t-1", "ok": False, "error": "bad\nerr"},
        {
            "v": 1,
            "type": "screen.touch.ack",
            "touch_id": "t-1",
            "ok": True,
            "x": 10,
            "y": 10,
            "error": "unexpected",
        },
    ],
)
def test_malformed_touch_frames_are_rejected(frame):
    assert ep.validate_inbound(frame) is not None


def test_screen_touch_requires_loopback_upgrade_header_and_token_and_blocks_browsers():
    from tools.ai_sidecar import server as srv

    class _Req:
        path = "/"

        def __init__(self, headers: dict[str, str]) -> None:
            self.headers = headers

    async def run():
        srv._reset_external_state()
        try:
            process_request = srv.make_process_request("rig-secret")
            screen = _Peer()
            authorized = _Peer()
            missing_token = _Peer()
            wrong_header = _Peer()
            browser = _Peer()
            remote = _Peer()
            remote.remote_address = ("192.168.1.50", 50123)

            assert (
                process_request(
                    authorized,
                    _Req(
                        {ep.CLIENT_HEADER: ep.SCREEN_TOUCH_CLIENT_ID, ep.AUTH_HEADER: "rig-secret"}
                    ),
                )
                is None
            )
            assert (
                process_request(missing_token, _Req({ep.CLIENT_HEADER: ep.SCREEN_TOUCH_CLIENT_ID}))
                is None
            )
            assert (
                process_request(
                    wrong_header, _Req({ep.CLIENT_HEADER: "other", ep.AUTH_HEADER: "rig-secret"})
                )
                is None
            )
            assert (
                process_request(
                    browser,
                    _Req(
                        {ep.CLIENT_HEADER: ep.SCREEN_TOUCH_CLIENT_ID, ep.AUTH_HEADER: "rig-secret"}
                    ),
                )
                is None
            )
            assert (
                process_request(
                    remote,
                    _Req(
                        {ep.CLIENT_HEADER: ep.SCREEN_TOUCH_CLIENT_ID, ep.AUTH_HEADER: "rig-secret"}
                    ),
                )
                is None
            )

            for peer, client, cls in (
                (screen, "ac-copilot-screen-01", ep.CLIENT_CLASS_SCREEN),
                (authorized, ep.SCREEN_TOUCH_CLIENT_ID, ep.CLIENT_CLASS_EXTERNAL),
                (missing_token, ep.SCREEN_TOUCH_CLIENT_ID, ep.CLIENT_CLASS_EXTERNAL),
                (wrong_header, "other", ep.CLIENT_CLASS_EXTERNAL),
                (browser, "tablet", ep.CLIENT_CLASS_BROWSER),
                (remote, ep.SCREEN_TOUCH_CLIENT_ID, ep.CLIENT_CLASS_EXTERNAL),
            ):
                await srv._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": client, "client_class": cls}
                )
                peer.sent.clear()

            for denied in (missing_token, wrong_header, browser, remote):
                await srv._handle_external_frame(
                    denied, {"v": 1, "type": "screen.touch", "touch_id": "t-no", "x": 10, "y": 10}
                )
                assert denied.sent[-1]["type"] == ep.TYPE_ERROR
                assert "authenticated screen-touch loopback" in denied.sent[-1]["message"]
                denied.sent.clear()
            assert screen.sent == []

            req = {"v": 1, "type": "screen.touch", "touch_id": "t-ok", "x": 160, "y": 116}
            await srv._handle_external_frame(authorized, req)
            assert screen.sent == [req]

            # Non-screen peer may not spoof screen.touch.ack.
            spoof = {
                "v": 1,
                "type": "screen.touch.ack",
                "touch_id": "t-ok",
                "ok": True,
                "x": 160,
                "y": 116,
            }
            await srv._handle_external_frame(wrong_header, spoof)
            assert wrong_header.sent[-1]["type"] == ep.TYPE_ERROR
            assert authorized.sent == []

            await srv._handle_external_frame(screen, spoof)
            assert authorized.sent == [spoof]
            assert browser.sent == []
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_touch_cli_sends_screen_touch_client_id_and_captures_after_settle(monkeypatch, tmp_path):
    from tools import screen_capture

    seen_clients: list[str | None] = []
    sent_frames: list[dict] = []

    class _Client:
        def __init__(self, _url, *, token=None, client_id=None, **_kwargs):
            self.client_id = client_id
            self.token = token
            seen_clients.append(client_id)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def hello(self):
            return {"type": "hello_ack"}

        async def send(self, frame):
            sent_frames.append(frame)

        async def wait_for(self, predicate, **_kwargs):
            last = sent_frames[-1]
            if last["type"] == "screen.touch":
                reply = {
                    "v": 1,
                    "type": "screen.touch.ack",
                    "touch_id": last["touch_id"],
                    "ok": True,
                    "x": last["x"],
                    "y": last["y"],
                }
            else:
                reply = chunk(0, b"\x00" * 8, total=8, done=True, capture_id=last["capture_id"])
            assert predicate(reply)
            return reply

    monkeypatch.setattr(screen_capture, "HarnessClient", _Client)
    out = tmp_path / "after_tap.png"
    rc = screen_capture.main(["--touch", "160", "200", "--settle-ms", "0", "--out", str(out)])
    assert rc == 0
    assert seen_clients == [ep.SCREEN_TOUCH_CLIENT_ID, "screen-capture"]
    assert sent_frames[0]["type"] == "screen.touch"
    assert (sent_frames[0]["x"], sent_frames[0]["y"]) == (160, 200)
    assert out.exists()
