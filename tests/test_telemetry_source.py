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
