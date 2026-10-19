"""Setup BEST lookup must preserve history without decoding telemetry in CSP."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"


@pytest.fixture(params=["lua51", "luajit21"])
def runtime(tmp_path, request):
    target = importlib.import_module(f"lupa.{request.param}")
    lua = target.LuaRuntime(unpack_returned_tuples=True)
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
        close_count = 0
        max_read_bytes = 0
        local original_open = io.open
        io.open = function(...)
          read_count = read_count + 1
          local file = original_open(...)
          if not file then return nil end
          return {
            read = function(_, size)
              assert(type(size) == 'number' and size <= 32768, 'Unbounded archive read')
              max_read_bytes = math.max(max_read_bytes, size)
              return file:read(size)
            end,
            write = function(_, ...) return file:write(...) end,
            close = function()
              close_count = close_count + 1
              return file:close()
            end,
          }
        end
        """
    )
    decoded_sizes = []

    def decode(text):
        decoded_sizes.append(len(text))
        assert len(text) < 65536, "Telemetry was passed to JSON.parse"
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
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
    assert lua.globals().close_count == 2
    assert lua.globals().max_read_bytes == 32768
    assert max(decoded_sizes) < 1000
    # Archives are immutable: a repeat request reads none of them again.
    lua.execute("return require('setup_library').bestForSetups(setups)")
    assert lua.globals().read_count == 2
    # No stale cache: a newer archived lap is visible on the next request.
    (directory / "lap_2.json").write_text(json.dumps(record(paths[0], 88000)))
    assert lua.execute("return require('setup_library').bestForSetups(setups)")[1] == 88000
    assert lua.globals().read_count == 3
    # A deleted archive drops out instead of lingering in the index.
    (directory / "lap_2.json").unlink()
    assert lua.execute("return require('setup_library').bestForSetups(setups)")[1] == 90000


def _lua_to_py(value):
    if hasattr(value, "items") and not isinstance(value, dict):
        items = dict(value.items())
        if items and all(isinstance(k, int) for k in items):
            return [_lua_to_py(items[k]) for k in sorted(items)]
        return {str(k): _lua_to_py(v) for k, v in items.items()}
    return value


def _enable_disk_index(lua):
    """Give the persistence stub the JSON helpers the on-disk index needs."""
    lua.globals().encode_json = lambda t: json.dumps(_lua_to_py(t))
    lua.execute(
        """
        package.loaded.persistence = nil
        package.preload.persistence = function()
          return {
            dataDir = function() return data_root end,
            encodeJsonCompact = function(t) return encode_json(t) end,
            decodeJson = function(s)
              if s == nil or s == '' then return nil end
              return decode_metadata(s)
            end,
          }
        end
        """
    )


def _new_ac_launch(lua):
    lua.execute("package.loaded.setup_library = nil; package.loaded.lap_metadata = nil")
    lua.globals().read_count = 0


def test_disk_index_survives_a_new_ac_launch_without_rereading_archives(runtime):
    lua, directory, _ = runtime
    _enable_disk_index(lua)
    path = "C:/setups/car/track/gp/race.ini"
    (directory / "lap_0.json").write_text(json.dumps(record(path, 91000)))
    (directory / "lap_1.json").write_text(json.dumps(record(path, 90500)))
    best = "return require('setup_library').bestForSetup('race', setup_path)"
    lua.globals().setup_path = path
    assert lua.execute(best) == 90500
    index = json.loads((directory.parent / "lap-metadata-index.json").read_text())
    assert index["version"] == 1
    assert sorted(index["entries"]) == ["lap_0.json", "lap_1.json"]
    assert "telemetry" not in index["entries"]["lap_0.json"]["rec"]

    _new_ac_launch(lua)
    assert lua.execute(best) == 90500
    assert lua.globals().read_count == 1  # the index only; no archive is opened

    (directory / "lap_2.json").write_text(json.dumps(record(path, 89000)))
    _new_ac_launch(lua)
    assert lua.execute(best) == 89000
    assert lua.globals().read_count == 3  # index, the one new archive, the index rewrite
    # The rewrite replaced the existing index in place and left no temp or backup behind.
    index = json.loads((directory.parent / "lap-metadata-index.json").read_text())
    assert sorted(index["entries"]) == ["lap_0.json", "lap_1.json", "lap_2.json"]
    leftovers = sorted(p.name for p in directory.parent.glob("lap-metadata-index.json.*"))
    assert leftovers == []


def test_unreadable_archive_is_retried_and_not_indexed(runtime):
    lua, directory, _ = runtime
    _enable_disk_index(lua)
    path = "C:/setups/car/track/gp/race.ini"
    (directory / "lap_0.json").write_text(json.dumps(record(path)))
    (directory / "lap_1.json").write_text(json.dumps(record(path, 70000))[:-1])
    lua.globals().setup_path = path
    best = "return require('setup_library').bestForSetup('race', setup_path)"
    assert lua.execute(best) == 90000
    index = json.loads((directory.parent / "lap-metadata-index.json").read_text())
    assert sorted(index["entries"]) == ["lap_0.json"]
    lua.globals().read_count = 0
    assert lua.execute(best) == 90000
    # The broken archive is read again (it may be repaired), but the index is not rewritten.
    assert lua.globals().read_count == 1


def test_corrupt_index_file_is_rebuilt(runtime):
    lua, directory, _ = runtime
    _enable_disk_index(lua)
    (directory.parent / "lap-metadata-index.json").write_text('{"version": 1, "entr')
    path = "C:/setups/car/track/gp/race.ini"
    (directory / "lap_0.json").write_text(json.dumps(record(path, 88800)))
    lua.globals().setup_path = path
    assert lua.execute("return require('setup_library').bestForSetup('race', setup_path)") == 88800
    index = json.loads((directory.parent / "lap-metadata-index.json").read_text())
    assert sorted(index["entries"]) == ["lap_0.json"]


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


@pytest.mark.parametrize("offset", range(-3, 4))
def test_streamed_escape_and_metadata_cross_chunk_boundaries(runtime, offset):
    lua, directory, _ = runtime
    value = record()
    # Put escaped quotes, backslashes, braces and brackets across chunk edges.
    prefix = "x" * (32768 + offset) + '\\"}]'
    value = {"telemetry": {"labels": [prefix]}, **value}
    path = directory / "lap_boundary.json"
    path.write_text(json.dumps(value))
    lua.globals().archive_path = path.as_posix()
    metadata = lua.execute("return require('lap_metadata').read(archive_path)")
    assert metadata["lap"]["lap_ms"] == 90000
    assert metadata["car"]["id"] == "car"
    assert metadata["telemetry"] is None
    assert lua.globals().close_count == 1


@pytest.mark.parametrize("suffix", [" trailing", ',"broken":{]}'])
def test_streamed_trailing_corruption_fails_closed_and_closes_file(runtime, suffix):
    lua, directory, _ = runtime
    path = directory / "lap_broken.json"
    path.write_text(json.dumps(record()) + suffix)
    lua.globals().archive_path = path.as_posix()
    assert lua.execute("return require('lap_metadata').read(archive_path)") is None
    assert lua.globals().close_count == 1
