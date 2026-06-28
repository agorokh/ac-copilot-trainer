"""Integration tests for the tt_ingest retention pipeline + CLI parser (issue #353).

``retain_sessions`` is the local, network-free heart of ``export``: given already
fetched raw sessions it normalizes, immutably retains, and indexes them. These tests
drive it against the sanitized fixture and a ``tmp_path`` lake.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tt_ingest.cli import (
    INDEX_FILENAME,
    SESSIONS_INDEX_FILENAME,
    build_arg_parser,
    retain_sessions,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tt_sessions_page.json"


def _sessions() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["sessions"]


# --- retain_sessions end-to-end ---------------------------------------------------


def test_retain_sessions_writes_lake_tree(tmp_path) -> None:
    summary = retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    root = tmp_path / "journal" / "tt"
    assert summary.total == 3
    assert summary.retained_new == 3
    assert summary.skipped_existing == 0
    assert summary.lake_root == root

    # Raw session retained at the car/track/session path.
    raw = (
        root
        / "assettoCorsa"
        / "syn_mercedes_w09"
        / "ks_red_bull_ring"
        / "sess-aaa"
        / "session.json"
    )
    assert raw.exists()
    assert json.loads(raw.read_text())["id"] == "fake-uid-001#sess-aaa"

    # Both indexes present.
    sessions_index = json.loads((root / SESSIONS_INDEX_FILENAME).read_text())
    assert sessions_index["session_count"] == 3
    file_index = json.loads((root / INDEX_FILENAME).read_text())
    assert file_index["file_count"] == 3
    assert all("sha256" in f for f in file_index["files"])


def test_retain_sessions_is_immutable_on_rerun(tmp_path) -> None:
    retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    # Second run: same raw sessions are already present → all skipped, none re-written.
    summary = retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-29T00:00:00Z")
    assert summary.total == 3
    assert summary.retained_new == 0
    assert summary.skipped_existing == 3


def test_retain_sessions_summary_render(tmp_path) -> None:
    summary = retain_sessions(_sessions(), lake_base=tmp_path)
    rendered = summary.render()
    assert "retained 3 session(s)" in rendered
    assert "3 new" in rendered


def test_retain_sessions_empty(tmp_path) -> None:
    summary = retain_sessions([], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    assert summary.total == 0
    root = tmp_path / "journal" / "tt"
    assert (root / SESSIONS_INDEX_FILENAME).exists()
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 0


# --- argument parser --------------------------------------------------------------


def test_parser_export_defaults() -> None:
    args = build_arg_parser().parse_args(["export"])
    assert args.command == "export"
    assert args.limit == 50
    assert args.dry_run is False
    assert args.overwrite is False


def test_parser_export_flags() -> None:
    args = build_arg_parser().parse_args(
        ["export", "--limit", "10", "--max-pages", "2", "--dry-run", "--uid", "u9"]
    )
    assert args.limit == 10
    assert args.max_pages == 2
    assert args.dry_run is True
    assert args.uid == "u9"


def test_parser_auth_check() -> None:
    args = build_arg_parser().parse_args(["auth-check"])
    assert args.command == "auth-check"


def test_parser_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args([])


# --- regression tests for the PR-359 adversarial-review fixes ----------------------


def test_retain_sessions_idless_sessions_do_not_collide(tmp_path) -> None:
    # Two DISTINCT sessions both lacking a usable id must NOT collapse onto one lake path
    # (the old 'unknown_session' single bucket silently dropped the second + corrupted the index).
    s1 = {"car_id": "c", "track_id": "t", "game_id": "g", "bestLapTime": 1000}
    s2 = {"car_id": "c", "track_id": "t", "game_id": "g", "bestLapTime": 2000}
    summary = retain_sessions([s1, s2], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    assert summary.total == 2
    assert summary.retained_new == 2  # both retained — no silent drop
    root = tmp_path / "journal" / "tt"
    assert len(list(root.rglob("session.json"))) == 2  # two distinct raw files on disk
    file_index = json.loads((root / INDEX_FILENAME).read_text())
    assert file_index["file_count"] == 2
    # Distinct sha256 per session — the first file's hash is never mis-attributed to the second.
    assert len({f["sha256"] for f in file_index["files"]}) == 2


def test_retain_sessions_keeps_nan_session_and_whole_batch(tmp_path) -> None:
    good = {"id": "u#a", "car_id": "c", "track_id": "t", "game_id": "g"}
    nan_session = {
        "id": "u#b",
        "car_id": "c",
        "track_id": "t",
        "game_id": "g",
        "lap_attributes": {"fuelLevel": float("nan")},
    }
    after = {"id": "u#c", "car_id": "c", "track_id": "t", "game_id": "g"}
    summary = retain_sessions(
        [good, nan_session, after], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z"
    )
    # A non-finite telemetry float must NOT abort the batch or skip the indexes.
    assert summary.total == 3
    assert summary.failed == 0
    root = tmp_path / "journal" / "tt"
    assert (root / SESSIONS_INDEX_FILENAME).exists()
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 3


def test_retain_sessions_guards_unserializable_session(tmp_path) -> None:
    good = {"id": "u#a", "car_id": "c", "track_id": "t", "game_id": "g"}
    # A set is not JSON-serializable (even with allow_nan): the per-session write raises, but the
    # guard must keep the rest of the batch and still write both indexes.
    bad = {"id": "u#b", "car_id": "c", "track_id": "t", "game_id": "g", "weird": {1, 2, 3}}
    summary = retain_sessions([good, bad], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    assert summary.failed == 1
    assert summary.total == 1  # only the good session retained
    assert "1 session(s) skipped due to errors" in summary.render()
    root = tmp_path / "journal" / "tt"
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 1
    assert json.loads((root / SESSIONS_INDEX_FILENAME).read_text())["session_count"] == 1
