"""Unit tests for the tablet ``adb reverse`` tunnel keeper (issue #567).

The keeper is exercised with a fake ``run`` callable that scripts adb subcommand output, so
the state machine is verified with no adb, no device, and no rig.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from tools.rig_launcher.tablet_tunnel import (
    TunnelStatus,
    ensure_tablet_reverse,
    resolve_adb,
)

_ADB = "/fake/adb"


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class _FakeAdb:
    """Scripts adb output keyed by the first meaningful subcommand token."""

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        # cmd is [adb, <sub>, ...]; key on "reverse --list" vs "reverse" vs "devices".
        key = cmd[1]
        if key == "reverse" and len(cmd) >= 3 and cmd[2] == "--list":
            key = "reverse --list"
        value = self._responses.get(key, _completed())
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(cmd)
        assert isinstance(value, subprocess.CompletedProcess)
        return value


def test_resolve_adb_prefers_explicit_override(tmp_path) -> None:
    adb = tmp_path / "adb.exe"
    adb.write_text("", encoding="utf-8")
    got = resolve_adb({"AC_COPILOT_ADB": str(adb)}, which=lambda _n: None)
    assert got == str(adb)


def test_resolve_adb_missing_returns_none() -> None:
    assert resolve_adb({}, which=lambda _n: None) is None


def test_adb_missing_is_non_fatal(monkeypatch) -> None:
    # Force the resolver to miss regardless of whether this host actually has adb.
    monkeypatch.setattr("tools.rig_launcher.tablet_tunnel.resolve_adb", lambda *_a, **_k: None)

    def _boom(_cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("adb must not be invoked when it cannot be resolved")

    status = ensure_tablet_reverse(_boom, 8765, env={})
    assert status == TunnelStatus(True, "adb-missing", status.detail)
    assert status.ok is True


def test_no_device_is_non_fatal() -> None:
    fake = _FakeAdb({"devices": _completed("List of devices attached\n")})
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    assert status.state == "no-device"
    assert status.ok is True


def test_unauthorized_device_fails_loud() -> None:
    fake = _FakeAdb({"devices": _completed("List of devices attached\n1c00abcd\tunauthorized\n")})
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    assert status.state == "unauthorized"
    assert status.ok is False


def test_existing_tunnel_is_reported_without_reasserting() -> None:
    fake = _FakeAdb(
        {
            "devices": _completed("List of devices attached\n1c00abcd\tdevice\n"),
            "reverse --list": _completed("UsbFfs tcp:8765 tcp:8765\n"),
        }
    )
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    assert status == TunnelStatus(True, "tunnel-up", "tcp:8765 -> tcp:8765")
    # It must NOT issue a `reverse tcp:8765 tcp:8765` assertion when already present.
    assert not any(cmd[1:] == ["reverse", "tcp:8765", "tcp:8765"] for cmd in fake.calls)


def test_missing_tunnel_is_asserted_then_verified() -> None:
    listings = iter(["", "UsbFfs tcp:8765 tcp:8765\n"])

    fake = _FakeAdb(
        {
            "devices": _completed("List of devices attached\n1c00abcd\tdevice\n"),
            "reverse --list": lambda _cmd: _completed(next(listings)),
        }
    )
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    assert status.state == "tunnel-up"
    assert status.ok is True
    assert any(cmd[1:] == ["reverse", "tcp:8765", "tcp:8765"] for cmd in fake.calls)


def test_reverse_assertion_that_does_not_stick_fails_loud() -> None:
    fake = _FakeAdb(
        {
            "devices": _completed("List of devices attached\n1c00abcd\tdevice\n"),
            "reverse --list": _completed(""),  # never present, even after assert
        }
    )
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    assert status.state == "tunnel-down"
    assert status.ok is False


def test_reverse_list_pair_match_is_not_substring_fooled() -> None:
    # `tcp:8765` must not match an unrelated `tcp:87650` mapping.
    fake = _FakeAdb(
        {
            "devices": _completed("List of devices attached\n1c00abcd\tdevice\n"),
            "reverse --list": _completed("UsbFfs tcp:87650 tcp:87650\n"),
        }
    )
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    # 8765 is absent → keeper asserts it; the scripted list still lacks it → tunnel-down.
    assert status.state == "tunnel-down"


def test_adb_devices_spawn_failure_degrades_to_adb_missing() -> None:
    fake = _FakeAdb({"devices": FileNotFoundError("adb vanished")})
    status = ensure_tablet_reverse(fake, 8765, adb=_ADB)
    assert status.state == "adb-missing"
    assert status.ok is True


_KEEPER: Callable[..., TunnelStatus] = ensure_tablet_reverse  # module-symbol smoke
