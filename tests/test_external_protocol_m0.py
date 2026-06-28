"""M0 (#341) protocol additions: coaching.cue + telemetry_tick builders, spline/lap validation."""

from __future__ import annotations

from tools.ai_sidecar.external_protocol import (
    TOPIC_COACHING_CUE,
    TYPE_STATE_SNAPSHOT,
    TYPE_TELEMETRY_TICK,
    make_coaching_cue,
    make_telemetry_tick,
    validate_inbound,
)


def _full_payload(**overrides):
    """A telemetry_tick payload carrying every field _validate_telemetry_tick requires."""
    payload = {
        "speed_kmh": 120.0,
        "rpm": 6000,
        "throttle": 0.5,
        "brake": 0.0,
        "steer": 0.1,
        "gear": 3,
        "lat_g": 0.2,
        "long_g": -0.1,
    }
    payload.update(overrides)
    return payload


def test_make_coaching_cue_shape():
    adv = {"kind": "late_brake", "corner": 3, "spline": 0.5, "urgency": "act"}
    frame = make_coaching_cue(adv)
    assert frame["v"] == 1
    assert frame["type"] == TYPE_STATE_SNAPSHOT
    assert frame["topic"] == TOPIC_COACHING_CUE
    assert frame["state"] == adv


def test_make_telemetry_tick_shape_and_validates():
    frame = make_telemetry_tick(_full_payload(spline=0.4), seq=7)
    assert frame["v"] == 1
    assert frame["type"] == TYPE_TELEMETRY_TICK
    assert frame["seq"] == 7
    assert validate_inbound(frame) is None


def test_make_telemetry_tick_omits_seq_when_none():
    assert "seq" not in make_telemetry_tick(_full_payload())


def test_telemetry_tick_accepts_valid_spline_and_lap():
    assert validate_inbound(make_telemetry_tick(_full_payload(spline=0.0, lap=2))) is None
    assert (
        validate_inbound(make_telemetry_tick(_full_payload(spline=1.0, completed_laps=5))) is None
    )


def test_telemetry_tick_rejects_out_of_range_spline():
    assert validate_inbound(make_telemetry_tick(_full_payload(spline=1.5))) is not None
    assert validate_inbound(make_telemetry_tick(_full_payload(spline=-0.1))) is not None


def test_telemetry_tick_rejects_negative_lap():
    assert validate_inbound(make_telemetry_tick(_full_payload(lap=-1))) is not None


def test_telemetry_tick_valid_without_spline_backcompat():
    # spline is additive/optional — a legacy peripheral frame without it still validates.
    assert validate_inbound(make_telemetry_tick(_full_payload())) is None
