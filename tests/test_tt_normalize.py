"""Unit tests for tools.tt_ingest.tt_normalize (issue #353)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tt_ingest.tt_normalize import (
    INDEX_SCHEMA_VERSION,
    build_sessions_index,
    normalize_session,
    normalize_sessions,
    split_session_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tt_sessions_page.json"


def _sessions() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["sessions"]


def test_split_session_id() -> None:
    assert split_session_id("uid-1#sess-aaa") == ("uid-1", "sess-aaa")
    assert split_session_id("no-sep") == (None, None)
    assert split_session_id(123) == (None, None)


def test_normalize_session_full_row() -> None:
    row = normalize_session(_sessions()[0])
    assert row["session_id"] == "fake-uid-001#sess-aaa"
    assert row["uid"] == "fake-uid-001"
    assert row["session_key"] == "sess-aaa"
    assert row["car_id"] == "syn_mercedes_w09"
    assert row["car_name"] == "Mercedes W09"
    assert row["track_id"] == "ks_red_bull_ring"
    assert row["best_lap_ms"] == 64321
    assert row["lap_count"] == 12
    assert row["game_name"] == "Assetto Corsa"


def test_normalize_session_lifts_conditions() -> None:
    row = normalize_session(_sessions()[0])
    cond = row["conditions"]
    assert cond["airTemp"] == 24.0
    assert cond["tyreCompound"] == "Pirelli SuperSoft (SS)"
    assert cond["carSetupName"] == "quali"
    assert cond["isFixedSetup"] is False
    assert cond["trackGrip"] == 0.98


def test_normalize_session_degrades_missing_fields() -> None:
    row = normalize_session(_sessions()[2])  # minimal session
    assert row["car_id"] == "ks_abarth500"
    assert row["best_lap_ms"] is None
    assert row["lap_count"] is None
    assert row["car_name"] is None
    # conditions keys all present but None when lap_attributes absent
    assert row["conditions"]["airTemp"] is None
    assert set(row["conditions"]).issuperset({"airTemp", "tyreCompound", "trackGrip"})


def test_normalize_session_uid_from_user_id_when_id_unusable() -> None:
    row = normalize_session({"car_id": "c", "user_id": "uid-only"})
    assert row["uid"] == "uid-only"
    assert row["session_id"] is None


def test_normalize_session_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        normalize_session("not a mapping")


def test_normalize_sessions_skips_non_mappings() -> None:
    rows = normalize_sessions([_sessions()[0], "garbage", 7, _sessions()[1]])
    assert len(rows) == 2


def test_build_sessions_index() -> None:
    rows = normalize_sessions(_sessions())
    index = build_sessions_index(rows, generated_at="2026-06-28T00:00:00Z")
    assert index["index_schema_version"] == INDEX_SCHEMA_VERSION
    assert index["session_count"] == 3
    assert index["generated_at"] == "2026-06-28T00:00:00Z"
    assert len(index["sessions"]) == 3
