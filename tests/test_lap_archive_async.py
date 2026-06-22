"""Regression coverage for #246 render-thread archive deferral."""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"
ENTRY = REPO / "src" / "ac_copilot_trainer" / "ac_copilot_trainer.lua"


def _lua_to_py(value: Any) -> Any:
    if hasattr(value, "items"):
        items = list(value.items())
        if not items:
            return []
        keys = [k for k, _ in items]
        if all(isinstance(k, int) for k in keys):
            ordered = sorted(keys)
            if ordered == list(range(1, len(ordered) + 1)):
                return [_lua_to_py(value[i]) for i in ordered]
        return {str(k): _lua_to_py(v) for k, v in items}
    return value


def _runtime(tmp_path: pathlib.Path) -> lupa.LuaRuntime:
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    script_config = str(tmp_path).replace("\\", "/")
    rt.globals()["_script_config"] = script_config
    rt.execute(
        f"""
        package.path = package.path .. ";{modules_path}/?.lua"
        _logs = {{}}
        ac = {{
          FolderID = {{ ScriptConfig = 1 }},
          getFolder = function(_) return _script_config end,
          log = function(msg) _logs[#_logs + 1] = tostring(msg) end,
        }}
        """
    )

    def stringify(table: Any, _pretty: bool = False) -> str:
        return json.dumps(_lua_to_py(table), separators=(",", ":"), sort_keys=True)

    rt.globals()["JSON"] = rt.table_from({"stringify": stringify})
    return rt


def _step(rt: lupa.LuaRuntime, rows: int) -> dict[str, Any]:
    result = rt.execute(
        f"""
        local done, ok, res = _job:step({rows})
        return {{ done = done == true, ok = ok == true, res = res or "" }}
        """
    )
    return _lua_to_py(result)


def test_archive_write_job_streams_trace_over_multiple_steps(tmp_path: pathlib.Path) -> None:
    rt = _runtime(tmp_path)
    rt.execute(
        """
        local trace = {}
        for i = 1, 6 do
          trace[i] = {
            spline = (i - 1) / 5,
            speed = 100 + i,
            eMs = (i - 1) * 1000,
            throttle = 0.5,
            brake = 0.1,
            steer = -0.2,
            gear = 3,
            px = i,
            py = 0,
            pz = i * 2,
          }
        end
        _opts = {
          session_uuid = "session-abc",
          car = { id = "ks_porsche_911_gt3_r_2016" },
          sim = {
            trackName = "magione",
            trackLengthM = 2507,
            trackGripLevel = 0.98,
            ambientTemperature = 21,
            trackTemperature = 29,
          },
          lap_n = 3,
          lap_ms = 81234,
          is_pb = true,
          is_valid = true,
          trace = trace,
          corners = {
            { label = "T1", entrySpeed = 112, minSpeed = 71, exitSpeed = 96 },
          },
          setup_snap = {
            path = "C:/Assetto Corsa/setups/magione.ini",
            keys = {
              { section = "TYRES", key = "PRESSURE_LF", value = "27.5" },
            },
          },
          setup_ini_path = "C:/Assetto Corsa/setups/magione.ini",
          setup_hash = "hash1234",
          rules_hints = { { text = "Brake earlier at T1" } },
          corner_advice = { T1 = "Trail brake to apex" },
        }
        local lapArchive = require("lap_archive")
        local job, err = lapArchive.createWriteJob(_opts, 50)
        assert(job, err)
        _job = job
        """
    )

    first = _step(rt, 2)
    assert first["done"] is False
    assert not list(tmp_path.rglob("lap_*.json"))
    assert list(tmp_path.rglob("*.tmp")), "job should stage a temp file before completion"

    final = first
    for _ in range(10):
        final = _step(rt, 2)
        if final["done"]:
            break

    assert final["done"] is True
    assert final["ok"] is True
    archive_path = pathlib.Path(final["res"])
    assert archive_path.is_file()
    assert not archive_path.with_name(archive_path.name + ".tmp").exists()

    record = json.loads(archive_path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["lap"]["lap_n"] == 3
    assert record["lap"]["lap_ms"] == 81234
    assert record["trace"]["samples_count"] == 6
    assert len(record["trace"]["samples"]) == 6
    assert record["trace"]["fields"] == [
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
        # per-wheel channels (issue #266)
        "wheelAngularSpeed_fl",
        "wheelAngularSpeed_fr",
        "wheelAngularSpeed_rl",
        "wheelAngularSpeed_rr",
        "wheelSlip_fl",
        "wheelSlip_fr",
        "wheelSlip_rl",
        "wheelSlip_rr",
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
    ]
    assert record["setup"]["hash"] == "hash1234"
    assert record["coaching"]["rules_hints"] == ["Brake earlier at T1"]
    assert record["coaching"]["corner_advice_used"]["T1"] == "Trail brake to apex"


def test_lap_boundary_queues_archive_instead_of_sync_write() -> None:
    # This is an intentional source-structure regression test: if the lap
    # boundary or WS pump sections are refactored, update these regex anchors
    # with the implementation so the architectural guard remains meaningful.
    src = ENTRY.read_text(encoding="utf-8")
    match = re.search(
        r"-- Issue #77 Part C / #246: archive this lap.*?state\.lapInvalidatedThisLap = false",
        src,
        flags=re.S,
    )
    assert match is not None
    block = match.group(0)
    assert "queueLapArchiveJob(archiveOpts)" in block
    assert "lapArchive.write" not in block
    assert "lapArchive.buildRecord" not in block

    ws_match = re.search(
        r"wsBridge\.tick\(ch\.simSeconds\(sim\)\).*?-- Issue #180 Part D step 2",
        src,
        flags=re.S,
    )
    assert ws_match is not None
    ws_block = ws_match.group(0)
    assert ws_block.index("wsBridge.pollInbound(8)") < ws_block.index("pumpLapArchiveJobs()")
    assert ws_block.index("pumpLapArchiveJobs()") < ws_block.index("pumpLapArchiveNotifications()")
    assert "pendingLapArchiveRecordPaths" in src
