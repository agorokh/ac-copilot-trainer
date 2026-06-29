"""Issue #341 M0 contract proofs — Lua telemetry_tick producer + sidecar-only subscribe."""

from __future__ import annotations

from tools.ai_sidecar.external_protocol import (
    SIDECAR_PRODUCED_TOPICS,
    TOPIC_COACHING_CUE,
    topics_are_sidecar_only,
)


def test_coaching_cue_is_sidecar_produced_topic() -> None:
    """Voice clients may subscribe without a loopback Lua peer (#341 / Qodo #5)."""
    assert TOPIC_COACHING_CUE in SIDECAR_PRODUCED_TOPICS
    assert topics_are_sidecar_only([TOPIC_COACHING_CUE]) is True
    assert topics_are_sidecar_only(["coaching.snapshot"]) is False


def test_lua_telemetry_tick_module_exports_publisher() -> None:
    """In-game Lua emits telemetry_tick with spline+lap via telemetry_publisher (#341 / Qodo #4)."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    lua = repo / "src/ac_copilot_trainer/modules/telemetry_publisher.lua"
    text = lua.read_text(encoding="utf-8")
    assert "publishTelemetryTickIfDue" in text
    assert 'type = "telemetry_tick"' in text
    assert "spline" in text
    assert "lap" in text
    assert 'type(car) ~= "table"' not in text
    assert "_field(car" in text
    wired = repo / "src/ac_copilot_trainer/ac_copilot_trainer.lua"
    assert "publishTelemetryTickIfDue" in wired.read_text(encoding="utf-8")
