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
    COACHING_ENDPOINT,
    INDEX_FILENAME,
    LAST_SESSION_ENDPOINT,
    SESSIONS_INDEX_FILENAME,
    build_arg_parser,
    retain_coaching,
    retain_sessions,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tt_sessions_page.json"
LAST_SESSION_FIXTURE = Path(__file__).parent / "fixtures" / "tt_services_last_session.json"


def _sessions() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["sessions"]


def _last_session() -> dict:
    return json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))["data"]["session"]


def _bundle() -> dict:
    return {
        "reference_lap": {"username": "Reference Driver", "lap_time": "71035"},
        "reference_id": ["ref-uid-002", "20220611194228"],
        "segments": [
            {"segment": 1, "stories": [{"diagnosis": "Brake later", "time_loss": 0.12}]},
            {"segment": 2, "stories": [{"diagnosis": "Good corner", "time_loss": 0.0}]},
        ],
    }


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


def test_parser_coaching_defaults() -> None:
    args = build_arg_parser().parse_args(["coaching"])
    assert args.command == "coaching"
    assert args.segment_count == 7
    assert args.session_key is None
    assert args.lap is None
    assert args.dry_run is False


def test_parser_coaching_flags() -> None:
    args = build_arg_parser().parse_args(
        ["coaching", "--session-key", "20260629005756", "--lap", "5", "--segment-count", "3"]
    )
    assert args.session_key == "20260629005756"
    assert args.lap == 5
    assert args.segment_count == 3


# --- retain_coaching (M-TT1) ------------------------------------------------------


def test_retain_coaching_writes_lake(tmp_path) -> None:
    summary = retain_coaching(_last_session(), _bundle(), lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    session_dir = root / "assettoCorsa" / "ks_porsche_911_gt3_r_2016" / "magione" / "20260629005756"
    assert (session_dir / f"{LAST_SESSION_ENDPOINT}.json").exists()
    coaching = json.loads((session_dir / f"{COACHING_ENDPOINT}.json").read_text())
    assert coaching["reference_lap"]["username"] == "Reference Driver"
    assert summary.segments == 2
    assert summary.actionable == 1  # only the 0.12s loss is actionable; the 0.0 is not
    assert set(summary.written) == {LAST_SESSION_ENDPOINT, COACHING_ENDPOINT}


def test_retain_coaching_is_write_once(tmp_path) -> None:
    retain_coaching(_last_session(), _bundle(), lake_base=tmp_path)
    again = retain_coaching(_last_session(), _bundle(), lake_base=tmp_path)
    assert again.written == []  # both endpoints already present → nothing re-written
    assert "nothing new" in again.render()


def test_retain_coaching_summary_render(tmp_path) -> None:
    rendered = retain_coaching(_last_session(), _bundle(), lake_base=tmp_path).render()
    assert "session 20260629005756" in rendered
    assert "2 segment(s)" in rendered
    assert "1 actionable" in rendered


def test_retain_coaching_preserves_full_payload(tmp_path) -> None:
    # The FULL services payload (session + referenceLap + telemetry) must be retained as
    # last_session.json so the lake reconstructs what the endpoint returned (M-TT2 input).
    full = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    retain_coaching(_last_session(), _bundle(), last_session_payload=full, lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    session_dir = root / "assettoCorsa" / "ks_porsche_911_gt3_r_2016" / "magione" / "20260629005756"
    retained = json.loads((session_dir / f"{LAST_SESSION_ENDPOINT}.json").read_text())
    assert retained.get("success") is True  # envelope preserved, not the stripped session
    assert "referenceLap" in retained["data"]  # reference evidence kept for M-TT2


def test_retain_coaching_indexes_endpoint_files(tmp_path) -> None:
    summary = retain_coaching(_last_session(), _bundle(), lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    file_index = json.loads((root / INDEX_FILENAME).read_text())
    endpoints = {f["endpoint"] for f in file_index["files"]}
    assert {LAST_SESSION_ENDPOINT, COACHING_ENDPOINT} <= endpoints
    assert summary.indexed == file_index["file_count"] >= 2


def test_retain_coaching_keys_on_given_session(tmp_path) -> None:
    # The lake key comes from the GIVEN session, so coaching for an OLD session lands under
    # that session's dir (PR #370 review fix — not the latest session's).
    old = {
        "session_id": "u#20240101120000",
        "game_id": "assettoCorsa",
        "car": "ks_audi_r8_lms",
        "track_id": "monza",
        "lap_number": 3,
    }
    retain_coaching(old, _bundle(), lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    assert (
        root
        / "assettoCorsa"
        / "ks_audi_r8_lms"
        / "monza"
        / "20240101120000"
        / f"{COACHING_ENDPOINT}.json"
    ).exists()


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


def test_retain_sessions_partial_export_preserves_index(tmp_path) -> None:
    # A later partial export must NOT shrink the discovery index: the index is a derived
    # view of the WHOLE lake on disk, not of one batch (regression for index-rebuild bug).
    retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    extra = {"id": "u#new", "car_id": "c", "track_id": "t", "game_id": "g"}
    summary = retain_sessions([extra], lake_base=tmp_path, generated_at="2026-06-29T00:00:00Z")
    assert summary.total == 1  # this batch processed one session...
    assert summary.indexed == 4  # ...but the index covers all 4 raw files on disk
    root = tmp_path / "journal" / "tt"
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 4
    assert json.loads((root / SESSIONS_INDEX_FILENAME).read_text())["session_count"] == 4


def test_retain_sessions_raw_is_write_once_and_index_matches_disk(tmp_path) -> None:
    s = {"id": "u#a", "car_id": "c", "track_id": "t", "game_id": "g", "bestLapTime": 1000}
    retain_sessions([s], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    root = tmp_path / "journal" / "tt"
    raw_path = next(root.rglob("session.json"))
    original = raw_path.read_text()
    # Re-export the SAME session id with DIFFERENT content: raw is write-once → unchanged,
    # and the rebuilt index reflects the retained (old) raw, never the new payload.
    summary = retain_sessions(
        [{**s, "bestLapTime": 9999}], lake_base=tmp_path, generated_at="2026-06-29T00:00:00Z"
    )
    assert summary.retained_new == 0
    assert raw_path.read_text() == original
    si = json.loads((root / SESSIONS_INDEX_FILENAME).read_text())
    assert si["sessions"][0]["best_lap_ms"] == 1000  # index agrees with disk, not the new payload
