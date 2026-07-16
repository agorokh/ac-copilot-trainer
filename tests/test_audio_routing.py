"""#531 Part E: register -> audio_routing policy + its ride on the voice dispatch payload."""

from __future__ import annotations

from tools.ai_sidecar.registers import (
    AUDIO_ROUTING_AUTHORITATIVE_PC,
    AUDIO_ROUTING_TABLET_NATIVE,
    audio_routing_for_register,
)
from tools.ai_sidecar.voice.dispatch import VoiceDispatch


def test_urgent_and_critical_stay_on_the_pc() -> None:
    assert audio_routing_for_register("urgent") == AUDIO_ROUTING_AUTHORITATIVE_PC
    assert audio_routing_for_register("critical") == AUDIO_ROUTING_AUTHORITATIVE_PC
    # Legacy alias resolves through the same ladder.
    assert audio_routing_for_register("firm") == AUDIO_ROUTING_AUTHORITATIVE_PC


def test_calm_alert_and_unknown_route_tablet() -> None:
    assert audio_routing_for_register("calm") == AUDIO_ROUTING_TABLET_NATIVE
    assert audio_routing_for_register("alert") == AUDIO_ROUTING_TABLET_NATIVE
    # An unknown register ranks 0 (calm) — routing must fail toward the glanceable tier,
    # never claim the critical PC path for a malformed producer.
    assert audio_routing_for_register("bogus") == AUDIO_ROUTING_TABLET_NATIVE


def test_voice_dispatch_payload_is_always_pc_owned() -> None:
    """coaching.voice frames exist only AFTER the PC playback sounded the clip — the routing
    on this stream is authoritative_pc by construction, regardless of register; a
    register-based hint would invite the tablet to re-speak a clip the PC just played
    (Codex on PR #615)."""
    for register in ("urgent", "calm"):
        dispatch = VoiceDispatch(
            seq=1,
            clip_id=f"fuel_status.info.{register}",
            kind="fuel_status",
            urgency="info",
            register=register,
            corner=None,
            text="Fuel.",
            duration_ms=420.0,
            t_wall_ms=1_000.0,
            t_mono_ms=2_000.0,
        )
        assert dispatch.to_payload()["audio_routing"] == AUDIO_ROUTING_AUTHORITATIVE_PC
