"""Tests for the EPIC #154 #241 racing telemetry recorder — pure frame parsers."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from tools.ac_harness import racing_telemetry
from tools.ac_harness.racing_telemetry import (
    CSV_HEADER,
    csv_display_gear,
    csv_row,
    parse_graphics,
    parse_physics,
    record,
)


def _phys_buf(**kw: Any) -> bytes:
    b = bytearray(200)
    struct.pack_into("<i", b, 0, kw.get("packet", 7))
    struct.pack_into("<2f", b, 4, kw.get("gas", 0.8), kw.get("brake", 0.0))
    struct.pack_into("<2i", b, 16, kw.get("gear", 4), kw.get("rpm", 6500))
    struct.pack_into("<2f", b, 24, kw.get("steer", -0.25), kw.get("speed", 142.5))
    struct.pack_into("<3f", b, 44, kw.get("accg_lat", 1.3), 0.1, kw.get("accg_lon", -0.9))
    struct.pack_into("<4f", b, 56, *kw.get("slip", (0.2, 0.21, 0.05, 0.06)))
    struct.pack_into("<4f", b, 104, *kw.get("omega", (85.0, 85.1, 86.0, 86.2)))
    return bytes(b)


def _gfx_buf(**kw: Any) -> bytes:
    b = bytearray(256)
    struct.pack_into("<i", b, 0, kw.get("packet", 11))
    struct.pack_into("<i", b, 4, kw.get("status", 2))
    struct.pack_into("<i", b, 132, kw.get("completed_laps", 3))
    struct.pack_into("<f", b, 248, kw.get("norm_pos", 0.4231))  # normalizedCarPosition @248
    return bytes(b)


def test_parse_physics_reads_inputs_and_dynamics():
    p = parse_physics(_phys_buf())
    assert p.packet_id == 7
    assert p.gas == pytest.approx(0.8)
    assert p.brake == pytest.approx(0.0)
    assert p.gear == 4  # raw AC gear (4 = 3rd); csv_row converts to real gear
    assert p.rpm == 6500
    assert p.steer == pytest.approx(-0.25)
    assert p.speed_kmh == pytest.approx(142.5)
    assert p.accg_lat == pytest.approx(1.3)
    assert p.accg_lon == pytest.approx(-0.9)
    assert p.slip == pytest.approx((0.2, 0.21, 0.05, 0.06))
    # wheelAngularSpeed[4]@104 (#532 handshake r_eff channel)
    assert p.wheel_omega == pytest.approx((85.0, 85.1, 86.0, 86.2))


def test_parse_physics_rejects_non_finite_wheel_omega():
    bad = bytearray(_phys_buf())
    struct.pack_into("<f", bad, 104, float("nan"))
    with pytest.raises(ValueError, match="omega_fl"):
        parse_physics(bytes(bad))


def test_parse_static_track_decodes_utf16():
    from tools.ac_harness.shared_memory import STATIC_TRACK_OFFSET, parse_static_track

    b = bytearray(260)
    b[STATIC_TRACK_OFFSET : STATIC_TRACK_OFFSET + 2 * 4] = "spa\x00".encode("utf-16-le")
    assert parse_static_track(bytes(b)) == "spa"


def test_parse_static_track_rejects_short_buffer():
    from tools.ac_harness.shared_memory import parse_static_track

    with pytest.raises(ValueError, match="too short"):
        parse_static_track(b"\x00" * 100)


def test_parse_static_car_decodes_utf16():
    from tools.ac_harness.shared_memory import STATIC_CAR_OFFSET, parse_static_car

    b = bytearray(260)
    car = "ks_porsche_911_gt3_r_2016"
    b[STATIC_CAR_OFFSET : STATIC_CAR_OFFSET + 2 * len(car) + 2] = (car + "\x00").encode("utf-16-le")
    assert parse_static_car(bytes(b)) == car


def test_parse_graphics_reads_lap_and_position():
    g = parse_graphics(_gfx_buf())
    assert g.packet_id == 11
    assert g.status == 2
    assert g.completed_laps == 3
    assert g.norm_pos == pytest.approx(0.4231, abs=1e-4)


def test_parsers_reject_non_finite_values():
    bad = bytearray(_phys_buf())
    struct.pack_into("<f", bad, 28, float("nan"))
    with pytest.raises(ValueError, match="non-finite"):
        parse_physics(bytes(bad))
    gbad = bytearray(_gfx_buf())
    struct.pack_into("<f", gbad, 248, float("inf"))  # normalizedCarPosition @248
    with pytest.raises(ValueError, match="non-finite"):
        parse_graphics(bytes(gbad))


def test_parsers_reject_short_buffers():
    with pytest.raises(ValueError, match="physics buffer too short"):
        parse_physics(b"\x00" * 16)
    with pytest.raises(ValueError, match="graphics buffer too short"):
        parse_graphics(b"\x00" * 16)


def test_csv_row_converts_to_real_gear_and_matches_header_width():
    p = parse_physics(_phys_buf(gear=4))  # raw 4 -> 3rd forward gear
    g = parse_graphics(_gfx_buf())
    row = csv_row(2, 12.5, p, g)
    cols = row.split(",")
    assert len(cols) == len(CSV_HEADER.split(","))
    assert cols[0] == "2"  # lap
    assert cols[4] == "3"  # 3rd gear (AC raw 4)


def test_csv_display_gear_maps_neutral_and_reverse():
    assert csv_display_gear(0) == -1
    assert csv_display_gear(1) == 0
    assert csv_display_gear(4) == 3


def test_record_requires_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(racing_telemetry.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        record(str(tmp_path / "x.csv"))
