"""Package smoke tests for optional AI WebSocket sidecar (issue #9 Part B)."""

import asyncio
import importlib

import pytest


def test_ai_sidecar_subpackage_importable() -> None:
    importlib.import_module("tools.ai_sidecar")


def test_ai_sidecar_server_importable_when_websockets_installed() -> None:
    pytest.importorskip("websockets")
    importlib.import_module("tools.ai_sidecar.server")


def test_run_exits_cleanly_when_port_already_in_use(monkeypatch) -> None:
    """Port-in-use must raise SystemExit(str), not an unhandled OSError traceback.

    A frozen ``--noconsole`` launcher turns an unhandled exception into a Windows
    "Unhandled exception in script" dialog; a ``SystemExit`` string just logs the reason and
    exits non-zero. Reproduces WinError 10048 from the rig log.
    """
    websockets = pytest.importorskip("websockets")
    server = importlib.import_module("tools.ai_sidecar.server")

    class _BoomServe:
        async def __aenter__(self):
            err = OSError("only one usage of each socket address is normally permitted")
            err.errno = server._WSAEADDRINUSE
            raise err

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(websockets, "serve", lambda *a, **k: _BoomServe())

    with pytest.raises(SystemExit) as excinfo:
        asyncio.run(server._run("127.0.0.1", 8765, False, None))

    assert "already in use" in str(excinfo.value)


def test_run_reraises_unrelated_oserror(monkeypatch) -> None:
    """A non-bind OSError must NOT be swallowed as a port-in-use SystemExit."""
    websockets = pytest.importorskip("websockets")
    server = importlib.import_module("tools.ai_sidecar.server")

    class _BoomServe:
        async def __aenter__(self):
            raise OSError("disk on fire")  # no errno set → not EADDRINUSE

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(websockets, "serve", lambda *a, **k: _BoomServe())

    with pytest.raises(OSError, match="disk on fire"):
        asyncio.run(server._run("127.0.0.1", 8765, False, None))
