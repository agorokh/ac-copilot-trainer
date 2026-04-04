"""Lap feature extraction and improvement ranking (issue #49)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sidecar.features import _as_float, extract_corner_table
from tools.ai_sidecar.improvement_ranking import rank_corner_improvements
from tools.ai_sidecar.protocol import EVENT_COACHING_RESPONSE, prepare_outbound_message
from tools.ai_sidecar.server import _run_compare_laps
from tools.ai_sidecar.session import LapComparisonState

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_extract_corner_table_fixture() -> None:
    raw = json.loads((_FIXTURES / "lap_sidecar_ref.json").read_text(encoding="utf-8"))
    t = extract_corner_table(raw)
    assert t[1]["min_speed_kmh"] == 55.0
    assert t[2]["apex_speed_kmh"] == 102.0


def test_rank_corner_improvements_orders_by_regret() -> None:
    last = json.loads((_FIXTURES / "lap_sidecar_last.json").read_text(encoding="utf-8"))
    ref = json.loads((_FIXTURES / "lap_sidecar_ref.json").read_text(encoding="utf-8"))
    ranked = rank_corner_improvements(
        extract_corner_table(last),
        extract_corner_table(ref),
    )
    assert len(ranked) >= 2
    priorities = [r["priority"] for r in ranked]
    assert priorities == sorted(priorities, reverse=True)
    assert "suggestion" in ranked[0]
    assert ranked[0]["metric"] in ("min_speed_kmh", "apex_speed_kmh")


def test_prepare_outbound_attaches_improvement_ranking_after_slower_lap() -> None:
    state = LapComparisonState()
    ref = json.loads((_FIXTURES / "lap_sidecar_ref.json").read_text(encoding="utf-8"))
    last = json.loads((_FIXTURES / "lap_sidecar_last.json").read_text(encoding="utf-8"))

    first = prepare_outbound_message(ref, reply_coaching=True, lap_state=state)
    assert first is not None
    assert first["event"] == EVENT_COACHING_RESPONSE
    assert "improvementRanking" not in first

    second = prepare_outbound_message(last, reply_coaching=True, lap_state=state)
    assert second is not None
    imp = second.get("improvementRanking")
    assert isinstance(imp, list)
    assert len(imp) >= 1


def test_compare_laps_cli_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    _run_compare_laps(
        str(_FIXTURES / "lap_sidecar_last.json"),
        str(_FIXTURES / "lap_sidecar_ref.json"),
    )
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert data
    assert data[0]["corner"] in (1, 2)


def test_extract_corner_table_ignores_unknown_and_malformed() -> None:
    assert extract_corner_table({}) == {}
    assert extract_corner_table({"telemetry": "bad"}) == {}
    assert extract_corner_table({"telemetry": {"corners": [{"id": 1, "brakeDistanceM": 10}]}}) == {}
    assert extract_corner_table(
        {"telemetry": {"corners": [{"id": "x"}, {}, {"id": 3, "min_speed_kmh": 40}]}}
    ) == {3: {"min_speed_kmh": 40.0}}


def test_rank_corner_improvements_empty_when_no_regressions() -> None:
    ref = json.loads((_FIXTURES / "lap_sidecar_ref.json").read_text(encoding="utf-8"))
    t = extract_corner_table(ref)
    assert rank_corner_improvements(t, t) == []


def test_new_pb_lap_emits_no_improvement_ranking() -> None:
    state = LapComparisonState()
    slow = json.loads((_FIXTURES / "lap_sidecar_last.json").read_text(encoding="utf-8"))
    fast = json.loads((_FIXTURES / "lap_sidecar_ref.json").read_text(encoding="utf-8"))
    assert state.improvement_ranking_for(slow) == []
    assert state.improvement_ranking_for(fast) == []


def test_lap_time_true_is_ignored_for_pb() -> None:
    state = LapComparisonState()
    payload = {
        "lapTimeMs": True,
        "telemetry": {"corners": [{"id": 1, "minSpeedKmh": 50}]},
    }
    assert state.improvement_ranking_for(payload) == []


def test_as_float_rejects_non_finite() -> None:
    assert _as_float(float("nan")) is None
    assert _as_float(float("inf")) is None


def test_as_float_rejects_bool() -> None:
    assert _as_float(True) is None
    assert _as_float(False) is None


def test_compare_laps_invalid_json_exits(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit, match="compare-laps: invalid JSON"):
        _run_compare_laps(str(bad), str(bad))


def test_lap_comparison_state_skips_pb_without_lap_time() -> None:
    state = LapComparisonState()
    payload = {
        "protocol": 1,
        "event": "lap_complete",
        "lap": 1,
        "telemetry": {"corners": [{"id": 1, "minSpeedKmh": 50}]},
    }
    assert state.improvement_ranking_for(payload) == []
    assert state.improvement_ranking_for(payload) == []


def test_server_main_compare_laps(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    last = _FIXTURES / "lap_sidecar_last.json"
    ref = _FIXTURES / "lap_sidecar_ref.json"
    monkeypatch.setattr("sys.argv", ["x", "--compare-laps", str(last), str(ref)])
    from tools.ai_sidecar import server

    server.main()
    out = capsys.readouterr().out
    ranking = json.loads(out)
    assert isinstance(ranking, list)
    assert ranking
    assert ranking[0]["suggestion"]
