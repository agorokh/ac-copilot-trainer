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


def test_lap_publishes_payload_with_validity():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          local r = M.publishLap({ lap = 3, lastLapMs = 91234, bestLapMs = 90000,
                                   lapsCompleted = 2, valid = false, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].payload
          return { r = r, n = #ws._calls, topic = ws._calls[1] and ws._calls[1].topic,
                   lap = p and p.lap, last = p and p.last_lap_ms, best = p and p.best_lap_ms,
                   done = p and p.laps_completed, valid = p and p.valid }
        end)()
        """
    )
    assert out["r"] is True
    assert out["n"] == 1
    assert out["topic"] == "lap"
    assert out["lap"] == 3
    assert out["last"] == 91234
    assert out["best"] == 90000
    assert out["done"] == 2
    assert out["valid"] is False


def test_lap_defaults_to_valid_when_unspecified():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("lifecycle_publisher"); M.reset()
          local ws = make_ws()
          M.publishLap({ lap = 1, wsBridge = ws })
          return { valid = ws._calls[1].payload.valid }
        end)()
        """
    )
    assert out["valid"] is True  # missing `valid` -> treated as a valid lap


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
