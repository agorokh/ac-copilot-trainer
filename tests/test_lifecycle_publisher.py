"""Lupa L0 regression for the #180 Part D step 2 lifecycle producers.

`modules/lifecycle_publisher.lua` owns the three lifecycle WS topics the autonomous
self-test harness's sequence assertions need: `connection` (~1 Hz heartbeat),
`session` (on track/car/session change), and `lap` (on the lap boundary). These tests
exercise it under lupa with NO Assetto Corsa and NO sidecar — a Lua-side capturing
`wsBridge` records every `publishTopic(topic, payload)` so we assert topic names,
payload shape, rate-limiting, change-detection, and the no-op-when-WS-down contract.
"""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"

# `ac` content-id mocks + two capturing wsBridge factories: one whose publishTopic
# succeeds (returns true, like a hello-acked sidecar) and one that returns false
# (WS not open). Both record their calls so tests can assert on the payloads.
_STUB = r"""
ac = {
  getCarID = function(_i) return "bmw_m3_gt2" end,
  getTrackID = function() return "ks_laguna_seca" end,
}
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
      return false  -- WS not hello-acked yet
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


def test_connection_heartbeat_is_rate_limited_to_1hz():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local s1 = { currentSessionIndex = 1 }
          local r1 = M.publishConnectionIfDue({ dt = 0.5, sim = s1, wsBridge = ws })
          local r2 = M.publishConnectionIfDue({ dt = 0.6, sim = s1, wsBridge = ws })
          local c = ws._calls[1]
          return { r1 = r1, r2 = r2, n = #ws._calls, topic = c and c.topic,
                   car = c and c.payload.car_id, track = c and c.payload.track_id,
                   sess = c and c.payload.session_index }
        end)()
        """
    )
    assert out["r1"] is False  # 0.5s < 1.0s -> not due
    assert out["r2"] is True  # 1.1s accumulated -> publish
    assert out["n"] == 1
    assert out["topic"] == "connection"
    assert out["car"] == "bmw_m3_gt2"
    assert out["track"] == "ks_laguna_seca"
    assert out["sess"] == 1


def test_session_published_once_then_suppressed_until_change():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local opts0 = { sim = { currentSessionIndex = 0 }, wsBridge = ws }
          local r1 = M.publishSessionIfChanged(opts0)  -- first -> publish
          local r2 = M.publishSessionIfChanged(opts0)  -- same key -> suppress
          -- changed session index -> publish again
          local r3 = M.publishSessionIfChanged({ sim = { currentSessionIndex = 1 }, wsBridge = ws })
          local c = ws._calls[1]
          return { r1 = r1, r2 = r2, r3 = r3, n = #ws._calls, topic = c and c.topic,
                   sess = c and c.payload.session_index }
        end)()
        """
    )
    assert out["r1"] is True
    assert out["r2"] is False
    assert out["r3"] is True
    assert out["n"] == 2
    assert out["topic"] == "session"
    assert out["sess"] == 0


def test_session_retries_after_ws_recovers():
    # Regression: a session change while the WS is down must NOT mark the key as
    # sent, so the initial `session` frame is re-published once the WS comes up.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local sim0 = { currentSessionIndex = 0 }
          local down = make_ws_closed()
          local r_down = M.publishSessionIfChanged({ sim = sim0, wsBridge = down })
          local up = make_ws()
          local r_up = M.publishSessionIfChanged({ sim = sim0, wsBridge = up })
          local c = up._calls[1]
          return { r_down = r_down, r_up = r_up, n_up = #up._calls, topic = c and c.topic }
        end)()
        """
    )
    assert out["r_down"] is False  # WS down -> no-op
    assert out["r_up"] is True  # same session re-published once WS is up
    assert out["n_up"] == 1
    assert out["topic"] == "session"


def test_session_reemits_after_reset():
    # Regression (Cursor/CodeRabbit/codex P1): a same-session/stint restart calls
    # M.reset(), after which the unchanged session identity must be re-published
    # (else the harness's session->lap sequence misses the restart's session frame).
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local opts = { sim = { currentSessionIndex = 0 }, wsBridge = ws }
          local r1 = M.publishSessionIfChanged(opts)  -- publish
          local r2 = M.publishSessionIfChanged(opts)  -- same key -> suppressed
          M.reset()
          local r3 = M.publishSessionIfChanged(opts)  -- re-published after reset
          return { r1 = r1, r2 = r2, r3 = r3, n = #ws._calls }
        end)()
        """
    )
    assert out["r1"] is True
    assert out["r2"] is False
    assert out["r3"] is True
    assert out["n"] == 2


def test_trackid_prefers_full_id_for_layout():
    # codex P2: multi-layout tracks must be distinguished -> prefer ac.getTrackFullID
    # (track/layout) over the bare ac.getTrackID.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          ac.getTrackFullID = function(_sep) return "ks_brands_hatch/gp" end
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          M.publishSessionIfChanged({ sim = { currentSessionIndex = 0 }, wsBridge = ws })
          return { track = ws._calls[1] and ws._calls[1].payload.track_id }
        end)()
        """
    )
    assert out["track"] == "ks_brands_hatch/gp"


def test_lap_payload_and_stint_best_tracking():
    # best_lap_ms is the producer-tracked min of valid timed laps THIS stint (not the
    # caller's value), and an invalid lap does not update it.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local function lap(n, ms, valid)
            M.publishLap({
              lap = n, lastLapMs = ms, lapsCompleted = n, valid = valid, wsBridge = ws,
            })
          end
          lap(1, 110000, true)   -- best -> 110000
          lap(2, 105000, true)   -- faster -> best 105000
          lap(3, 108000, true)   -- slower -> best stays 105000
          lap(4, 100000, false)  -- invalid -> best stays 105000, last=100000
          local function best(i) return ws._calls[i].payload.best_lap_ms end
          local p4 = ws._calls[4].payload
          return { topic = ws._calls[1].topic, b1 = best(1), b2 = best(2), b3 = best(3),
                   b4 = best(4), last4 = p4.last_lap_ms, valid4 = p4.valid,
                   lap4 = p4.lap, done4 = p4.laps_completed }
        end)()
        """
    )
    assert out["topic"] == "lap"
    assert out["b1"] == 110000
    assert out["b2"] == 105000
    assert out["b3"] == 105000
    assert out["b4"] == 105000  # invalid lap didn't lower the stint best
    assert out["last4"] == 100000
    assert out["valid4"] is False
    assert out["lap4"] == 4
    assert out["done4"] == 4


def test_lap_untimed_boundary_sends_nil_last_lap():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          M.publishLap({ lap = 1, lastLapMs = 0, lapsCompleted = 1, wsBridge = ws })  -- out-lap
          local p = ws._calls[1].payload
          return { last = p.last_lap_ms, best = p.best_lap_ms, valid = p.valid }
        end)()
        """
    )
    assert out["last"] is None  # untimed -> nil, not a fake 0
    assert out["best"] is None  # no valid timed lap yet
    assert out["valid"] is True


def test_lap_stint_best_resets_on_reset():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local function lap(ms)
            M.publishLap({
              lap = 1, lastLapMs = ms, lapsCompleted = 1, valid = true, wsBridge = ws,
            })
          end
          lap(105000)
          M.reset()  -- new stint
          lap(112000)
          return { b1 = ws._calls[1].payload.best_lap_ms, b2 = ws._calls[2].payload.best_lap_ms }
        end)()
        """
    )
    assert out["b1"] == 105000
    assert out["b2"] == 112000  # stint best reset -> the new (slower) lap is the new best


def test_session_reemits_on_ws_reconnect():
    # Regression (codex P2): after a WS down->up reconnect (same identity), the connection
    # heartbeat re-arms `session` so a reconnected tap sees `session` before any `lap`.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local up = { v = true }
          local ws = { _calls = {} }
          ws.publishTopic = function(t, _p) ws._calls[#ws._calls + 1] = t; return up.v end
          local M = require("lifecycle_publisher"); M.reset()
          local sim0 = { currentSessionIndex = 0 }
          M.publishConnectionIfDue({ dt = 1.0, sim = sim0, wsBridge = ws })  -- initial up
          local r1 = M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })  -- publishes
          local r2 = M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })  -- suppressed
          up.v = false
          M.publishConnectionIfDue({ dt = 1.0, sim = sim0, wsBridge = ws })  -- WS down
          up.v = true
          M.publishConnectionIfDue({ dt = 1.0, sim = sim0, wsBridge = ws })  -- reconnect -> re-arm
          local r3 = M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })  -- re-emits
          return { r1 = r1, r2 = r2, r3 = r3 }
        end)()
        """
    )
    assert out["r1"] is True
    assert out["r2"] is False  # same identity, still connected -> suppressed
    assert out["r3"] is True  # reconnect re-armed -> session re-emitted


def test_stint_reset_emits_session_once_not_duplicate():
    # Regression (Cursor on #182 r2-fix): a stint reset with the WS still up must re-emit
    # `session` exactly once. The earlier code reset _lastConnOk=false, so the next heartbeat
    # falsely detected a reconnect and emitted a SECOND (duplicate) session ~1s later.
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local sim0 = { currentSessionIndex = 0 }
          M.publishConnectionIfDue({ dt = 1.0, sim = sim0, wsBridge = ws })  -- initial connect
          M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })  -- session #1
          M.reset()  -- stint reset (WS still up)
          M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })  -- session #2 (intended re-emit)
          -- a due heartbeat (WS still up, not a reconnect) must NOT clear the key:
          M.publishConnectionIfDue({ dt = 1.0, sim = sim0, wsBridge = ws })
          M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })  -- must be SUPPRESSED (no dup)
          local sessions = 0
          for _, c in ipairs(ws._calls) do
            if c.topic == "session" then sessions = sessions + 1 end
          end
          return { sessions = sessions }
        end)()
        """
    )
    assert out["sessions"] == 2  # one initial + one post-reset; NOT a third spurious duplicate


def test_all_producers_noop_when_ws_down():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws_closed()
          local sim0 = { currentSessionIndex = 0 }
          local c = M.publishConnectionIfDue({ dt = 2.0, sim = sim0, wsBridge = ws })
          local s = M.publishSessionIfChanged({ sim = sim0, wsBridge = ws })
          local l = M.publishLap({ lap = 1, wsBridge = ws })
          return { c = c, s = s, l = l }
        end)()
        """
    )
    assert out["c"] is False
    assert out["s"] is False
    assert out["l"] is False


def test_producers_return_false_without_wsbridge():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          return {
            c = M.publishConnectionIfDue({ dt = 2.0 }),
            s = M.publishSessionIfChanged({}),
            l = M.publishLap({ lap = 1 }),
            bad = M.publishLap("not a table"),
          }
        end)()
        """
    )
    assert out["c"] is False
    assert out["s"] is False
    assert out["l"] is False
    assert out["bad"] is False
