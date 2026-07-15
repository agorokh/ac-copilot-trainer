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


def test_telemetry_tick_carries_fuel_and_tyre_temps_when_available():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = {
            speedKmh = 120, rpm = 6000, gas = 0.5, brake = 0.0, steer = 0.1,
            gear = 3, splinePosition = 0.42, lapCount = 2, fuel = 18.5, fuelCapacity = 60,
          }
          M.publishTelemetryTickIfDue({
            dt = 0.06, car = car, wsBridge = ws,
            temps = { fl = 85, fr = 86, rl = 83, rr = 84 },
          })
          local p = ws._calls[1] and ws._calls[1].send.payload
          return {
            fuel = p and p.fuel_l,
            capacity = p and p.fuel_capacity_l,
            fl = p and p.tyre_temps_c and p.tyre_temps_c.fl,
            rr = p and p.tyre_temps_c and p.tyre_temps_c.rr,
          }
        end)()
        """
    )
    assert out["fuel"] == 18.5
    assert out["capacity"] == 60
    assert (out["fl"], out["rr"]) == (85, 84)


def test_telemetry_tick_carries_rpm_max_and_lap_time_when_available():
    """#531 Part C-min: the tablet dashboard's shift ribbon bands from the car's REAL
    redline (`car.rpmLimiter`) and the lap clock reads `car.lapTimeMs` — both optional
    (a CSP build lacking the field omits the key), never hardcoded."""
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = {
            speedKmh = 120, rpm = 6000, gas = 0.5, brake = 0.0, steer = 0.1,
            gear = 3, splinePosition = 0.42, lapCount = 2,
            rpmLimiter = 8500, lapTimeMs = 62410,
          }
          M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].send.payload
          return { rpm_max = p and p.rpm_max, lap_time_ms = p and p.lap_time_ms }
        end)()
        """
    )
    assert out["rpm_max"] == 8500
    assert out["lap_time_ms"] == 62410


def test_telemetry_tick_omits_rpm_max_when_missing_or_zero():
    """A zero/absent limiter means "unknown", not a real redline — the key must be
    omitted so the dashboard renders an explicit unknown instead of a fake band."""
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = {
            speedKmh = 120, rpm = 6000, gas = 0.5, brake = 0.0, steer = 0.1,
            gear = 3, splinePosition = 0.42, lapCount = 2, rpmLimiter = 0,
          }
          M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].send.payload
          return { has_rpm_max = p.rpm_max ~= nil, has_lap_time = p.lap_time_ms ~= nil }
        end)()
        """
    )
    assert out["has_rpm_max"] is False
    assert out["has_lap_time"] is False


def test_telemetry_tick_carries_wheel_vitals_and_intervention_flags():
    """#531 Part D: the live vitals the tablet tyre board reads (pressure/brake-temp/wear) plus
    the TC/ABS intervention flags. CSP field names are the finicky part — `tyrePressure`,
    `discTemperature`, `tyreWear` (NOT the SimHub/ACC `brakeTemperature` spelling) — and wheels
    are 0-BASED (FL=0..RR=3); a 1-based read silently shifts every corner (the #180 regression)."""
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local function wheel(psi, disc, wear)
            return { tyrePressure = psi, discTemperature = disc, tyreWear = wear }
          end
          local car = {
            speedKmh = 120, rpm = 6000, gas = 0.5, brake = 1.0, steer = 0.1,
            gear = 3, splinePosition = 0.42, lapCount = 2,
            tractionControlInAction = true, absInAction = false,
            wheels = {
              [0] = wheel(27.4, 310, 0.98), [1] = wheel(27.6, 312, 0.97),
              [2] = wheel(26.1, 280, 0.99), [3] = wheel(26.3, 282, 0.96),
            },
          }
          M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          local p = ws._calls[1] and ws._calls[1].send.payload
          return {
            psi_fl = p.tyre_pressures_psi and p.tyre_pressures_psi.fl,
            psi_rr = p.tyre_pressures_psi and p.tyre_pressures_psi.rr,
            disc_fl = p.brake_temps_c and p.brake_temps_c.fl,
            disc_rr = p.brake_temps_c and p.brake_temps_c.rr,
            tc = p.tc_active, abs = p.abs_active,
          }
        end)()
        """
    )
    assert (out["psi_fl"], out["psi_rr"]) == (27.4, 26.3)
    # RR is read from wheels[3]: a 1-based loop would read nil here and drop the corner.
    assert (out["disc_fl"], out["disc_rr"]) == (310, 282)
    assert out["tc"] is True
    assert out["abs"] is False


def test_telemetry_tick_wear_pct_is_consumed_not_condition():
    """CSP `tyreWear` is 0..1 wear CONSUMED (0.0 = new, growing with use), matching the wire's
    `tyre_wear_pct` (0 = new, 100 = gone) — a plain x100, NO inversion.

    Direction rig-verified 2026-07-14 across 321 lap archives (4 cars): every nonzero corner fell
    in 0.000268..0.0720, growing from an exact 0.0 on a new set. The SDK's "from 0 to 1" is
    direction-ambiguous, and reading it as condition-remaining inverts a NEW tyre to 100 —
    which `race_management._tyre_advisory` turns into a "tyre wear is high" voice cue on lap one.
    This test pins the measured direction so that inversion cannot be reintroduced.
    """
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = {
            speedKmh = 120, rpm = 6000, gas = 0.5, brake = 0.0, steer = 0.0,
            gear = 3, splinePosition = 0.42, lapCount = 2,
            wheels = {
              [0] = { tyreWear = 0.0 },     -- brand new (the observed value on a fresh set)
              [1] = { tyreWear = 0.072 },   -- the worst corner seen across 321 rig archives
              [2] = { tyreWear = 0.75 },    -- a heavily used set
              [3] = { tyreWear = 1.0 },     -- fully consumed
            },
          }
          M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          local w = ws._calls[1].send.payload.tyre_wear_pct
          return { fl = w.fl, fr = w.fr, rl = w.rl, rr = w.rr }
        end)()
        """
    )
    assert out["fl"] == 0.0  # a NEW tyre must report 0% consumed -> never trips the >=70 cue
    assert abs(out["fr"] - 7.2) < 1e-9  # matches reference_mock.html's illustrative "7% wear"
    assert out["rl"] == 75.0
    assert out["rr"] == 100.0


def test_telemetry_tick_omits_vitals_and_flags_when_car_lacks_them():
    """Sentinel discipline: a CSP build/car with no wheel struct or no TC/ABS physics flags must
    OMIT the keys so the dashboard renders an explicit unknown — never an empty map (which Lua
    would serialize as `{}` and the board would read as live-but-blank) and never a defaulted
    `false` (which would claim "present and idle" for a system the car does not have)."""
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local M = require("telemetry_publisher"); M.reset()
          local ws = make_ws()
          local car = {
            speedKmh = 10, rpm = 900, gas = 0, brake = 0, steer = 0,
            gear = 1, splinePosition = 0.1, lapCount = 0,
          }
          M.publishTelemetryTickIfDue({ dt = 0.06, car = car, wsBridge = ws })
          local p = ws._calls[1].send.payload
          return {
            psi = p.tyre_pressures_psi ~= nil, disc = p.brake_temps_c ~= nil,
            wear = p.tyre_wear_pct ~= nil, tc = p.tc_active ~= nil, abs = p.abs_active ~= nil,
          }
        end)()
        """
    )
    assert out["psi"] is False
    assert out["disc"] is False
    assert out["wear"] is False
    assert out["tc"] is False
    assert out["abs"] is False


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


def test_entry_isolates_tire_stream_from_optional_delta_failures():
    """A reference/delta exception must not suppress the always-on tyre stream."""
    entry = (REPO / "src" / "ac_copilot_trainer" / "ac_copilot_trainer.lua").read_text(
        encoding="utf-8"
    )
    delta_start = entry.index("-- Issue #180 Part D step 2: telemetry topics")
    tyre_start = entry.index("-- Keep the always-on tyre/tick streams", delta_start)
    next_section = entry.index("-- Round 10: drain any corner_advice", tyre_start)

    delta_block = entry[delta_start:tyre_start]
    tyre_block = entry[tyre_start:next_section]
    assert "publishDeltaIfDue" in delta_block
    assert "publishTireTempsIfDue" not in delta_block
    assert "pcall(function()" in tyre_block
    assert "publishTireTempsIfDue" in tyre_block
