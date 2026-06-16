"""Imported reference-lap activation tests for issue #79."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"


def _to_lua(lua: Any, value: Any) -> Any:
    if isinstance(value, dict):
        tbl = lua.table()
        for k, v in value.items():
            tbl[k] = _to_lua(lua, v)
        return tbl
    if isinstance(value, list):
        tbl = lua.table()
        for i, v in enumerate(value, start=1):
            tbl[i] = _to_lua(lua, v)
        return tbl
    return value


def _runtime(tmp_path: Path, files: list[str]):
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    root = str(tmp_path).replace("\\", "/")
    quoted_files = ", ".join(repr(name) for name in files)
    rt.execute(
        f"""
        ac = {{
          FolderID = {{ ScriptConfig = 2 }},
          getFolder = function(_) return {root!r} end,
          getTrackLayout = function() return "" end,
        }}
        io.scanDir = function(_, _) return {{ {quoted_files} }} end
        package.path = package.path .. ";{modules_path}/?.lua"
        """
    )

    def json_parse(raw: str) -> Any:
        return _to_lua(rt, json.loads(str(raw)))

    rt.globals()["JSON"] = rt.table_from({"parse": json_parse})
    return rt


def _record(
    lap_ms: int, *, car: str = "car_a", track: str = "track_a", valid: bool = True
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "imported",
        "import_format": "motec_csv",
        "car": {"id": car},
        "track": {"id": track, "layout": None},
        "lap": {"lap_ms": lap_ms, "is_valid": valid},
        "trace": {
            "fields": [
                "spline",
                "speed",
                "eMs",
                "throttle",
                "brake",
                "steer",
                "gear",
                "px",
                "py",
                "pz",
            ],
            "samples": [
                [0.0, 100, 0, 1, 0, 0, 2, 0, 0, 0],
                [0.5, 120, lap_ms / 2, 1, 0.5, 0.1, 3, 0, 0, 0],
                [0.99, 140, lap_ms, 1, 0, 0, 4, 0, 0, 0],
            ],
        },
    }


def test_best_imported_reference_scans_fastest_matching_car_track(tmp_path: Path) -> None:
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    (laps / "lap_imported_slow.json").write_text(json.dumps(_record(100_000)), encoding="utf-8")
    (laps / "lap_imported_fast.json").write_text(json.dumps(_record(90_000)), encoding="utf-8")
    (laps / "lap_imported_wrong_track.json").write_text(
        json.dumps(_record(80_000, track="other_track")),
        encoding="utf-8",
    )
    (laps / "lap_imported_invalid.json").write_text(
        json.dumps(_record(70_000, valid=False)),
        encoding="utf-8",
    )

    rt = _runtime(
        tmp_path,
        [
            "lap_imported_slow.json",
            "lap_imported_fast.json",
            "lap_imported_wrong_track.json",
            "lap_imported_invalid.json",
        ],
    )
    ref = rt.execute(
        """
        local p = require("persistence")
        return p.bestImportedReference({ id = "car_a" }, { trackName = "track_a" })
        """
    )

    assert ref["lapMs"] == 90_000
    assert len(ref["trace"]) == 3
    assert ref["source"] == "imported"


def test_choose_imported_reference_requires_flag_and_faster_lap(tmp_path: Path) -> None:
    rt = _runtime(tmp_path, [])
    result = rt.execute(
        """
        local p = require("persistence")
        local imported = { lapMs = 90000 }
        return {
          disabled = p.chooseImportedReference(100000, imported, false) ~= nil,
          faster = p.chooseImportedReference(100000, imported, true).lapMs,
          noLocal = p.chooseImportedReference(nil, imported, true).lapMs,
          slower = p.chooseImportedReference(80000, imported, true) ~= nil,
        }
        """
    )

    assert result["disabled"] is False
    assert result["faster"] == 90_000
    assert result["noLocal"] == 90_000
    assert result["slower"] is False


def test_settings_ui_exposes_reference_lap_controls() -> None:
    src = (MODULES_DIR / "hud_settings.lua").read_text(encoding="utf-8")

    assert "Reference lap" in src
    assert "useImportedReference" in src
    assert "Prefer imported reference over local PB" in src
    assert "Open reference laps folder" in src
