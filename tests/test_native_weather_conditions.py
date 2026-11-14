"""Native CSP weather enums reach the same strict gate as legacy weather names."""

from __future__ import annotations

from copy import deepcopy

import pytest

from tools.ai_sidecar.coaching_runtime import practice_archive_conditions, practice_frame_conditions
from tools.ai_sidecar.conditions_model import analyze_conditions, normalize_weather_type


@pytest.mark.parametrize("code", [15, 16, 17, 18, 19, 21])
def test_known_csp_dry_weather_is_read_without_rewriting_raw_observations(code):
    conditions = {"weatherType": code, "trackGripLevel": 1.0}
    before = deepcopy(conditions)
    result = analyze_conditions(conditions)
    assert result.regime == "dry"
    assert result.weather == normalize_weather_type(code)
    assert conditions == before


@pytest.mark.parametrize("code", [*range(15), 32])
def test_known_precipitation_codes_disable_the_dry_slick_model(code):
    report = analyze_conditions({"weatherType": code, "trackGripLevel": 1.0})
    assert report.regime == "wet" and not report.slick_model_valid
    assert any(finding.key == "wet_regime" for finding in report.findings)


@pytest.mark.parametrize(
    "code", [True, False, None, -1, 33, 999, 15.1, float("nan"), float("inf"), "15"]
)
def test_unknown_or_malformed_enum_cannot_become_dry(code):
    assert analyze_conditions({"weatherType": code}).regime == "unknown"


def test_native_numeric_and_legacy_names_share_live_and_archive_gating():
    from tests.test_coaching_practice_bootstrap import _scoped_raw_reference

    frame = {
        "tyre_temps_c": dict.fromkeys(("fl", "fr", "rl", "rr"), 90.0),
        "brake_temps_c": dict.fromkeys(("fl", "fr", "rl", "rr"), 100.0),
        "tyre_optimal_temp_c": 90.0,
        "conditions": {"weatherType": 15, "trackGripLevel": 1.0},
    }
    archive = _scoped_raw_reference(1)
    for weather, allowed, reason in (
        (15, True, ""),
        (15.0, True, ""),
        ("clear", True, ""),
        (7, False, "wet_regime"),
        ("rain", False, "wet_regime"),
        (999, False, "thermal_evidence_required"),
    ):
        frame["conditions"]["weatherType"] = weather
        archive["conditions"]["weatherType"] = weather
        before = deepcopy((frame, archive))
        assert practice_frame_conditions({"payload": frame}) == (allowed, reason)
        assert practice_archive_conditions(archive) is allowed
        assert (frame, archive) == before


def test_real_lua_tick_weather_enum_reaches_the_strict_python_consumer():
    from tests.test_telemetry_publisher import _runtime

    runtime = _runtime()
    lua_frame = runtime.eval(
        """(function()
          local M = require('telemetry_publisher'); M.reset()
          local ws = make_ws()
          local wheels = {}
          for i=0,3 do wheels[i] = {discTemperature=100,tyreOptimumTemperature=90} end
          M.publishTelemetryTickIfDue({dt=0.1,car={wheels=wheels,isAIControlled=false},
            sim={isLive=true,isReplayActive=false,weatherType=15,roadGrip=1,
                 ambientTemperature=26,roadTemperature=30},
            temps={fl=90,fr=90,rl=90,rr=90},wsBridge=ws})
          return ws._calls[1].send
        end)()"""
    )

    def plain(value):
        return (
            {key: plain(item) for key, item in value.items()} if hasattr(value, "items") else value
        )

    frame = plain(lua_frame)
    assert frame["payload"]["conditions"]["weatherType"] == 15
    assert frame["payload"]["conditions"]["trackGripLevel"] == 1
    assert frame["payload"]["conditions"]["trackTempC"] == 30
    assert practice_frame_conditions(frame) == (True, "")
    assert frame["payload"]["conditions"]["weatherType"] == 15
