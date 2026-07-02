"""Pure unit tests for the CSP Custom-AI mmap writer/reader (EPIC #154 actuator half).

These exercise only the platform-independent halves of ``tools/ac_harness/custom_ai.py``:
the ``CarControls`` / ``SimState`` packers and the ``parse_car_data`` reader. No Assetto
Corsa, no Windows, no mmap — synthetic buffers built at the exact documented offsets, with
pack -> reparse round-trips. The Windows ctypes plumbing is pragma-guarded and validated on
the rig, so it is not imported here.

Offsets are UNVERIFIED upstream; these tests pin the *byte layout the module commits to* so a
future live-verification edit that shifts an offset is caught by a failing round-trip rather
than silently mis-driving the car.
"""

from __future__ import annotations

import struct

import pytest

from tools.ac_harness.custom_ai import (
    CAR_DATA_MIN_BYTES,
    CONTROLS_BUFFER_BYTES,
    CTRL_BRAKE_OFFSET,
    CTRL_GAS_OFFSET,
    CTRL_GEAR_DN_OFFSET,
    CTRL_GEAR_UP_OFFSET,
    CTRL_HANDBRAKE_OFFSET,
    CTRL_STEER_OFFSET,
    CTRL_TELEPORT_POS_OFFSET,
    CTRL_TELEPORT_TO_OFFSET,
    DATA_GEAR_OFFSET,
    DATA_LOOK_OFFSET,
    DATA_PACKET_ID_OFFSET,
    DATA_POSITION_OFFSET,
    DATA_RPM_OFFSET,
    DATA_SPEED_KMH_OFFSET,
    DATA_SPLINE_POSITION_OFFSET,
    SIM_DISABLE_COLLISIONS_OFFSET,
    SIM_EXTRA_SLEEP_MS_OFFSET,
    SIM_PAUSE_OFFSET,
    SIM_RESTART_SESSION_OFFSET,
    SIM_STATE_BUFFER_BYTES,
    TELEPORT_TO_CUSTOM,
    TELEPORT_TO_PITS,
    CarControls,
    CarData,
    SimState,
    car_controls_name,
    car_data_name,
    parse_car_data,
)


# --------------------------------------------------------------------------- helpers
def _car_data_bytes(
    *,
    packet_id: int,
    gear: int,
    rpm: float,
    speed_kmh: float,
    position: tuple[float, float, float],
    look: tuple[float, float, float],
    spline_position: float,
) -> bytes:
    """Build a cai_car_data buffer with the parsed fields at their documented offsets."""
    buf = bytearray(CAR_DATA_MIN_BYTES)
    struct.pack_into("<i", buf, DATA_PACKET_ID_OFFSET, packet_id)
    struct.pack_into("<i", buf, DATA_GEAR_OFFSET, gear)
    struct.pack_into("<f", buf, DATA_RPM_OFFSET, rpm)
    struct.pack_into("<f", buf, DATA_SPEED_KMH_OFFSET, speed_kmh)
    struct.pack_into("<3f", buf, DATA_POSITION_OFFSET, *position)
    struct.pack_into("<3f", buf, DATA_LOOK_OFFSET, *look)
    struct.pack_into("<f", buf, DATA_SPLINE_POSITION_OFFSET, spline_position)
    return bytes(buf)


# --------------------------------------------------------------------------- controls pack
def test_car_controls_pack_buffer_is_zero_filled_and_sized():
    buf = CarControls().pack()
    assert len(buf) == CONTROLS_BUFFER_BYTES
    assert buf == bytes(CONTROLS_BUFFER_BYTES)  # all-default -> every byte zero


def test_car_controls_pack_floats_at_offsets():
    buf = CarControls(gas=0.5, brake=0.25, steer=-0.75, handbrake=1.0).pack()
    assert struct.unpack_from("<f", buf, CTRL_GAS_OFFSET)[0] == pytest.approx(0.5)
    assert struct.unpack_from("<f", buf, CTRL_BRAKE_OFFSET)[0] == pytest.approx(0.25)
    assert struct.unpack_from("<f", buf, CTRL_STEER_OFFSET)[0] == pytest.approx(-0.75)
    assert struct.unpack_from("<f", buf, CTRL_HANDBRAKE_OFFSET)[0] == pytest.approx(1.0)


def test_car_controls_pack_bools_at_offsets():
    buf = CarControls(gear_up=True, gear_dn=False).pack()
    assert buf[CTRL_GEAR_UP_OFFSET] == 1
    assert buf[CTRL_GEAR_DN_OFFSET] == 0
    buf2 = CarControls(gear_up=False, gear_dn=True).pack()
    assert buf2[CTRL_GEAR_UP_OFFSET] == 0
    assert buf2[CTRL_GEAR_DN_OFFSET] == 1


def test_car_controls_clamps_out_of_range_inputs():
    buf = CarControls(gas=2.0, brake=-1.0, steer=5.0, handbrake=-3.0, clutch=2.0).pack()
    assert struct.unpack_from("<f", buf, CTRL_GAS_OFFSET)[0] == pytest.approx(1.0)
    assert struct.unpack_from("<f", buf, CTRL_BRAKE_OFFSET)[0] == pytest.approx(0.0)
    assert struct.unpack_from("<f", buf, CTRL_STEER_OFFSET)[0] == pytest.approx(1.0)  # +5 -> +1
    assert struct.unpack_from("<f", buf, CTRL_HANDBRAKE_OFFSET)[0] == pytest.approx(0.0)


def test_car_controls_steer_clamps_negative_extreme():
    buf = CarControls(steer=-9.0).pack()
    assert struct.unpack_from("<f", buf, CTRL_STEER_OFFSET)[0] == pytest.approx(-1.0)


def test_car_controls_teleport_to_pits_byte():
    buf = CarControls(teleport_to=TELEPORT_TO_PITS).pack()
    assert buf[CTRL_TELEPORT_TO_OFFSET] == TELEPORT_TO_PITS


def test_car_controls_teleport_custom_position_packed():
    buf = CarControls(teleport_to=TELEPORT_TO_CUSTOM, teleport_pos=(10.0, -2.5, 33.0)).pack()
    assert buf[CTRL_TELEPORT_TO_OFFSET] == TELEPORT_TO_CUSTOM
    assert struct.unpack_from("<3f", buf, CTRL_TELEPORT_POS_OFFSET) == pytest.approx(
        (10.0, -2.5, 33.0)
    )


def test_car_controls_teleport_custom_direction_packed():
    from tools.ac_harness.custom_ai import CTRL_TELEPORT_DIR_OFFSET

    buf = CarControls(
        teleport_to=TELEPORT_TO_CUSTOM,
        teleport_pos=(10.0, -2.5, 33.0),
        teleport_dir=(0.6, 0.0, 0.8),
    ).pack()
    assert struct.unpack_from("<3f", buf, CTRL_TELEPORT_DIR_OFFSET) == pytest.approx(
        (0.6, 0.0, 0.8)
    )
    # Default direction stays zeroed so unset teleports cannot aim the car.
    assert struct.unpack_from(
        "<3f", CarControls().pack(), CTRL_TELEPORT_DIR_OFFSET
    ) == pytest.approx((0.0, 0.0, 0.0))


def test_default_controls_have_no_teleport():
    buf = CarControls().pack()
    assert buf[CTRL_TELEPORT_TO_OFFSET] == 0


# --------------------------------------------------------------------------- car data parse
def test_parse_car_data_decodes_fields_at_documented_offsets():
    raw = _car_data_bytes(
        packet_id=777,
        gear=3,
        rpm=6500.0,
        speed_kmh=142.5,
        position=(100.0, 1.5, -200.0),
        look=(0.0, 0.0, 1.0),
        spline_position=0.42,
    )
    data = parse_car_data(raw)
    assert isinstance(data, CarData)
    assert data.packet_id == 777
    assert data.gear == 3
    assert data.rpm == pytest.approx(6500.0)
    assert data.speed_kmh == pytest.approx(142.5)
    assert data.position == pytest.approx((100.0, 1.5, -200.0))
    assert data.look == pytest.approx((0.0, 0.0, 1.0))
    assert data.spline_position == pytest.approx(0.42)


def test_parse_car_data_accepts_full_512_byte_buffer():
    # A real read maps 512 bytes; parsing a longer-than-minimum buffer must still work.
    raw = bytearray(512)
    struct.pack_into("<i", raw, DATA_PACKET_ID_OFFSET, 9)
    struct.pack_into("<f", raw, DATA_SPLINE_POSITION_OFFSET, 0.99)
    data = parse_car_data(bytes(raw))
    assert data.packet_id == 9
    assert data.spline_position == pytest.approx(0.99)


def test_parse_car_data_rejects_short_buffer():
    with pytest.raises(ValueError, match="too short"):
        parse_car_data(bytes(CAR_DATA_MIN_BYTES - 1))


def test_car_data_as_dict_round_trip():
    data = parse_car_data(
        _car_data_bytes(
            packet_id=1,
            gear=-1,
            rpm=0.0,
            speed_kmh=0.0,
            position=(1.0, 2.0, 3.0),
            look=(4.0, 5.0, 6.0),
            spline_position=0.0,
        )
    )
    d = data.as_dict()
    assert d["gear"] == -1
    assert d["position"] == pytest.approx((1.0, 2.0, 3.0))
    assert d["look"] == pytest.approx((4.0, 5.0, 6.0))
    assert set(d) == {
        "packet_id",
        "gear",
        "rpm",
        "speed_kmh",
        "position",
        "look",
        "spline_position",
    }


# --------------------------------------------------------------------------- sim state pack
def test_sim_state_pack_buffer_is_zero_filled_and_sized():
    buf = SimState().pack()
    assert len(buf) == SIM_STATE_BUFFER_BYTES
    assert buf == bytes(SIM_STATE_BUFFER_BYTES)


def test_sim_state_pack_flags_at_offsets():
    buf = SimState(
        pause=True, restart_session=True, disable_collisions=True, extra_sleep_ms=7
    ).pack()
    assert buf[SIM_PAUSE_OFFSET] == 1
    assert buf[SIM_RESTART_SESSION_OFFSET] == 1
    assert buf[SIM_DISABLE_COLLISIONS_OFFSET] == 1
    assert buf[SIM_EXTRA_SLEEP_MS_OFFSET] == 7


def test_sim_state_partial_flags():
    buf = SimState(pause=True).pack()
    assert buf[SIM_PAUSE_OFFSET] == 1
    assert buf[SIM_RESTART_SESSION_OFFSET] == 0
    assert buf[SIM_DISABLE_COLLISIONS_OFFSET] == 0


def test_sim_state_extra_sleep_masks_to_byte():
    # extra_sleep_ms is a single byte; values >255 must wrap, not corrupt adjacent bytes.
    buf = SimState(extra_sleep_ms=257).pack()
    assert buf[SIM_EXTRA_SLEEP_MS_OFFSET] == 1


# --------------------------------------------------------------------------- section names
def test_section_name_templates_use_car_index():
    assert car_controls_name(0) == "AcTools.CSP.NewBehaviour.CustomAI.CarControls0.v0"
    assert car_data_name(0) == "AcTools.CSP.NewBehaviour.CustomAI.Car0.v0"
    assert car_controls_name(3) == "AcTools.CSP.NewBehaviour.CustomAI.CarControls3.v0"
    assert car_data_name(3) == "AcTools.CSP.NewBehaviour.CustomAI.Car3.v0"


def test_section_name_rejects_negative_car_index():
    # A negative index would silently produce an invalid section name (e.g. CarControls-1.v0)
    # that fails obscurely later; the builders reject it up front (CodeRabbit).
    for bad in (-1, -5):
        with pytest.raises(ValueError, match="car_index"):
            car_controls_name(bad)
        with pytest.raises(ValueError, match="car_index"):
            car_data_name(bad)
