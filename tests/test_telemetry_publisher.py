"""Lupa L0 regression for the #180 Part D step 2 telemetry producers.

`modules/telemetry_publisher.lua` owns the two continuous telemetry WS topics: `delta` (live
time delta vs the reference lap) and `tire_temps` (current per-wheel core temps). These are
thin, stateless, rate-limited publishers — no ordering contract, no reconnect machinery. Also
covers `tire_monitor.Mon:currentTemps()`, the live per-wheel read the `tire_temps` producer
consumes. Exercised under lupa with a capturing `wsBridge` (publishTopic returns true) or a
closed one (returns false) so the no-op-when-WS-down contract is asserted.
"""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"

_STUB = r"""
function make_ws()
  local calls = {}
  return {
    _calls = calls,
    publishTopic = function(topic, payload)
      calls[#calls + 1] = { topic = topic, payload = payload }
      return true
    end,
    sendJson = function(payload)
      calls[#calls + 1] = { send = payload }
      return true
    end,
  }
end
function make_ws_closed()
  local calls = {}
  return {
    _calls = calls,
    publishTopic = function(topic, payload)
      calls[#calls + 1] = { topic = topic, payload = payload }
      return false
    end,
    sendJson = function(payload)
      calls[#calls + 1] = { send = payload }
      return false
    end,
  }
end
"""


def _runtime():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(_STUB)
    p = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{p}/?.lua"')
    return rt


# --------------------------------------------------------------------------- delta
def test_delta_rate_limited_to_10hz():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r1 = M.publishDeltaIfDue({ dt = 0.05, deltaS = -0.30, spline = 0.5, wsBridge = ws })
          local r2 = M.publishDeltaIfDue({
            dt = 0.06, deltaS = -0.25, spline = 0.52, wsBridge = ws,
          })
          local p = ws._calls[1] and ws._calls[1].payload
          return { r1 = r1, r2 = r2, n = #ws._calls, topic = ws._calls[1] and ws._calls[1].topic,
                   ds = p and p.delta_s, sp = p and p.spline }
        end)()
        """
    )
    assert out["r1"] is False  # 0.05 < 0.1 -> not due
    assert out["r2"] is True  # 0.11 accumulated -> publish
    assert out["n"] == 1
    assert out["topic"] == "delta"
    assert out["ds"] == -0.25
    assert out["sp"] == 0.52


def test_delta_noop_without_reference_delta():
    # No reference lap yet -> caller passes deltaS=nil -> nothing to publish.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishDeltaIfDue({ dt = 1.0, deltaS = nil, spline = 0.5, wsBridge = ws })
          return { r = r, n = #ws._calls }
        end)()
        """
    )
    assert out["r"] is False
    assert out["n"] == 0


# --------------------------------------------------------------------------- tire_temps
def test_tire_temps_rate_limited_and_payload():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local temps = { fl = 85, fr = 86, rl = 83, rr = 84 }
          local r1 = M.publishTireTempsIfDue({ dt = 0.1, temps = temps, wsBridge = ws })
          local r2 = M.publishTireTempsIfDue({ dt = 0.15, temps = temps, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].payload
          return { r1 = r1, r2 = r2, n = #ws._calls, topic = ws._calls[1] and ws._calls[1].topic,
                   fl = p and p.fl, fr = p and p.fr, rl = p and p.rl, rr = p and p.rr }
        end)()
        """
    )
    assert out["r1"] is False  # 0.1 < 0.2 -> not due
    assert out["r2"] is True  # 0.25 accumulated -> publish
    assert out["n"] == 1
    assert out["topic"] == "tire_temps"
    assert (out["fl"], out["fr"], out["rl"], out["rr"]) == (85, 86, 83, 84)


def test_tire_temps_noop_without_temps_table():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishTireTempsIfDue({ dt = 1.0, temps = nil, wsBridge = ws })
          return { r = r, n = #ws._calls }
        end)()
        """
    )
    assert out["r"] is False
    assert out["n"] == 0


def test_tire_temps_noop_when_all_temps_nil():
    # No wheel temp resolvable (CSP build/car) -> empty {} payload would mask the failure;
    # treat the sample as unavailable and don't publish (codex on #185).
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishTireTempsIfDue({ dt = 1.0, temps = {}, wsBridge = ws })
          return { r = r, n = #ws._calls }
        end)()
        """
    )
    assert out["r"] is False
    assert out["n"] == 0


def test_tire_temps_drops_non_finite_values():
    # A non-finite wheel temp (NaN / ±inf) must never reach the wire — JSON can't represent it.
    # The finite wheels still publish; the bad ones are omitted (codex on #185).
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishTireTempsIfDue({
            dt = 1.0, temps = { fl = 80, fr = 0/0, rl = 1/0, rr = 84 }, wsBridge = ws,
          })
          local p = ws._calls[1] and ws._calls[1].payload
          return { r = r, n = #ws._calls, fl = p and p.fl,
                   has_fr = p and p.fr ~= nil, has_rl = p and p.rl ~= nil, rr = p and p.rr }
        end)()
        """
    )
    assert out["r"] is True
    assert out["n"] == 1
    assert out["fl"] == 80
    assert out["has_fr"] is False  # NaN dropped
    assert out["has_rl"] is False  # +inf dropped
    assert out["rr"] == 84


def test_tire_temps_noop_when_all_non_finite():
    # Every wheel non-finite -> treat the sample as unavailable, don't publish an empty frame.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishTireTempsIfDue({
            dt = 1.0, temps = { fl = 0/0, fr = 1/0, rl = -1/0 }, wsBridge = ws,
          })
          return { r = r, n = #ws._calls }
        end)()
        """
    )
    assert out["r"] is False
    assert out["n"] == 0


def test_delta_omits_non_finite_spline():
    # delta_s finite but spline non-finite (corrupt/reset frame): the spline field must be omitted,
    # not emitted as unserializable JSON (codex on #185). The frame still publishes.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishDeltaIfDue({ dt = 1.0, deltaS = -0.3, spline = 1/0, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].payload
          return { r = r, n = #ws._calls, ds = p and p.delta_s, has_spline = p and p.spline ~= nil }
        end)()
        """
    )
    assert out["r"] is True
    assert out["n"] == 1
    assert out["ds"] == -0.3
    assert out["has_spline"] is False  # +inf spline omitted


def test_delta_noop_on_non_finite():
    # A non-finite delta_s (e.g. degenerate reference trace) is unserializable -> skip the frame.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishDeltaIfDue({ dt = 1.0, deltaS = 0/0, spline = 0.5, wsBridge = ws })
          return { r = r, n = #ws._calls }
        end)()
        """
    )
    assert out["r"] is False
    assert out["n"] == 0


def test_mon_current_temps_drops_nan_wheel():
    # readWheelTemp must reject a non-finite field at the source so currentTemps is finite-only.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local TM = require("tire_monitor")
          local mon = TM.new()
          local car = { wheels = {
            [0] = { temperature = 0/0 },
            [1] = { temperature = 70 },
            [2] = { temperature = 71 },
            [3] = { temperature = 72 },
          } }
          local t = mon:currentTemps(car)
          return { has_fl = t.fl ~= nil, fr = t.fr, rl = t.rl, rr = t.rr }
        end)()
        """
    )
    assert out["has_fl"] is False  # NaN at index 0 -> fl unavailable
    assert (out["fr"], out["rl"], out["rr"]) == (70, 71, 72)


def test_tire_temps_publishes_with_partial_temps():
    # At least one resolvable temp -> still a meaningful sample, publish it.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishTireTempsIfDue({ dt = 1.0, temps = { fl = 80 }, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].payload
          return { r = r, n = #ws._calls, fl = p and p.fl, fr = p and p.fr }
        end)()
        """
    )
    assert out["r"] is True
    assert out["n"] == 1
    assert out["fl"] == 80
    assert out["fr"] is None  # unresolved wheels stay absent


# --------------------------------------------------------------------------- contracts
def test_both_noop_when_ws_down():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws_closed()
          local d = M.publishDeltaIfDue({ dt = 1.0, deltaS = -0.2, spline = 0.5, wsBridge = ws })
          local t = M.publishTireTempsIfDue({ dt = 1.0, temps = { fl = 80 }, wsBridge = ws })
          return { d = d, t = t }
        end)()
        """
    )
    assert out["d"] is False
    assert out["t"] is False


def test_producers_return_false_without_wsbridge():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          return {
            d = M.publishDeltaIfDue({ dt = 1.0, deltaS = -0.2 }),
            t = M.publishTireTempsIfDue({ dt = 1.0, temps = { fl = 80 } }),
            bad = M.publishDeltaIfDue("not a table"),
          }
        end)()
        """
    )
    assert out["d"] is False
    assert out["t"] is False
    assert out["bad"] is False


def test_telemetry_tick_rate_limited_to_20hz():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = {
            speedKmh = 120, rpm = 6000, gas = 0.5, brake = 0.0, steer = 0.1,
            gear = 3, splinePosition = 0.42, lapCount = 2,
          }
          local r1 = M.publishTelemetryTickIfDue({ dt = 0.02, car = car, wsBridge = ws })
          local r2 = M.publishTelemetryTickIfDue({ dt = 0.04, car = car, wsBridge = ws })
          local sent = ws._calls[1] and ws._calls[1].send
          return {
            r1 = r1, r2 = r2, n = #ws._calls,
            typ = sent and sent.type,
            spline = sent and sent.payload and sent.payload.spline,
            lap = sent and sent.payload and sent.payload.lap,
          }
        end)()
        """
    )
    assert out["r1"] is False
    assert out["r2"] is True
    assert out["n"] == 1
    assert out["typ"] == "telemetry_tick"
    assert out["spline"] == 0.42
    assert out["lap"] == 2


def test_telemetry_tick_seq_resets_on_module_reset():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = { speedKmh = 1, rpm = 1, splinePosition = 0.1, lapCount = 0 }
          for _ = 1, 3 do
            M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          end
          local seqBefore = ws._calls[#ws._calls].send.seq
          M.reset()
          M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          return { before = seqBefore, after = ws._calls[#ws._calls].send.seq }
        end)()
        """
    )
    assert out["before"] == 3
    assert out["after"] == 1


# --------------------------------------------------------------------------- tire_monitor accessor
def test_mon_current_temps_reads_four_wheels():
    # CSP `car.wheels` is 0-indexed per `ac.Wheel` (FrontLeft=0 .. RearRight=3) — the table is
    # keyed [0..3], NOT a 1-based list. A 1-based read (`wheels[1..4]`) would shift every corner
    # by one and return rr=0 from the out-of-bounds slot (the live regression this fix closes).
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local TM = require("tire_monitor")
          local mon = TM.new()
          local car = { wheels = {
            [0] = { temperature = 85 },
            [1] = { temperature = 86 },
            [2] = { temperature = 83 },
            [3] = { temperature = { average = 84 } },
          } }
          local t = mon:currentTemps(car)
          return { fl = t.fl, fr = t.fr, rl = t.rl, rr = t.rr }
        end)()
        """
    )
    # order fl,fr,rl,rr; the rr wheel (index 3) uses the {average=...} form (readWheelTemp unwraps)
    assert (out["fl"], out["fr"], out["rl"], out["rr"]) == (85, 86, 83, 84)


def test_mon_current_temps_fl_read_from_index_zero():
    # Pin the fix directly: FL must come from wheel index 0 (a 1-based read would miss [0] and
    # instead pull [1..4], shifting every corner and reading rr from an out-of-bounds slot).
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local TM = require("tire_monitor")
          local mon = TM.new()
          local car = { wheels = {
            [0] = { temperature = 60 },
            [1] = { temperature = 61 },
            [2] = { temperature = 62 },
            [3] = { temperature = 63 },
          } }
          local t = mon:currentTemps(car)
          return { fl = t.fl, rr = t.rr }
        end)()
        """
    )
    assert out["fl"] == 60  # index 0 -> fl (the corner a 1-based read would drop)
    assert out["rr"] == 63  # index 3 -> rr (was reading the out-of-bounds 0 before the fix)


def test_mon_update_lap_summary_uses_zero_indexed_wheels():
    # Mon:update shares the wheel-order contract with currentTemps; its lap aggregates must be
    # labeled from the same 0-based read so the summary line's FL/FR/RL/RR match reality.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local TM = require("tire_monitor")
          local mon = TM.new()
          local car = { wheels = {
            [0] = { temperature = 70, slipRatio = 0 },
            [1] = { temperature = 71, slipRatio = 0 },
            [2] = { temperature = 80, slipRatio = 0 },
            [3] = { temperature = 81, slipRatio = 0 },
          } }
          mon:update(car, 0.1, 0.5)
          return mon:lapSummaryLine()
        end)()
        """
    )
    assert out is not None
    # FL=70 (idx0), FR=71 (idx1), RL=80 (idx2), RR=81 (idx3) — corner labels follow the enum order.
    assert "FL 70" in out
    assert "FR 71" in out
    assert "RL 80" in out
    assert "RR 81" in out


def test_mon_current_temps_nil_car_is_all_nil():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local TM = require("tire_monitor")
          local mon = TM.new()
          local t = mon:currentTemps(nil)
          return {
            has_fl = t.fl ~= nil, has_fr = t.fr ~= nil,
            has_rl = t.rl ~= nil, has_rr = t.rr ~= nil,
          }
        end)()
        """
    )
    assert out["has_fl"] is False
    assert out["has_fr"] is False
    assert out["has_rl"] is False
    assert out["has_rr"] is False
