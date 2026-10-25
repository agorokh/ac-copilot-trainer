"""Tests for the M0 telemetry source replay core (tools.ai_sidecar.telemetry_source)."""

from __future__ import annotations

import asyncio

import pytest

import tools.ai_sidecar.telemetry_source as telemetry_source
from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar.external_protocol import TYPE_TELEMETRY_TICK, validate_inbound
from tools.ai_sidecar.telemetry_source import (
    make_hello_frame,
    ticks_from_archive,
)


class _StubLap:
    """A lap trace with OUT-OF-RANGE channels, to exercise the clamps in ticks_from_archive."""

    def __init__(self, n=4):
        self._n = n
        self.spline = [1.5, -0.1, 0.5, 0.5][:n]
        self.brake = [1.3, -0.2, 0.5, 0.5][:n]
        self.throttle = [1.4, -0.5, 0.5, 0.5][:n]
        self.steer = [-1.3, 2.0, 0.0, 0.0][:n]
        self.gear = [3.0] * n
        self.lat_g = [0.1] * n
        self.long_g = [-0.1] * n
        self._v = [-5.0, 300.0, 120.0, 120.0][:n]  # includes a negative speed sample

    @property
    def v_kmh(self):
        return self._v

    def __len__(self):
        return self._n


def test_ticks_from_archive_are_valid_telemetry_ticks():
    frames = ticks_from_archive(_corner_archive())
    assert frames
    for frame in frames:
        assert frame["type"] == TYPE_TELEMETRY_TICK
        # every produced frame must satisfy the sidecar's inbound contract, else it is dropped
        # before reaching the observer.
        assert validate_inbound(frame) is None
        assert "spline" in frame["payload"]


def test_ticks_carry_monotonic_seq():
    frames = ticks_from_archive(_corner_archive())
    assert [f["seq"] for f in frames] == list(range(len(frames)))


def test_ticks_spline_within_unit_range():
    for frame in ticks_from_archive(_corner_archive()):
        assert 0.0 <= frame["payload"]["spline"] <= 1.0


def test_ticks_clamp_out_of_range_channels(monkeypatch):
    # Out-of-range archive jitter must be clamped into the contract range so the sidecar admits
    # the frame rather than dropping it — the documented jitter-tolerance of ticks_from_archive.
    monkeypatch.setattr(telemetry_source, "lap_trace_from_archive", lambda archive: _StubLap())
    frames = ticks_from_archive({"ignored": True})
    assert len(frames) == 4
    for frame in frames:
        assert validate_inbound(frame) is None  # would fail if clamps were removed
        p = frame["payload"]
        assert 0.0 <= p["spline"] <= 1.0
        assert 0.0 <= p["throttle"] <= 1.0
        assert 0.0 <= p["brake"] <= 1.0
        assert -1.0 <= p["steer"] <= 1.0
        assert p["speed_kmh"] >= 0.0


def test_ticks_from_archive_raises_without_trace():
    with pytest.raises(ValueError):
        ticks_from_archive({})


def test_hello_frame_shape():
    h = make_hello_frame()
    assert h["type"] == "hello"
    assert h["client"] == "telemetry-source"


def test_period_seconds_rejects_non_positive_hz():
    with pytest.raises(ValueError, match="hz must be a finite value > 0"):
        telemetry_source.period_seconds(0)
    with pytest.raises(ValueError, match="hz must be a finite value > 0"):
        telemetry_source.period_seconds(-1.0)
    with pytest.raises(ValueError, match="hz must be a finite value > 0"):
        telemetry_source.period_seconds(float("nan"))
    with pytest.raises(ValueError, match="hz must be a finite value > 0"):
        telemetry_source.period_seconds(float("inf"))


def test_normalize_live_steer_uses_steering_lock():
    assert telemetry_source.normalize_live_steer(90.0) == pytest.approx(0.2)
    assert telemetry_source.normalize_live_steer(-450.0) == pytest.approx(-1.0)


def test_close_shared_memory_maps_closes_present_handles():
    closed: list[str] = []

    class _Map:
        def __init__(self, name: str):
            self.name = name

        def close(self) -> None:
            closed.append(self.name)

    phys = _Map("phys")
    telemetry_source.close_shared_memory_maps(phys, None)
    assert closed == ["phys"]
    telemetry_source.close_shared_memory_maps(phys, _Map("gfx"))
    assert closed == ["phys", "phys", "gfx"]


def test_stream_live_closes_maps_when_ws_connect_fails(monkeypatch):
    from tools.ac_harness.shared_memory import SHM_GRAPHICS, SHM_PHYSICS

    closed: list[str] = []

    class _Map:
        def __init__(self, name: str):
            self.name = name

        def read(self, size: int) -> bytes:
            return b"\x00" * size

        def close(self) -> None:
            closed.append(self.name)

    monkeypatch.setattr(
        "tools.ac_harness.shared_memory.open_shared_memory",
        lambda name, size: _Map(name),
    )

    class _FailConnect:
        async def __aenter__(self):
            raise ConnectionRefusedError("sidecar down")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr("websockets.connect", lambda *_args, **_kwargs: _FailConnect())

    with pytest.raises(ConnectionRefusedError, match="sidecar down"):
        asyncio.run(telemetry_source.stream_live("ws://127.0.0.1:8765", hz=20.0))

    assert closed == [SHM_PHYSICS, SHM_GRAPHICS]


def test_ticks_from_archive_sanitizes_nan_channels(monkeypatch):
    class _NaNLap:
        def __len__(self):
            return 1

        v_kmh = [float("nan")]
        spline = [float("nan")]
        brake = [float("nan")]
        throttle = [float("nan")]
        steer = [float("nan")]
        gear = [float("nan")]
        lat_g = [0.0]
        long_g = [0.0]

    monkeypatch.setattr(telemetry_source, "lap_trace_from_archive", lambda _a: _NaNLap())
    frames = telemetry_source.ticks_from_archive({"ignored": True})
    assert len(frames) == 1
    assert validate_inbound(frames[0]) is None
    assert frames[0]["payload"]["gear"] == 0


def test_ticks_from_archive_propagates_thermal_and_conditions_metadata():
    archive = _corner_archive()
    archive["car"] = {"id": "ks_bmw_m3_e30", "tyreCompound": "street"}
    archive["conditions"] = {
        "trackGripLevel": 0.97,
        "trackTempC": 29.5,
        "ambientTempC": 21.0,
        "weatherType": "clear",
        "optimalTempC": 80.0,
    }
    tr = archive["trace"]
    tr["fields"] = list(tr["fields"]) + [
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
        "brakeTemp_fl",
        "brakeTemp_fr",
        "brakeTemp_rl",
        "brakeTemp_rr",
    ]
    tr["samples"] = [
        list(row) + [78.5, 79.0, 76.0, 76.5, 340.0, 345.0, 290.0, 295.0] for row in tr["samples"]
    ]

    frames = ticks_from_archive(archive)
    assert frames
    for frame in frames:
        assert validate_inbound(frame) is None
        p = frame["payload"]
        assert p["tyre_temps_c"] == {"fl": 78.5, "fr": 79.0, "rl": 76.0, "rr": 76.5}
        assert p["brake_temps_c"] == {"fl": 340.0, "fr": 345.0, "rl": 290.0, "rr": 295.0}
        assert p["track_grip_level"] == pytest.approx(0.97)
        assert p["track_temp_c"] == pytest.approx(29.5)
        assert p["ambient_temp_c"] == pytest.approx(21.0)
        assert p["weather_type"] == "clear"
        assert p["tyre_compound"] == "street"
        assert p["conditions"]["trackGripLevel"] == pytest.approx(0.97)
        assert p["conditions"]["optimalTempC"] == pytest.approx(80.0)


def test_ticks_from_archive_rejects_bool_nan_inf_on_thermal_and_g_channels():
    archive = _corner_archive()
    archive["conditions"] = {
        "trackGripLevel": True,
        "trackTempC": float("nan"),
        "ambientTempC": float("inf"),
        "weatherType": False,
        "tyreCompound": "slick",
    }
    tr = archive["trace"]
    tr["fields"] = list(tr["fields"]) + [
        "lat_g",
        "long_g",
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
        "brakeTemp_fl",
        "brakeTemp_fr",
        "brakeTemp_rl",
        "brakeTemp_rr",
    ]
    # Sample 0 has bool/NaN/inf values mixed with valid wheel temps; Sample 1 has all invalid temps.
    new_samples = []
    for idx, row in enumerate(tr["samples"]):
        if idx == 0:
            new_samples.append(
                list(row)
                + [
                    True,
                    float("-inf"),
                    82.0,
                    True,
                    float("nan"),
                    float("inf"),
                    False,
                    410.0,
                    float("nan"),
                    float("-inf"),
                ]
            )
        else:
            new_samples.append(
                list(row)
                + [
                    0.4,
                    -0.3,
                    True,
                    False,
                    float("nan"),
                    float("inf"),
                    True,
                    False,
                    float("nan"),
                    float("-inf"),
                ]
            )
    tr["samples"] = new_samples

    frames = ticks_from_archive(archive)
    assert frames
    for frame in frames:
        assert validate_inbound(frame) is None

    p0 = frames[0]["payload"]
    # `True` in lat_g and `-inf` in long_g must be rejected (0.0), never coerced to 1.0.
    assert p0["lat_g"] == 0.0
    assert p0["long_g"] == 0.0
    assert p0["tyre_temps_c"] == {"fl": 82.0}
    assert p0["brake_temps_c"] == {"fr": 410.0}
    assert "track_grip_level" not in p0
    assert "track_temp_c" not in p0
    assert "ambient_temp_c" not in p0
    assert "weather_type" not in p0
    assert p0["tyre_compound"] == "slick"

    p1 = frames[1]["payload"]
    assert "tyre_temps_c" not in p1
    assert "brake_temps_c" not in p1


def test_ticks_from_archive_omits_all_zero_unread_thermal_columns():
    archive = _corner_archive()
    tr = archive["trace"]
    tr["fields"] = list(tr["fields"]) + [
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
        "brakeTemp_fl",
        "brakeTemp_fr",
        "brakeTemp_rl",
        "brakeTemp_rr",
    ]
    tr["samples"] = [list(row) + [0.0] * 8 for row in tr["samples"]]

    frames = ticks_from_archive(archive)
    assert frames
    for frame in frames:
        assert "tyre_temps_c" not in frame["payload"]
        assert "brake_temps_c" not in frame["payload"]


def test_build_live_tick_payload_propagates_shm_thermals_and_rejects_bool_nan():
    import struct

    class _Phys:
        speed_kmh = 135.0
        rpm = 6800
        gas = 0.8
        brake = 0.0
        steer = 45.0
        gear = 4
        accg_lat = True  # bool must be rejected -> 0.0
        accg_lon = float("nan")  # NaN must be rejected -> 0.0
        road_temp = 32.0
        air_temp = 24.0

    class _Gfx:
        norm_pos = 0.42
        completed_laps = 3
        surface_grip = 0.98
        weather_type = "mid_clear"
        tyre_compound = "slick"

    buf = bytearray(400)
    struct.pack_into("<4f", buf, 152, 84.0, 85.5, 81.0, 82.0)
    struct.pack_into("<4f", buf, 348, 450.0, 460.0, 390.0, 395.0)

    payload = telemetry_source.build_live_tick_payload(_Phys(), _Gfx(), phys_buf=bytes(buf))
    frame = telemetry_source.make_telemetry_tick(payload, seq=7)
    assert validate_inbound(frame) is None
    assert payload["lat_g"] == 0.0
    assert payload["long_g"] == 0.0
    assert payload["tyre_temps_c"] == {"fl": 84.0, "fr": 85.5, "rl": 81.0, "rr": 82.0}
    assert payload["brake_temps_c"] == {"fl": 450.0, "fr": 460.0, "rl": 390.0, "rr": 395.0}
    assert payload["track_grip_level"] == pytest.approx(0.98)
    assert payload["track_temp_c"] == pytest.approx(32.0)
    assert payload["ambient_temp_c"] == pytest.approx(24.0)
    assert payload["weather_type"] == "mid_clear"
    assert payload["tyre_compound"] == "slick"
    assert payload["conditions"]["trackGripLevel"] == pytest.approx(0.98)
