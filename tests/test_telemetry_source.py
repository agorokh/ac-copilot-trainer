"""Tests for the M0 telemetry source replay core (tools.ai_sidecar.telemetry_source)."""

from __future__ import annotations

import pytest

from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar.external_protocol import TYPE_TELEMETRY_TICK, validate_inbound
from tools.ai_sidecar.telemetry_source import (
    make_hello_frame,
    ticks_from_archive,
)


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


def test_ticks_from_archive_raises_without_trace():
    with pytest.raises(ValueError):
        ticks_from_archive({})


def test_hello_frame_shape():
    h = make_hello_frame()
    assert h["type"] == "hello"
    assert h["client"] == "telemetry-source"
