"""#675 Part 2 — between-lap corner_advice selection (fail-closed validation)."""

from __future__ import annotations

from tools.ai_sidecar.coaching.between_lap import (
    select_between_lap_advice,
    select_focus_corner,
    validate_corner_advice,
)
from tools.ai_sidecar.coaching_diagnosis import Diagnosis, RootError
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.track_reference import CornerReference


def _refs(*indexes: int) -> list[CornerReference]:
    out = []
    for i, idx in enumerate(indexes):
        lo = 0.1 * (i + 1)
        out.append(
            CornerReference(
                index=idx,
                spline_lo=lo,
                spline_hi=lo + 0.05,
                apex_spline=lo + 0.02,
                optimal_apex_kmh=100.0,
            )
        )
    return out


def test_validate_rejects_unknown_corner() -> None:
    refs = _refs(0, 1)
    assert validate_corner_advice(corner=9, text="BRAKE LATER NEXT LAP", refs=refs) is None
    assert validate_corner_advice(corner=1, text="ok", refs=refs) is None  # too short
    ok = validate_corner_advice(corner=1, text="BRAKE LATER NEXT LAP", refs=refs)
    assert ok is not None and ok["corner"] == 1 and ok["corner_label"] == "T1"


def test_select_focus_prefers_ledger_focus() -> None:
    ledger = CoachingLedger(hysteresis=1, assess_laps=0, lap_budget=4)
    ledger.begin_lap(1)
    ledger.record_pass(2, Diagnosis(RootError.EARLY_BRAKE, {}), time_lost_s=0.4, valid=True)
    ledger.record_pass(0, Diagnosis(RootError.SLOW_APEX, {}), time_lost_s=0.1, valid=True)
    assert select_focus_corner(ledger, valid_corners=[0, 1, 2]) == 2


def test_select_between_lap_rules_fallback_without_ollama(monkeypatch) -> None:
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "0")
    refs = _refs(0, 1, 2)
    ledger = CoachingLedger(hysteresis=1, assess_laps=0, lap_budget=4)
    ledger.begin_lap(1)
    ledger.record_pass(1, Diagnosis(RootError.EARLY_BRAKE, {}), time_lost_s=0.5, valid=True)
    advice = select_between_lap_advice(refs=refs, ledger=ledger, use_ollama=False)
    assert advice is not None
    assert advice["corner"] == 1
    assert "T1" in advice["text"] or "NEXT LAP" in advice["text"]


def test_select_between_lap_uses_ranking_when_ledger_empty(monkeypatch) -> None:
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "0")
    refs = _refs(0, 3)
    advice = select_between_lap_advice(
        refs=refs,
        ledger=None,
        improvement_ranking=[{"corner": 3, "suggestion": "carry more"}],
        use_ollama=False,
    )
    assert advice is not None and advice["corner"] == 3
