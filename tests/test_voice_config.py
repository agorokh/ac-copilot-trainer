"""Tests for voice config — verbosity + cooldown validation (tools.ai_sidecar.voice.config)."""

from __future__ import annotations

import pytest

from tools.ai_sidecar.voice.config import Verbosity, VoiceConfig


def test_verbosity_parse_accepts_string_and_enum() -> None:
    assert Verbosity.parse("low") is Verbosity.LOW
    assert Verbosity.parse("HIGH") is Verbosity.HIGH
    assert Verbosity.parse(Verbosity.OFF) is Verbosity.OFF
    with pytest.raises(ValueError):
        Verbosity.parse("loud")


def test_low_verbosity_suppresses_info_only() -> None:
    cfg = VoiceConfig(verbosity="low")
    assert not cfg.urgency_allowed("info")
    assert cfg.urgency_allowed("prepare")
    assert cfg.urgency_allowed("act")


def test_off_verbosity_mutes_everything() -> None:
    cfg = VoiceConfig(verbosity=Verbosity.OFF)
    assert not cfg.urgency_allowed("info")
    assert not cfg.urgency_allowed("prepare")
    assert not cfg.urgency_allowed("act")


def test_normal_speaks_all_tiers() -> None:
    cfg = VoiceConfig(verbosity=Verbosity.NORMAL)
    assert all(cfg.urgency_allowed(u) for u in ("info", "prepare", "act"))


def test_cooldown_defaults_and_override() -> None:
    cfg = VoiceConfig(cooldown_s={"late_brake": 2.5})
    assert cfg.cooldown_for("late_brake") == 2.5
    # apex_deficit keeps its default since only late_brake was overridden
    assert cfg.cooldown_for("apex_deficit") > 0


def test_high_verbosity_shortens_cooldown() -> None:
    cfg = VoiceConfig(verbosity=Verbosity.HIGH, cooldown_s={"apex_deficit": 6.0})
    assert cfg.cooldown_for("apex_deficit") == pytest.approx(3.0)  # *0.5 default factor


def test_invalid_config_values_rejected() -> None:
    with pytest.raises(ValueError):
        VoiceConfig(ttl_s=-1.0)
    with pytest.raises(ValueError):
        VoiceConfig(dedup_window_s=float("nan"))
    with pytest.raises(ValueError):
        VoiceConfig(cooldown_s={"late_brake": float("inf")})
    with pytest.raises(ValueError):
        VoiceConfig(device_name="   ")
    with pytest.raises(ValueError):
        VoiceConfig(host_api="")
