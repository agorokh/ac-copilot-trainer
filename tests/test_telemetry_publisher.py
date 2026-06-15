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


# --------------------------------------------------------------------------- tire_monitor accessor
def test_mon_current_temps_reads_four_wheels():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local TM = require("tire_monitor")
          local mon = TM.new()
          local car = { wheels = {
            { temperature = 85 },
            { temperature = 86 },
            { temperature = 83 },
            { temperature = { average = 84 } },
          } }
          local t = mon:currentTemps(car)
          return { fl = t.fl, fr = t.fr, rl = t.rl, rr = t.rr }
        end)()
        """
    )
    # order fl,fr,rl,rr; the rr wheel uses the {average=...} table form (readWheelTemp unwraps it)
    assert (out["fl"], out["fr"], out["rl"], out["rr"]) == (85, 86, 83, 84)


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
