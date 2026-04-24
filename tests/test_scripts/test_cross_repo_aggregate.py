"""Tests for ``scripts/cross_repo_aggregate.py`` env parsing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_cross_repo_aggregate():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "cross_repo_aggregate.py"
    spec = importlib.util.spec_from_file_location("cross_repo_aggregate", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("value", "expected_ok", "expect_err_substr"),
    [
        ("30", True, None),
        ("0", True, None),
        ("nan", False, "finite"),
        ("inf", False, "finite"),
        ("-1", False, ">="),
        ("not-a-number", False, "number"),
    ],
)
def test_parse_days_env(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected_ok: bool,
    expect_err_substr: str | None,
) -> None:
    mod = _load_cross_repo_aggregate()
    monkeypatch.setenv("MINING_DAYS", value)
    days, err = mod._parse_days_env()
    if expected_ok:
        assert err is None
        assert days == int(float(value))
    else:
        assert days is None
        assert err is not None
        assert expect_err_substr in err


def test_fleet_vault_summary_rolls_up_scores() -> None:
    mod = _load_cross_repo_aggregate()
    per_repo = {
        "a": {
            "vault_health": {
                "health_score": 80,
                "node_count": 10,
                "coverage_gaps": ["g1"],
            }
        },
        "b": {
            "vault_health": {
                "health_score": 60,
                "node_count": 5,
                "coverage_gaps": [],
            }
        },
        "skip": {"vault_health": {"error": "no token"}},
    }
    s = mod._fleet_vault_summary(per_repo)
    assert s is not None
    assert s["repos_scored"] == 2
    assert s["avg_health_score"] == 70.0
    assert s["min_health_score"] == 60
    assert s["max_health_score"] == 80
    assert s["avg_node_count"] == 7.5
    assert s["total_coverage_gap_hints"] == 1
    assert s["rankings"] == [
        {"repo": "a", "health_score": 80},
        {"repo": "b", "health_score": 60},
    ]
    assert s["coverage_gap_patterns"] == {"g1": 1}


def test_fleet_vault_summary_empty_returns_none() -> None:
    mod = _load_cross_repo_aggregate()
    assert mod._fleet_vault_summary({}) is None
    assert mod._fleet_vault_summary({"x": {}}) is None
