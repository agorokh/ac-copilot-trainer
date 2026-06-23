"""Regression coverage for #246 render-thread archive deferral."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"


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


def test_create_write_job_refuses_empty_trace(tmp_path: pathlib.Path) -> None:
    """#305 stub guard: a lap with no trace rows must NOT produce an archive at all —
    not the envelope-only ~900-byte stub the coaching pipeline cannot use. The writer
    refuses and the caller (queueLapArchiveJob) logs + skips. No .json, no .tmp."""
    rt = _runtime(tmp_path)
    rt.execute(
        """
        _opts = {
          session_uuid = "session-empty",
          car = { id = "ks_porsche_911_gt3_r_2016" },
          sim = { trackName = "magione", trackLengthM = 2507 },
          lap_n = 5,
          lap_ms = 82550,
          is_pb = true,
          is_valid = true,
          trace = {},  -- no samples
        }
        local lapArchive = require("lap_archive")
        _job, _err = lapArchive.createWriteJob(_opts, 50)
        """
    )
    assert rt.globals()["_job"] is None, "createWriteJob must refuse an empty-trace lap"
    err = rt.globals()["_err"]
    assert isinstance(err, str) and "empty trace" in err, f"unexpected err: {err!r}"
    assert not list(tmp_path.rglob("lap_*.json")), "no stub .json may be written"
    assert not list(tmp_path.rglob("*.tmp")), "no .tmp may be staged"


def test_pending_job_flushes_to_full_archive_in_one_step(tmp_path: pathlib.Path) -> None:
    """#305 drain primitive: a job only partially pumped (the few frames before a session
    ends) must complete to a FULL archive when force-drained in a single large step, never
    left as a .tmp stub. This is exactly what flushPendingLapArchiveJobs relies on."""
    rt = _runtime(tmp_path)
    rt.execute(
        """
        local trace = {}
        for i = 1, 200 do
          trace[i] = {
            spline = (i - 1) / 199, speed = 100, eMs = (i - 1) * 10,
            throttle = 1, brake = 0, steer = 0, gear = 4, px = i, py = 0, pz = i,
          }
        end
        _opts = {
          session_uuid = "session-flush",
          car = { id = "ks_porsche_911_gt3_r_2016" },
          sim = { trackName = "magione", trackLengthM = 2507 },
          lap_n = 7, lap_ms = 82550, is_pb = true, is_valid = true, trace = trace,
        }
        local lapArchive = require("lap_archive")
        _job = assert(lapArchive.createWriteJob(_opts, 50))
        """
    )
    # Reproduce the abandoned state: one per-frame step (64 rows) — not done, .tmp staged.
    first = _step(rt, 64)
    assert first["done"] is False
    assert list(tmp_path.rglob("*.tmp")), "a partial pump should stage a .tmp"
    assert not list(tmp_path.rglob("lap_*.json"))
    # The drain: a single huge-budget step must finish the WHOLE job into a full .json.
    final = _step(rt, 1_000_000)
    assert final["done"] is True
    assert final["ok"] is True
    archive_path = pathlib.Path(final["res"])
    assert archive_path.is_file()
    assert not archive_path.with_name(archive_path.name + ".tmp").exists()
    record = json.loads(archive_path.read_text(encoding="utf-8"))
    assert record["lap"]["lap_n"] == 7
    assert record["trace"]["samples_count"] == 200
    assert len(record["trace"]["samples"]) == 200, "drain must write the full trace, not a stub"


def test_flush_drains_whole_queue_to_full_archives(tmp_path: pathlib.Path) -> None:
    """#305 drain ORCHESTRATION: model the entry's pending-job queue + the synchronous
    flush helper (flushPendingLapArchiveJobs) and drive REAL createWriteJob jobs through
    it. The source-side helper is a file-local in the 2300-line CSP entry and can't be
    required directly (its call-site wiring is guarded by test_lap_archive_source_structure),
    so this mirrors its exact logic — LAP_ARCHIVE_FLUSH_ROWS=1000000, the guard cap, and the
    before==after fallback pop — and asserts the queue-level behavior end to end:
      (a) a partially pumped job (a few per-frame rows) completes to a FULL .json, .tmp gone;
      (b) several queued jobs all drain;
      (c) an empty queue is a no-op.
    """
    rt = _runtime(tmp_path)
    rt.execute(
        """
        -- Faithful mirror of the entry's queue primitives (issue #305). Kept in lockstep
        -- with ac_copilot_trainer.lua via test_lap_archive_source_structure.
        local lapArchive = require("lap_archive")
        local LAP_ARCHIVE_ROWS_PER_FRAME = 64
        local LAP_ARCHIVE_FLUSH_ROWS = 1000000
        _pending = {}
        _written = {}

        function _enqueue(lap_n, n_rows)
          local trace = {}
          for i = 1, n_rows do
            trace[i] = { spline = (i - 1) / math.max(1, n_rows - 1), speed = 100,
              eMs = (i - 1) * 10, throttle = 1, brake = 0, steer = 0, gear = 4,
              px = i, py = 0, pz = i }
          end
          local job = assert(lapArchive.createWriteJob({
            session_uuid = "s", car = { id = "x" },
            sim = { trackName = "magione", trackLengthM = 2507 },
            lap_n = lap_n, lap_ms = 80000 + lap_n, is_pb = false, is_valid = true,
            trace = trace,
          }, 50))
          _pending[#_pending + 1] = job
        end

        function _pump(maxRows)  -- mirror of pumpLapArchiveJobs
          local job = _pending[1]
          if not job then return end
          local done, ok, pathOrErr = job:step(maxRows or LAP_ARCHIVE_ROWS_PER_FRAME)
          if not done then return end
          table.remove(_pending, 1)
          if ok and type(pathOrErr) == "string" then
            _written[#_written + 1] = pathOrErr
          end
        end

        function _flush()  -- mirror of flushPendingLapArchiveJobs
          if #_pending == 0 then return end
          local guard = 0
          while #_pending > 0 and guard < 4096 do
            guard = guard + 1
            local before = #_pending
            _pump(LAP_ARCHIVE_FLUSH_ROWS)
            if #_pending == before then
              table.remove(_pending, 1)
            end
          end
        end

        function _queue_len() return #_pending end
        function _written_len() return #_written end
        """
    )

    # (c) empty queue: flush is a harmless no-op.
    rt.execute("_flush()")
    assert rt.eval("_queue_len()") == 0
    assert rt.eval("_written_len()") == 0

    # (a) one job, partially pumped (the few frames before a session ends), then drained.
    rt.execute("_enqueue(7, 200)")
    rt.execute("_pump(64)")  # one per-frame step: stages a .tmp, not done
    assert rt.eval("_queue_len()") == 1
    assert list(tmp_path.rglob("*.tmp")), "a partial pump should stage a .tmp"
    assert not list(tmp_path.rglob("lap_*.json"))

    rt.execute("_flush()")
    assert rt.eval("_queue_len()") == 0, "flush must drain the queue"
    assert not list(tmp_path.rglob("*.tmp")), "no leftover .tmp after flush"
    archives = list(tmp_path.rglob("lap_*.json"))
    assert len(archives) == 1
    record = json.loads(archives[0].read_text(encoding="utf-8"))
    assert record["lap"]["lap_n"] == 7
    assert record["trace"]["samples_count"] == 200
    assert len(record["trace"]["samples"]) == 200, "drain must write the full trace, not a stub"

    # (b) multiple queued jobs: the loop drains all of them in one flush.
    rt.execute("_enqueue(8, 120)")
    rt.execute("_enqueue(9, 80)")
    assert rt.eval("_queue_len()") == 2
    rt.execute("_flush()")
    assert rt.eval("_queue_len()") == 0, "flush must drain ALL queued jobs, not just the first"
    assert not list(tmp_path.rglob("*.tmp"))
    assert len(list(tmp_path.rglob("lap_*.json"))) == 3  # lap 7 + lap 8 + lap 9
