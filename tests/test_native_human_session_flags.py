"""CSP SDK observations remain explicit and unknown fields never mean human control."""

from __future__ import annotations

import pytest

from tests.test_lifecycle_publisher import _runtime as lifecycle_runtime
from tests.test_telemetry_publisher import _runtime as telemetry_runtime
from tools.ai_sidecar.external_protocol import make_telemetry_tick, validate_inbound


def test_native_session_republishes_when_live_or_ai_observation_changes():
    rt = lifecycle_runtime()
    values = rt.eval(
        """(function()
          local M = require('lifecycle_publisher'); M.reset()
          local ws = make_ws()
          local sim = {currentSessionIndex=0,isLive=false,isReplayActive=false}
          local car = {isAIControlled=false}
          local opts = {sim=sim,car=car,sessionUuid='fresh',archiveLapN=1,
                        lapTimeMs=0,wsBridge=ws}
          M.publishSessionIfChanged(opts)
          local paused = ws._calls[1].payload
          sim.isLive = true
          M.publishSessionIfChanged(opts)
          local live = ws._calls[2].payload
          car.isAIControlled = true
          M.publishSessionIfChanged(opts)
          local ai = ws._calls[3].payload
          M.publishSessionIfChanged(opts)
          return {n=#ws._calls, paused=paused, live=live, ai=ai}
        end)()"""
    )
    assert values["n"] == 3
    assert values["paused"]["is_live"] is False
    assert values["live"]["is_live"] is True
    assert values["live"]["is_ai"] is False
    assert values["live"]["is_replay"] is False
    assert values["live"]["archive_lap_n"] == 1
    assert values["live"]["lap_time_ms"] == 0
    assert values["ai"]["is_ai"] is True


def test_native_tick_emits_measured_flags_conditions_and_optimum_or_omits_unknown():
    rt = telemetry_runtime()
    values = rt.eval(
        """(function()
          local M = require('telemetry_publisher'); M.reset()
          local ws = make_ws()
          local car = {isAIControlled=false,wheels={[0]={tyreOptimumTemperature=95}}}
          local sim = {isLive=true,isReplayActive=false,ambientTemperature=26,
                       roadTemperature=30,roadGrip=1,weatherType=15}
          M.publishTelemetryTickIfDue({dt=0.1,car=car,sim=sim,wsBridge=ws})
          local observed = ws._calls[1].send.payload
          M.publishTelemetryTickIfDue({dt=0.1,car={},sim={},wsBridge=ws})
          return {observed=observed, unknown=ws._calls[2].send.payload}
        end)()"""
    )
    observed, unknown = values["observed"], values["unknown"]
    assert observed["is_live"] is True and observed["is_ai"] is False
    assert observed["is_replay"] is False
    assert observed["tyre_optimal_temp_c"] == 95
    assert observed["conditions"]["ambientTempC"] == 26
    assert observed["conditions"]["trackTempC"] == 30
    assert observed["conditions"]["trackGripLevel"] == 1
    for field in ("is_live", "is_ai", "is_replay", "tyre_optimal_temp_c", "conditions"):
        assert unknown[field] is None


def test_first_ambiguous_native_ordinal_does_not_swallow_admission_snapshot():
    rt = lifecycle_runtime()
    values = rt.eval(
        """(function()
          local M = require('lifecycle_publisher'); M.reset()
          local ws = make_ws()
          local opts = {sim={currentSessionIndex=0,isLive=true,isReplayActive=false},
                        car={isAIControlled=false},sessionUuid='fresh',
                        lapTimeMs=0,wsBridge=ws}
          M.publishSessionIfChanged(opts)
          opts.archiveLapN = 1
          M.publishSessionIfChanged(opts)
          M.publishSessionIfChanged(opts)
          return {n=#ws._calls, first=ws._calls[1].payload,
                  ready=ws._calls[2].payload}
        end)()"""
    )
    assert values["n"] == 2
    assert values["first"]["archive_lap_n"] is None
    assert values["ready"]["archive_lap_n"] == 1


@pytest.mark.parametrize("flag", ["is_live", "is_ai", "is_replay"])
@pytest.mark.parametrize("invalid", [0, "false", None])
def test_transport_rejects_nonboolean_native_observations(flag, invalid):
    payload = dict(speed_kmh=0, rpm=1000, throttle=0, brake=0, steer=0, gear=0, lat_g=0, long_g=0)
    payload[flag] = invalid
    frame = make_telemetry_tick(payload)
    assert validate_inbound(frame) == f"{flag} requires a boolean"
