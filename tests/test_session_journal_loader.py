"""Session journal file loader (#97)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from tools.session_journal import (
    SessionJournalParseError,
    ValidationError,
    ingest_exports,
    load_export,
    sample_valid_session_journal,
)


def test_load_export_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(sample_valid_session_journal()), encoding="utf-8")
    loaded = load_export(path)
    assert loaded["schema_version"] == 1


def test_malformed_json_raises_parse_error_with_snippet(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    text = '{"schema_version": 1, "trailing": '
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SessionJournalParseError) as exc_info:
        load_export(path)

    err = exc_info.value
    assert err.path == path
    assert err.byte_offset is not None
    assert err.snippet is not None
    assert len(err.snippet) <= 200


def test_schema_invalid_propagates_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text('{"schema_version": 1}', encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_export(path)

    assert any("missing keys" in e for e in exc_info.value.errors)


def test_json_array_raises_validation_error_at_trust_boundary(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_export(path)

    assert exc_info.value.errors == ["root must be a JSON object"]


def test_json_snippet_collapses_newlines(tmp_path: Path) -> None:
    path = tmp_path / "multiline.json"
    text = '{\n  "schema_version": 1,\n  "broken": '
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SessionJournalParseError) as exc_info:
        load_export(path)

    assert exc_info.value.snippet is not None
    assert "\n" not in exc_info.value.snippet


def test_missing_path_propagates_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(FileNotFoundError):
        load_export(missing)


def test_empty_file_raises_parse_error_with_reason(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_bytes(b"")

    with pytest.raises(SessionJournalParseError) as exc_info:
        load_export(path)

    assert exc_info.value.reason == "empty file"


def test_non_utf8_raises_encoding_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "latin1.json"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(SessionJournalParseError) as exc_info:
        load_export(path)

    assert exc_info.value.reason == "encoding"


def test_json_error_byte_offset_is_utf8_not_char_index(tmp_path: Path) -> None:
    path = tmp_path / "unicode.json"
    # Euro sign is one character but three UTF-8 bytes before the truncated tail.
    text = '{"note": "\u20ac", "broken": '
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SessionJournalParseError) as exc_info:
        load_export(path)

    err = exc_info.value
    char_pos = len(text)
    assert err.byte_offset is not None
    assert err.byte_offset == len(text[:char_pos].encode("utf-8"))
    assert err.byte_offset > char_pos


def test_ingest_missing_file_logs_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(sample_valid_session_journal()), encoding="utf-8")
    missing = tmp_path / "missing.json"

    caplog.set_level(logging.ERROR)
    loaded = ingest_exports([missing, good])

    assert len(loaded) == 1
    assert any(r.exc_info is not None for r in caplog.records)


def test_ingest_loop_logs_oserror_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(sample_valid_session_journal()), encoding="utf-8")
    not_a_file = tmp_path / "subdir"
    not_a_file.mkdir()

    caplog.set_level(logging.ERROR)
    loaded = ingest_exports([not_a_file, good])

    assert len(loaded) == 1
    assert any(r.exc_info is not None for r in caplog.records)


def test_ingest_loop_logs_exception_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(sample_valid_session_journal()), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    caplog.set_level(logging.ERROR)
    loaded = ingest_exports([bad, good])

    assert len(loaded) == 1
    assert loaded[0]["session_key"] == sample_valid_session_journal()["session_key"]
    assert any("Failed to load session journal export" in r.message for r in caplog.records)
    assert any(r.exc_info is not None for r in caplog.records)
