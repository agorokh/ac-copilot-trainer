"""Session debrief JSONL → knowledge DB ingest."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.repo_knowledge.schema import apply_schema
from tools.repo_knowledge.session_debrief_ingest import (
    ingest_session_debrief_records,
    load_debrief_records,
    utc_now_iso_z,
)


def test_load_debrief_records_rejects_non_positive_max_age(tmp_path: Path) -> None:
    debrief_dir = tmp_path / ".cache" / "session_debriefs"
    debrief_dir.mkdir(parents=True)
    with pytest.raises(ValueError, match="max_age_days"):
        load_debrief_records(debrief_dir, max_age_days=0, now=datetime.now(UTC))


def test_load_debrief_records_skips_missing_or_bad_ts(tmp_path: Path) -> None:
    debrief_dir = tmp_path / ".cache" / "session_debriefs"
    debrief_dir.mkdir(parents=True)
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    path = debrief_dir / "debrief-2099-01-01.jsonl"
    path.write_text(
        json.dumps({"session_debrief_ci": "no ts"})
        + "\n"
        + json.dumps({"ts": "not-a-date", "session_debrief_ci": "bad"})
        + "\n"
        + json.dumps({"ts": ts, "session_debrief_ci": "ok"})
        + "\n",
        encoding="utf-8",
    )
    recs = load_debrief_records(debrief_dir, max_age_days=30, now=datetime.now(UTC))
    assert len(recs) == 1
    assert recs[0][1].get("session_debrief_ci") == "ok"


def test_load_debrief_records_respects_max_age(tmp_path: Path) -> None:
    debrief_dir = tmp_path / ".cache" / "session_debriefs"
    debrief_dir.mkdir(parents=True)
    old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat().replace("+00:00", "Z")
    new_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    path = debrief_dir / "debrief-2099-01-01.jsonl"
    path.write_text(
        json.dumps({"ts": old_ts, "session_debrief_ci": "x"})
        + "\n"
        + json.dumps({"ts": new_ts, "session_debrief_ci": "y"})
        + "\n",
        encoding="utf-8",
    )
    now = datetime.now(UTC)
    recs = load_debrief_records(debrief_dir, max_age_days=30, now=now)
    assert len(recs) == 1
    ci = recs[0][1].get("session_debrief_ci")
    assert ci == "y"


def test_ingest_session_debrief_idempotent_and_updates_files(tmp_path: Path) -> None:
    debrief_dir = tmp_path / ".cache" / "session_debriefs"
    debrief_dir.mkdir(parents=True)
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    line = {
        "schema_version": 1,
        "ts": ts,
        "session_debrief_files": ["src/foo.py", "README.md"],
        "session_debrief_patterns": ["forgot tests"],
        "session_debrief_mistakes": "left debug print",
    }
    path = debrief_dir / "debrief-2099-01-01.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    db_path = tmp_path / "knowledge.db"
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    now = utc_now_iso_z()
    recs = load_debrief_records(debrief_dir, max_age_days=30, now=datetime.now(UTC))
    a1, s1 = ingest_session_debrief_records(conn, tmp_path, recs, now_iso=now)
    conn.commit()
    assert a1 == 1
    assert s1 == 0

    row = conn.execute(
        "SELECT session_touch_count FROM files WHERE path = ?", ("src/foo.py",)
    ).fetchone()
    assert row is not None
    assert row[0] == 1

    a2, s2 = ingest_session_debrief_records(conn, tmp_path, recs, now_iso=now)
    conn.commit()
    assert a2 == 0
    assert s2 == 1

    row2 = conn.execute(
        "SELECT session_touch_count FROM files WHERE path = ?", ("src/foo.py",)
    ).fetchone()
    assert row2 is not None
    assert row2[0] == 1
    conn.close()


def test_ingest_missing_debrief_dir_is_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.db"
    conn = sqlite3.connect(db_path)
    apply_schema(conn)
    now = utc_now_iso_z()
    a, s = ingest_session_debrief_records(conn, tmp_path, [], now_iso=now)
    assert a == 0
    assert s == 0
    conn.close()
