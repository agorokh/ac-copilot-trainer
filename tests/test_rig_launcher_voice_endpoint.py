"""Issue #672 — launcher voice-endpoint hygiene.

Part A: the own-headset-endpoint invariant, as a **warn-only** probe that flags when the
sidecar resolved voice playback onto the very endpoint Assetto Corsa / FMOD plays through.
Part B: surfacing the ``AC_COPILOT_VOICE_BANK`` arm switch, so a bank parked or force-armed
from the environment is diagnosable from the Voice row and ``status.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.rig_launcher.supervisor as supervisor_module
from tools.rig_launcher import theme
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointSupervisor,
    LauncherPaths,
)

#: The rig's real endpoint today: voice is pinned to the device AC also plays through.
#: This is the spelling Windows shows the operator, i.e. what they will type into
#: ``AC_COPILOT_AC_AUDIO_DEVICE``.
RIG_SHARED_DEVICE = "5.1 Speakers (USB Sound Device)"
OWN_HEADSET_DEVICE = "Headset Earphone (Rig Audio Interface)"

#: The SAME physical endpoint as :data:`RIG_SHARED_DEVICE`, as PortAudio actually reported it
#: on the rig (`sounddevice.query_devices()`, 2026-07-28) per host API. Pinned verbatim so the
#: comparison is anchored to measured reality rather than to a tidied-up fixture: MME truncates
#: to 31 characters and WASAPI/DirectSound carry internal padding before the closing paren.
RIG_DEVICE_AS_MME = "5.1 Speakers (USB Sound Device "
RIG_DEVICE_AS_WASAPI = "5.1 Speakers (USB Sound Device        )"
RIG_DEVICE_AS_DIRECTSOUND = "5.1 Speakers (USB Sound Device        )"


class _Response:
    """Minimal ``urlopen`` context-manager stand-in mirroring tests/test_rig_launcher.py."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _health_payload(
    device_name: str | None = RIG_SHARED_DEVICE,
    *,
    enabled: bool = True,
    state: str = "enabled",
) -> dict[str, object]:
    voice: dict[str, object] = {
        "configured": True,
        "enabled": enabled,
        "state": state,
        "backend": "sounddevice",
    }
    if device_name is not None:
        voice["device_name"] = device_name
        voice["host_api"] = "Windows WASAPI"
    return {"status": "ok", "connected_peers": 1, "screen_peers": 1, "voice": voice}


def _supervisor(
    tmp_path: Path,
    *,
    ac_audio_device: str | None,
    payload: dict[str, object] | None = None,
    voice_bank_source: str = supervisor_module.VOICE_BANK_SOURCE_UNSET,
) -> GamePointSupervisor:
    cfg = GamePointConfig(
        reference_archive="ref.json",
        voice_bank="bank",
        voice_bank_source=voice_bank_source,
        ac_audio_device=ac_audio_device,
        paths=LauncherPaths(tmp_path),
    )
    resolved = _health_payload() if payload is None else payload

    def fake_urlopen(_url: str, timeout: float) -> _Response:
        del timeout
        return _Response(resolved)

    return GamePointSupervisor(cfg, environ={}, urlopen=fake_urlopen)


# --- Part A: endpoint-name comparison --------------------------------------


@pytest.mark.parametrize(
    ("voice_device", "ac_device", "expected"),
    [
        # The same endpoint, spelled identically.
        (RIG_SHARED_DEVICE, RIG_SHARED_DEVICE, True),
        # Case and whitespace differences still name one endpoint.
        ("5.1 SPEAKERS  (USB Sound Device)", "5.1 speakers (USB Sound Device)", True),
        # PortAudio's MME host API truncates names to 31 chars -> a strict prefix.
        ("Headset Earphone (Rig Audio In", OWN_HEADSET_DEVICE, True),
        # --- measured on the rig: one physical endpoint, four host-API spellings. The
        # operator declares the name Windows shows them; every spelling must still match,
        # because a false all-clear here is worse than a false alarm.
        (RIG_DEVICE_AS_WASAPI, RIG_SHARED_DEVICE, True),
        (RIG_DEVICE_AS_DIRECTSOUND, RIG_SHARED_DEVICE, True),
        (RIG_DEVICE_AS_MME, RIG_SHARED_DEVICE, True),
        (RIG_DEVICE_AS_MME, RIG_DEVICE_AS_WASAPI, True),
        # ...and the rig's other real endpoint — the haptic USB-DAC the own-headset
        # invariant exists to keep voice off — must never collide with it.
        ("Bass Shakers (USB PnP Sound Device)", RIG_DEVICE_AS_WASAPI, False),
        ("Bass Shakers (USB PnP Sound Dev", RIG_SHARED_DEVICE, False),
        # KNOWN LIMITATION, pinned deliberately: PortAudio's WDM-KS host API drops the
        # "5.1 " prefix for this same physical endpoint, leaving no prefix relation to the
        # declared name. Not papered over with a suffix rule — that would widen the
        # false-positive surface for a host API the voice stack does not use (#602 resolves
        # voice on WASAPI). The `distinct` verdict prints BOTH names, so a normalization
        # miss is self-diagnosing from the status row.
        ("Speakers (USB Sound Device)", RIG_SHARED_DEVICE, False),
        # Genuinely different endpoints must never warn (the #575 cry-wolf lesson).
        (OWN_HEADSET_DEVICE, RIG_SHARED_DEVICE, False),
        # A short shared token is not a prefix match.
        ("Speaker", "Speakers (USB Sound Device)", False),
        # Nothing to compare yields no verdict rather than a guess.
        ("", RIG_SHARED_DEVICE, False),
        (None, RIG_SHARED_DEVICE, False),
        (RIG_SHARED_DEVICE, None, False),
    ],
)
def test_endpoints_collide_matches_only_the_same_endpoint(
    voice_device: str | None,
    ac_device: str | None,
    expected: bool,
) -> None:
    assert supervisor_module.endpoints_collide(voice_device, ac_device) is expected


# --- Part A: the probe ------------------------------------------------------


def test_shared_endpoint_is_flagged_visibly_and_warn_only(tmp_path: Path) -> None:
    """AC #1 — a visible warning when voice landed on AC's own endpoint, never a blocker."""
    sup = _supervisor(tmp_path, ac_audio_device=RIG_SHARED_DEVICE)

    status = sup.poll_status()

    rows = {row.name: row for row in status.checks}
    assert rows["voice_endpoint"].state == "shared"
    assert rows["voice_endpoint"].ok is True
    assert "AC_COPILOT_VOICE_DEVICE" in rows["voice_endpoint"].detail
    # Visible on the *rendered* Voice row: the launcher view renders `checks` nowhere.
    assert status.voice.state == supervisor_module.VOICE_STATE_SHARED_ENDPOINT
    assert "audio endpoint" in status.voice.detail
    # Warn-only: the row and the aggregate stay green so START keeps working.
    assert status.voice.ok is True
    assert status.ok is True
    saved = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    saved_rows = {row["name"]: row for row in saved["checks"]}
    assert saved_rows["voice_endpoint"]["state"] == "shared"
    assert saved["voice"]["state"] == supervisor_module.VOICE_STATE_SHARED_ENDPOINT


def test_shared_endpoint_never_blocks_start_sidecar(tmp_path: Path) -> None:
    """`start_sidecar` refuses to start on any not-ok preflight row; this must not be one."""
    sup = _supervisor(tmp_path, ac_audio_device=RIG_SHARED_DEVICE)

    checks = sup.preflight(_health_payload())

    assert [row.name for row in checks if not row.ok] == []
    assert "voice_endpoint" in {row.name for row in checks}


def test_own_headset_endpoint_reports_clean(tmp_path: Path) -> None:
    """AC #2 — voice on a non-AC endpoint reports clean, with no false-positive warning."""
    sup = _supervisor(
        tmp_path,
        ac_audio_device=RIG_SHARED_DEVICE,
        payload=_health_payload(OWN_HEADSET_DEVICE),
    )

    status = sup.poll_status()

    rows = {row.name: row for row in status.checks}
    assert rows["voice_endpoint"].state == "distinct"
    assert rows["voice_endpoint"].ok is True
    assert status.voice.state == "enabled"
    assert "endpoint" not in status.voice.detail
    assert status.ok is True


def test_undeclared_ac_device_reads_undeclared_not_clean(tmp_path: Path) -> None:
    """An inert check must never be mistaken for a clean bill of health."""
    sup = _supervisor(tmp_path, ac_audio_device=None)

    status = sup.poll_status()

    rows = {row.name: row for row in status.checks}
    assert rows["voice_endpoint"].state == "undeclared"
    assert rows["voice_endpoint"].ok is True
    assert "AC_COPILOT_AC_AUDIO_DEVICE" in rows["voice_endpoint"].detail
    assert status.voice.state == "enabled"


def test_idle_voice_stream_is_unknown_not_a_collision(tmp_path: Path) -> None:
    """A device name from a stream that is not open is no evidence of contention."""
    sup = _supervisor(
        tmp_path,
        ac_audio_device=RIG_SHARED_DEVICE,
        payload=_health_payload(RIG_SHARED_DEVICE, enabled=False, state="observer_only"),
    )

    status = sup.poll_status()

    rows = {row.name: row for row in status.checks}
    assert rows["voice_endpoint"].state == "unknown"
    assert rows["voice_endpoint"].ok is True
    assert status.voice.state != supervisor_module.VOICE_STATE_SHARED_ENDPOINT


def test_a_failing_voice_row_outranks_the_advisory_warning(tmp_path: Path) -> None:
    sup = _supervisor(
        tmp_path,
        ac_audio_device=RIG_SHARED_DEVICE,
        payload={
            "status": "ok",
            "connected_peers": 1,
            "screen_peers": 1,
            "voice": {"configured": False, "enabled": False, "state": "skipped"},
        },
    )

    status = sup.poll_status()

    assert status.voice.ok is False
    assert status.voice.state == "DISABLED"


def test_shared_endpoint_renders_amber_not_red() -> None:
    assert theme.tone_for(True, supervisor_module.VOICE_STATE_SHARED_ENDPOINT) == "lift"


def test_ac_audio_device_env_overrides_settings(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps({"ac_audio_device": "settings-endpoint"}),
        encoding="utf-8",
    )

    from_settings = GamePointConfig.from_env({}, paths=LauncherPaths(tmp_path))
    from_env = GamePointConfig.from_env(
        {"AC_COPILOT_AC_AUDIO_DEVICE": "env-endpoint"},
        paths=LauncherPaths(tmp_path),
    )

    assert from_settings.ac_audio_device == "settings-endpoint"
    assert from_env.ac_audio_device == "env-endpoint"


# --- Part B: arm-source surfacing ------------------------------------------


def _write_settings(tmp_path: Path, **payload: object) -> None:
    (tmp_path / "settings.json").write_text(json.dumps(payload), encoding="utf-8")


def test_env_voice_bank_wins_and_records_env_as_the_source(tmp_path: Path) -> None:
    _write_settings(tmp_path, voice_bank="settings-bank", reference_archive="ref.json")

    cfg = GamePointConfig.from_env(
        {"AC_COPILOT_VOICE_BANK": "env-bank"},
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(cfg, environ={})

    assert cfg.voice_bank == "env-bank"
    assert cfg.voice_bank_source == supervisor_module.VOICE_BANK_SOURCE_ENV
    assert "bank armed via env" in sup.probe_voice().detail


def test_blank_env_voice_bank_parks_the_settings_bank_and_says_so(tmp_path: Path) -> None:
    """AC #3 — set-but-blank env clears the settings bank; that must be diagnosable."""
    _write_settings(tmp_path, voice_bank="settings-bank", reference_archive="ref.json")

    cfg = GamePointConfig.from_env(
        {"AC_COPILOT_VOICE_BANK": "  "},
        paths=LauncherPaths(tmp_path),
    )
    sup = GamePointSupervisor(cfg, environ={})

    assert cfg.voice_bank is None
    assert cfg.voice_bank_source == supervisor_module.VOICE_BANK_SOURCE_ENV
    assert "bank cleared via env" in sup.probe_voice().detail


def test_settings_voice_bank_reports_settings_as_the_source(tmp_path: Path) -> None:
    _write_settings(tmp_path, voice_bank="settings-bank", reference_archive="ref.json")

    cfg = GamePointConfig.from_env({}, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={})

    assert cfg.voice_bank_source == supervisor_module.VOICE_BANK_SOURCE_SETTINGS
    assert "bank armed via settings" in sup.probe_voice().detail


def test_unset_voice_bank_adds_no_arm_source_noise(tmp_path: Path) -> None:
    cfg = GamePointConfig.from_env({}, paths=LauncherPaths(tmp_path))
    sup = GamePointSupervisor(cfg, environ={})

    assert cfg.voice_bank_source == supervisor_module.VOICE_BANK_SOURCE_UNSET
    assert "bank" not in sup.probe_voice().detail


def test_config_from_args_preserves_every_config_field(tmp_path: Path, monkeypatch) -> None:
    """`config_from_args` rebuilds the config field-by-field, so it silently drops new ones.

    Caught live: with `AC_COPILOT_AC_AUDIO_DEVICE` exported, the real
    `python -m tools.rig_launcher --once` still reported `voice_endpoint: undeclared`,
    because neither #672 field was listed in the rebuild — the feature was inert in the
    product's own entrypoint while every direct-construction unit test passed. Assert the
    whole class generically rather than the two fields, so the next one added cannot repeat it.
    """
    import dataclasses

    from tools.rig_launcher.app import build_arg_parser, config_from_args

    monkeypatch.setenv("AC_COPILOT_GAME_POINT_DIR", str(tmp_path))
    monkeypatch.setenv("AC_COPILOT_AC_AUDIO_DEVICE", RIG_SHARED_DEVICE)
    monkeypatch.setenv("AC_COPILOT_VOICE_BANK", "env-bank")

    args = build_arg_parser().parse_args([])
    rebuilt = config_from_args(args)
    direct = GamePointConfig.from_env(paths=rebuilt.paths)

    dropped = [
        field.name
        for field in dataclasses.fields(GamePointConfig)
        if getattr(rebuilt, field.name) != getattr(direct, field.name)
    ]
    assert dropped == []
    # The two this issue adds, named explicitly so a failure reads unambiguously.
    assert rebuilt.ac_audio_device == RIG_SHARED_DEVICE
    assert rebuilt.voice_bank_source == supervisor_module.VOICE_BANK_SOURCE_ENV


def test_status_json_carries_the_arm_source(tmp_path: Path) -> None:
    """AC #3 — a force-armed bank is diagnosable from status.json, not only the GUI."""
    sup = _supervisor(
        tmp_path,
        ac_audio_device=OWN_HEADSET_DEVICE,
        voice_bank_source=supervisor_module.VOICE_BANK_SOURCE_ENV,
    )

    sup.poll_status()

    saved = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert "bank armed via env" in saved["voice"]["detail"]
