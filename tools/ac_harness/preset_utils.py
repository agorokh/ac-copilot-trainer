"""Shared deterministic Content Manager preset builders."""

from __future__ import annotations

import json


def build_practice_preset(
    car_id: str, track_id: str, *, start_type: str = "START", layout: str | None = None
) -> str:
    """Render a deterministic Content Manager Quick Drive practice preset."""

    if start_type not in ("START", "PIT"):
        raise ValueError(f"start_type must be 'START' or 'PIT', got {start_type!r}")
    track_field = f"{track_id}/{layout}" if layout else track_id
    mode_data = {
        "StartType": start_type,
        "Penalties": False,
        "PlayerBallast": 0,
        "PlayerRestrictor": 0,
    }
    assists = {
        "IdealLine": False,
        "AutoBlip": True,
        "StabilityControl": 0.0,
        "AutoBrake": False,
        "AutoShifter": False,
        "SlipSteam": 1.0,
        "AutoClutch": False,
        "Abs": 1,
        "TractionControl": 1,
        "VisualDamage": True,
        "Damage": 0.0,
        "TyreWear": 0.0,
        "FuelConsumption": 0.0,
        "TyreBlankets": True,
    }
    track_state = {
        "s": 1.0,
        "t": 1.0,
        "r": 0.0,
        "g": 1,
        "d": "Perfect track for hotlapping.",
        "w": False,
    }
    preset = {
        "Mode": "/Pages/Drive/QuickDrive_Practice.xaml",
        "ModeData": json.dumps(mode_data, separators=(",", ":")),
        "CarId": car_id,
        "TrackId": track_field,
        "WeatherId": "3_clear",
        "RealConditions": False,
        "Temperature": 26.0,
        "Time": 43200,
        "TimeMultipler": 1,
        "tpc": False,
        "TrackPropertiesData": json.dumps(track_state, separators=(",", ":")),
        "asc": False,
        "AssistsData": json.dumps(assists, separators=(",", ":")),
        "ico": True,
    }
    return json.dumps(preset, separators=(",", ":"))
