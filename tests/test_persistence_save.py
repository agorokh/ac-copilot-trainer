"""Exercise the lap snapshot's actual Lua file path, including bootstrap/errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"


def runtime(tmp_path):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(
        "local modules, root = ...; package.path = modules .. '/?.lua;' .. package.path; "
        "ac = {FolderID={ScriptConfig=1}, getFolder=function() return root end, "
        "getCarID=function() return 'car' end, getTrackID=function() return 'track' end, "
        "getTrackLayout=function() return '' end}",
        MODULES.as_posix(),
        tmp_path.as_posix(),
    )
    formats = []

    def from_lua(value):
        if lupa.lua_type(value) == "table":
            keys = list(value.keys())
            if keys and all(isinstance(k, int) for k in keys):
                return [from_lua(value[i]) for i in range(1, len(keys) + 1)]
            return {k: from_lua(v) for k, v in value.items()}
        return value

    def encode(value, pretty=False):
        formats.append(pretty)
        return json.dumps(from_lua(value), indent=2 if pretty else None)

    lua.globals().JSON = lua.table_from({"stringify": encode})
    module = lua.execute("return require('persistence')")
    if isinstance(module, tuple):
        module = module[0]
    return lua, module, formats


def snapshot(lua):
    return lua.execute(
        "local t = {bestLapMs=80045, bestReferenceLapMs=80045, bestLapTrace={}, "
        "lapFeatureHistory={{lapMs=81000,corners={{id=1,entrySpeed=100}}}}}; "
        "for i=1,2000 do t.bestLapTrace[i]={spline=i/2000,speed=100+i/100,eMs=i*40} end; "
        "return t"
    )


def test_repeat_snapshot_preserves_nested_data_without_pretty_or_shell(tmp_path):
    lua, module, formats = runtime(tmp_path)
    path = Path(module.dataPath(None, None))
    path.parent.mkdir(parents=True)
    lua.execute("os.execute = function() error('save must not launch a shell') end")
    data = snapshot(lua)
    for _ in range(3):
        assert module.save(None, None, data) is True
    assert formats == [False, False, False]
    saved = json.loads(path.read_text())
    assert saved["version"] == 3
    assert saved["bestLapMs"] == saved["bestReferenceLapMs"] == 80045
    assert len(saved["bestLapTrace"]) == 2000
    assert saved["bestLapTrace"][-1]["spline"] == 1
    assert saved["lapFeatureHistory"][0]["corners"][0]["entrySpeed"] == 100
    assert "\n" not in path.read_text()
    # A swallowed os.execute error would otherwise conceal an attempted shell call.
    lua.execute("_shell_calls=0; os.execute=function() _shell_calls=_shell_calls+1 end")
    assert module.save(None, None, data) is True
    assert lua.globals()._shell_calls == 0


def test_missing_parent_bootstraps_once_then_uses_direct_open(tmp_path):
    lua, module, _ = runtime(tmp_path)
    path = Path(module.dataPath(None, None))
    calls = []

    def mkdir(command):
        calls.append(command)
        path.parent.mkdir(parents=True)
        return 0

    lua.globals().os.execute = mkdir
    assert module.save(None, None, snapshot(lua)) is True
    assert module.save(None, None, snapshot(lua)) is True
    assert len(calls) == 1
    assert json.loads(path.read_text())["version"] == 3
    # Removing the parent later must not be hidden by a stale in-memory cache.
    path.unlink()
    path.parent.rmdir()
    assert module.save(None, None, snapshot(lua)) is True
    assert len(calls) == 2


def test_serialization_failure_does_not_truncate_existing_snapshot(tmp_path):
    lua, module, _ = runtime(tmp_path)
    path = Path(module.dataPath(None, None))
    path.parent.mkdir(parents=True)
    original = b'{"version":3,"bestLapMs":80045}'
    path.write_bytes(original)
    lua.execute("JSON.stringify=function() error('serialization failed') end")
    assert module.save(None, None, snapshot(lua)) is False
    assert path.read_bytes() == original


def test_unwritable_destination_returns_failure(tmp_path):
    lua, module, _ = runtime(tmp_path)
    lua.execute("io.open=function() return nil end; os.execute=function() return nil end")
    assert module.save(None, None, snapshot(lua)) is False


def test_write_failure_is_reported_and_handle_closed(tmp_path):
    lua, module, _ = runtime(tmp_path)
    lua.execute(
        "_closed=false; io.open=function() return {write=function() return nil end, "
        "close=function() _closed=true end} end"
    )
    assert module.save(None, None, snapshot(lua)) is False
    assert lua.globals()._closed is True
