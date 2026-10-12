"""Setup BEST lookup must preserve history without decoding telemetry in CSP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"


@pytest.fixture
def runtime(tmp_path):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f"package.path = package.path .. {json.dumps(';' + MODULES.as_posix() + '/?.lua')}")
    lua.execute(
        """
        ac = {
          getCarID = function() return 'car' end,
          getTrackID = function() return 'track' end,
          getTrackLayout = function() return 'gp' end,
        }
        """
    )
    directory = tmp_path / "journal/laps"
    directory.mkdir(parents=True)
    lua.globals().data_root = tmp_path.as_posix()
    lua.execute(
        """
        package.preload.persistence = function()
          return {dataDir = function() return data_root end}
        end
        read_count = 0
        local original_open = io.open
        io.open = function(...)
          read_count = read_count + 1
          return original_open(...)
        end
        """
    )
    decoded_sizes = []

    def decode(text):
        decoded_sizes.append(len(text))
        assert len(text) < 65536, "Telemetry was passed to JSON.parse"
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return lua.table_from(parsed, recursive=True)
        return parsed

    lua.globals().decode_metadata = decode
    lua.globals().scan_archive_files = lambda *_: lua.table_from(
        [p.name for p in sorted(directory.glob("lap_*.json"))]
    )
    lua.execute(
        """
        JSON = {parse = function(text) return decode_metadata(text) end}
        io.scanDir = function(...) return scan_archive_files(...) end
        """
    )
    return lua, directory, decoded_sizes


def record(path="C:/setups/car/track/gp/race.ini", lap_ms=90000, **changes):
    result = {
        "car": {"id": "car"},
        "track": {"id": "track", "layout": "gp"},
        "lap": {"lap_ms": lap_ms, "is_valid": True},
        "setup": {"path": path},
        "telemetry": {"samples": [0.123456789] * 100000},
    }
    result.update(changes)
    return result


def test_batch_scans_each_archive_once_and_never_decodes_samples(runtime):
    lua, directory, decoded_sizes = runtime
    paths = ["C:/setups/car/track/gp/race.ini", "C:/setups/car/track/gp/qualify.ini"]
    for i, path in enumerate(paths):
        (directory / f"lap_{i}.json").write_text(json.dumps(record(path, 90000 - 1000 * i)))
    lua.globals().setups = lua.table_from(
        [{"name": Path(path).stem, "path": path} for path in paths], recursive=True
    )
    bests = lua.execute("return require('setup_library').bestForSetups(setups)")
    assert [bests[1], bests[2]] == [90000, 89000]
    assert lua.globals().read_count == 2
    assert max(decoded_sizes) < 1000
    # No stale cache: a newer archived lap is visible on the next request.
    (directory / "lap_2.json").write_text(json.dumps(record(paths[0], 88000)))
    assert lua.execute("return require('setup_library').bestForSetups(setups)")[1] == 88000


@pytest.mark.parametrize(
    "changes",
    [
        {"car": {"id": "other"}},
        {"track": {"id": "other", "layout": "gp"}},
        {"track": {"id": "track", "layout": "junior"}},
        {"lap": {"lap_ms": 70000, "is_valid": False}},
        {"lap": {"lap_ms": -1}},
        {"lap": {"lap_ms": "inf"}},
        {"setup": {"path": "C:/different/race.ini"}},
    ],
)
def test_faster_ineligible_archive_does_not_replace_best(runtime, changes):
    lua, directory, _ = runtime
    path = "C:/setups/car/track/gp/race.ini"
    (directory / "lap_0.json").write_text(json.dumps(record(path)))
    (directory / "lap_1.json").write_text(json.dumps(record(path, 70000, **changes)))
    lua.globals().setup_path = path.upper().replace("/", "\\")
    assert lua.execute("return require('setup_library').bestForSetup('race', setup_path)") == 90000


def test_legacy_snapshot_and_missing_layout_are_preserved(runtime):
    lua, directory, _ = runtime
    value = record(setup={"snapshot": {"path": "C:/setups/race.ini"}}, track={"id": "track"})
    (directory / "lap_0.json").write_text(json.dumps(value))
    assert lua.execute("return require('setup_library').bestForSetup('RACE')") == 90000


def test_metadata_after_samples_and_escaped_delimiters(runtime):
    lua, _, _ = runtime
    value = record()
    value = {"telemetry": {"labels": ['{]\\"', "setup", "}"]}, **value}
    value["telemetry"] = {"labels": ['{]\\"', "setup", "}"]}
    text = json.dumps(value).replace('"car":', '"c\\u0061r":')
    lua.globals().archive = text
    metadata = lua.execute("return require('lap_metadata').parse(archive)")
    assert metadata["car"]["id"] == "car"
    assert metadata["lap"]["lap_ms"] == 90000
    assert metadata["telemetry"] is None


@pytest.mark.parametrize(
    "text",
    [
        '{"car": {] }',
        '{"car": {"id": "car"},}',
        '{"car": {"id": "car"}} trailing',
        '{"car": {"id": "car"}',
        '{"car": {"id": invalid}}',
        '{"car": {"id": "unterminated}}',
        "[]",
    ],
)
def test_broken_framing_and_selected_metadata_fail_closed(runtime, text):
    lua, _, _ = runtime
    lua.globals().archive = text
    assert lua.execute("return require('lap_metadata').parse(archive)") is None


def test_oversized_metadata_is_not_decoded(runtime):
    lua, _, _ = runtime
    lua.globals().archive = json.dumps(record(setup={"path": "x" * 70000}))
    assert lua.execute("return require('lap_metadata').parse(archive)") is None
