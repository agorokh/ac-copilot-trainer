"""Self-healing ``adb reverse`` USB tunnel keeper for the tablet endpoints (issue #567).

The tablet GT dashboard (#531) and voice endpoint (#511) are served on the sidecar's
loopback port and reached from the tablet over ``adb reverse tcp:<port> tcp:<port>`` —
the tablet's ``127.0.0.1:<port>`` is forwarded across the USB cable to the PC's sidecar.
The Game Point EXE starts the sidecar but historically never established that tunnel, and
nothing re-asserted it after an unplug / device sleep / ``adb kill-server`` / reboot, so the
dashboard silently sat disconnected (root-caused live 2026-07-14).

This module is the keeper: given a ``run`` callable (``subprocess.run``-shaped, injected so
the supervisor's tests stay hermetic), :func:`ensure_tablet_reverse` resolves ``adb``, checks
the device, and asserts the reverse tunnel — idempotently, so it is safe to call on every
status poll. It is **stdlib-only** (PyInstaller-freezable, no new runtime dep) and **no-ops
cleanly when adb is absent** so CI and non-rig hosts never fail on it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

_WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_ADB_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class TunnelStatus:
    """Outcome of one keeper pass. The supervisor maps this to a ``ProbeResult``.

    ``ok`` follows a fail-loud-but-not-flappy posture: states that are merely "no tablet
    intended here" (``adb-missing``, ``no-device``, ``unmanaged``) are ``ok=True`` so they
    never turn the launcher red on a rig without a tablet; states that mean "a tablet is
    present but the link is broken" (``unauthorized``, ``tunnel-down``) are ``ok=False``.
    """

    ok: bool
    state: str
    detail: str = ""


def resolve_adb(
    env: Mapping[str, str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Locate the ``adb`` executable, or ``None`` when it is not installed.

    Checks ``AC_COPILOT_ADB`` (explicit override), then ``PATH``, then the two winget
    install locations the rig uses (Google Platform Tools and the scrcpy bundle), since a
    winget-installed adb is not always on a GUI-launched process's ``PATH``.
    """
    env_map = env if env is not None else os.environ
    override = (env_map.get("AC_COPILOT_ADB") or "").strip()
    if override and Path(override).is_file():
        return override
    found = which("adb")
    if found:
        return found
    local_app_data = (env_map.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        base = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        for pattern in (
            "Google.PlatformTools_*/platform-tools/adb.exe",
            "Genymobile.scrcpy_*/scrcpy-*/adb.exe",
        ):
            for candidate in sorted(base.glob(pattern)):
                if candidate.is_file():
                    return str(candidate)
    return None


def _adb_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": _ADB_TIMEOUT_SECONDS,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _WINDOWS_NO_WINDOW
    return kwargs


def _run_adb(
    run: Callable[..., subprocess.CompletedProcess[str]],
    adb: str,
    args: list[str],
) -> subprocess.CompletedProcess[str] | None:
    """Run one adb command, returning ``None`` on any spawn/timeout failure."""
    try:
        return run([adb, *args], **_adb_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None


def _device_state(devices_stdout: str) -> str:
    """Classify ``adb devices`` → ``device`` / ``unauthorized`` / ``offline`` / ``none``.

    A single connected+authorized device wins. ``unauthorized`` (the "Allow USB debugging?"
    prompt not yet accepted) and ``offline`` (a present-but-unusable tablet — asleep, wedged,
    or ``bootloader``/``recovery``; adb's own ``get-state`` documents ``offline | bootloader |
    device``) are each reported distinctly so a plugged-in-but-broken tablet surfaces an
    actionable reconnect/reset state instead of masquerading as ``none`` ("no tablet").
    """
    saw_unauthorized = False
    saw_present_unusable = False
    for line in devices_stdout.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        state = parts[1].lower()
        if state == "device":
            return "device"
        if state == "unauthorized":
            saw_unauthorized = True
        else:
            # offline / bootloader / recovery / sideload / host / no permissions — a device
            # line exists but is not a usable target. Present-but-unusable, not absent.
            saw_present_unusable = True
    if saw_unauthorized:
        return "unauthorized"
    if saw_present_unusable:
        return "offline"
    return "none"


def _authorized_serials(devices_stdout: str) -> list[str]:
    """Serials of every authorized (``device``-state) transport in ``adb devices`` output."""
    serials: list[str] = []
    for line in devices_stdout.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].lower() == "device":
            serials.append(parts[0])
    return serials


def _reverse_present(reverse_list_stdout: str, port: int) -> bool:
    """True iff ``adb reverse --list`` already maps ``tcp:<port>`` → ``tcp:<port>``.

    adb prints e.g. ``UsbFfs tcp:8765 tcp:8765``; a bare ``tcp:8765`` substring would also
    match an unrelated ``tcp:87650``, so match the whole forwarding pair as tokens.
    """
    spec = f"tcp:{port}"
    for line in reverse_list_stdout.splitlines():
        tokens = line.split()
        if tokens.count(spec) >= 2:
            return True
    return False


def ensure_tablet_reverse(
    run: Callable[..., subprocess.CompletedProcess[str]],
    port: int,
    *,
    env: Mapping[str, str] | None = None,
    adb: str | None = None,
) -> TunnelStatus:
    """Assert (and self-heal) the ``adb reverse tcp:<port> tcp:<port>`` tablet tunnel.

    Called **only when tablet management is opted in** (the caller gates on
    ``manage_tablet_tunnel``), so a missing/unresponsive adb here is a real, actionable
    failure — the operator asked for the tunnel and it cannot be created. Idempotent —
    call it on every status poll. Returns a :class:`TunnelStatus`:

    * ``adb-missing``    — adb not installed / not responding; managed tunnel impossible (fail).
    * ``no-device``      — no tablet over USB yet (ok, non-fatal — nothing to connect).
    * ``unauthorized``   — tablet present but USB debugging not authorized (fail-loud).
    * ``device-offline`` — tablet present but offline/unusable (fail-loud).
    * ``tunnel-up``      — the reverse mapping exists (asserting it first if needed).
    * ``tunnel-down``    — a device is present but the reverse assertion did not stick.
    """
    adb = adb or resolve_adb(env)
    if adb is None:
        return TunnelStatus(
            False,
            "adb-missing",
            "adb not found — install Google.PlatformTools to manage the tablet tunnel",
        )
    # start-server is best-effort: a stale/absent daemon otherwise makes the first
    # `devices` call flaky. Ignore its result; `devices` below is the real probe.
    _run_adb(run, adb, ["start-server"])
    devices = _run_adb(run, adb, ["devices"])
    if devices is None or devices.returncode != 0:
        return TunnelStatus(False, "adb-missing", "adb present but not responding to `devices`")
    state = _device_state(devices.stdout or "")
    if state == "none":
        return TunnelStatus(True, "no-device", "no tablet connected over USB")
    if state == "unauthorized":
        return TunnelStatus(
            False,
            "unauthorized",
            "tablet USB debugging not authorized — accept the prompt on the tablet",
        )
    if state == "offline":
        return TunnelStatus(
            False,
            "device-offline",
            "tablet present but offline/unusable — wake it or re-seat the USB cable",
        )
    # Pick the transport explicitly: with more than one authorized device/emulator, a bare
    # `adb reverse` errors "more than one device/emulator" and the tunnel would read
    # tunnel-down even though the tablet is fine. Use the sole serial, or an operator-chosen
    # AC_COPILOT_ADB_SERIAL; refuse to guess among several (#568 review).
    serials = _authorized_serials(devices.stdout or "")
    env_map = env if env is not None else os.environ
    chosen = (env_map.get("AC_COPILOT_ADB_SERIAL") or "").strip()
    if chosen:
        if chosen not in serials:
            return TunnelStatus(
                False,
                "no-device",
                f"AC_COPILOT_ADB_SERIAL={chosen} not among connected devices {serials}",
            )
        serial = chosen
    elif len(serials) == 1:
        serial = serials[0]
    else:
        return TunnelStatus(
            False,
            "multiple-devices",
            f"{len(serials)} authorized devices {serials} — "
            "set AC_COPILOT_ADB_SERIAL to the tablet's serial",
        )
    sel = ["-s", serial]
    spec = f"tcp:{port}"
    listing = _run_adb(run, adb, [*sel, "reverse", "--list"])
    if listing is not None and _reverse_present(listing.stdout or "", port):
        return TunnelStatus(True, "tunnel-up", f"{spec} -> {spec}")
    _run_adb(run, adb, [*sel, "reverse", spec, spec])
    verify = _run_adb(run, adb, [*sel, "reverse", "--list"])
    if verify is not None and _reverse_present(verify.stdout or "", port):
        return TunnelStatus(True, "tunnel-up", f"asserted {spec} -> {spec}")
    return TunnelStatus(False, "tunnel-down", f"failed to assert `adb reverse {spec} {spec}`")
