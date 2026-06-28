"""Unit tests for tools.tt_ingest.tt_export (issue #353)."""

from __future__ import annotations

import json

import pytest

from tools.tt_ingest.tt_export import (
    INDEX_SCHEMA_VERSION,
    RetainedFile,
    TTExportError,
    build_index,
    endpoint_file,
    lake_root,
    relative_to_lake,
    sanitize_segment,
    session_lake_dir,
    sha256_hex,
    stable_fingerprint,
    write_immutable_json,
)

# --- sanitize_segment -------------------------------------------------------------


def test_sanitize_segment_replaces_unsafe() -> None:
    assert sanitize_segment("ks/red:bull ring") == "ks_red_bull_ring"


def test_sanitize_segment_blocks_traversal() -> None:
    assert sanitize_segment("..") == "unknown"
    assert sanitize_segment("../../etc") == "etc"


def test_sanitize_segment_empty_fallback() -> None:
    assert sanitize_segment("", fallback="fb") == "fb"
    assert sanitize_segment(None, fallback="fb") == "fb"


def test_sanitize_segment_length_cap() -> None:
    assert len(sanitize_segment("a" * 500)) == 128


# --- lake paths -------------------------------------------------------------------


def test_lake_root_default(tmp_path) -> None:
    root = lake_root(tmp_path, env={})
    assert root == tmp_path / "journal" / "tt"


def test_lake_root_env_override(tmp_path) -> None:
    override = tmp_path / "custom"
    assert lake_root(tmp_path, env={"TT_LAKE_DIR": str(override)}) == override


def test_session_lake_dir_structure(tmp_path) -> None:
    root = lake_root(tmp_path, env={})
    d = session_lake_dir(
        root, game="assettoCorsa", car="syn_mercedes_w09", track="spa", session_key="sess-1"
    )
    assert d == root / "assettoCorsa" / "syn_mercedes_w09" / "spa" / "sess-1"


def test_session_lake_dir_sanitizes_missing(tmp_path) -> None:
    root = lake_root(tmp_path, env={})
    d = session_lake_dir(root, game=None, car=None, track=None, session_key=None)
    assert d.parts[-4:] == ("unknown_game", "unknown_car", "unknown_track", "unknown_session")


def test_endpoint_file(tmp_path) -> None:
    assert endpoint_file(tmp_path, "session").name == "session.json"


# --- write_immutable_json ---------------------------------------------------------


def test_write_immutable_json_writes_new(tmp_path) -> None:
    path = tmp_path / "a" / "b" / "session.json"
    result = write_immutable_json(path, {"hello": "world"})
    assert result.written is True
    assert path.exists()
    assert json.loads(path.read_text())["hello"] == "world"
    assert result.sha256 == sha256_hex(path.read_bytes())


def test_write_immutable_json_refuses_overwrite(tmp_path) -> None:
    path = tmp_path / "session.json"
    write_immutable_json(path, {"v": 1})
    original = path.read_text()
    result = write_immutable_json(path, {"v": 2})
    assert result.written is False
    assert path.read_text() == original  # unchanged
    # Returned hash is the EXISTING file's, so it can still be indexed.
    assert result.sha256 == sha256_hex(path.read_bytes())


def test_write_immutable_json_overwrite_true(tmp_path) -> None:
    path = tmp_path / "session.json"
    write_immutable_json(path, {"v": 1})
    result = write_immutable_json(path, {"v": 2}, overwrite=True)
    assert result.written is True
    assert json.loads(path.read_text())["v"] == 2


def test_write_immutable_json_no_temp_litter(tmp_path) -> None:
    path = tmp_path / "session.json"
    write_immutable_json(path, {"v": 1})
    assert list(tmp_path.glob("*.tmp")) == []


# --- index helpers ----------------------------------------------------------------


def test_relative_to_lake(tmp_path) -> None:
    root = tmp_path / "journal" / "tt"
    f = root / "assettoCorsa" / "car" / "track" / "s" / "session.json"
    assert relative_to_lake(f, root) == "assettoCorsa/car/track/s/session.json"


def test_relative_to_lake_outside_root_raises(tmp_path) -> None:
    root = tmp_path / "lake"
    root.mkdir()
    with pytest.raises(TTExportError):
        relative_to_lake(tmp_path / "elsewhere" / "x.json", root)


def test_build_index() -> None:
    records = [
        RetainedFile("s1", "session", "a/s1/session.json", "deadbeef", 120, True),
        RetainedFile("s2", "session", "a/s2/session.json", "cafef00d", 96, False),
    ]
    index = build_index(records, generated_at="2026-06-28T00:00:00Z")
    assert index["index_schema_version"] == INDEX_SCHEMA_VERSION
    assert index["file_count"] == 2
    assert index["files"][0]["sha256"] == "deadbeef"
    assert index["files"][1]["path"] == "a/s2/session.json"


# --- regression tests for the PR-359 adversarial-review fixes ----------------------


def test_stable_fingerprint_deterministic_and_distinct() -> None:
    a = {"car_id": "c", "track_id": "t"}
    b = {"track_id": "t", "car_id": "c"}  # same content, different key order
    c = {"car_id": "c", "track_id": "u"}
    assert stable_fingerprint(a) == stable_fingerprint(b)  # canonical → order-independent
    assert stable_fingerprint(a) != stable_fingerprint(c)  # distinct content → distinct id
    assert len(stable_fingerprint(a)) == 12


def test_write_immutable_json_strict_rejects_nan_by_default(tmp_path) -> None:
    with pytest.raises(ValueError):
        write_immutable_json(tmp_path / "x.json", {"v": float("nan")})


def test_write_immutable_json_allow_nan_is_lossless(tmp_path) -> None:
    import json

    path = tmp_path / "raw.json"
    result = write_immutable_json(path, {"airTemp": float("nan")}, allow_nan=True)
    assert result.written is True
    # Round-trips through our own json.loads (which accepts NaN), so retention is lossless.
    loaded = json.loads(path.read_text())
    assert loaded["airTemp"] != loaded["airTemp"]  # NaN != NaN
