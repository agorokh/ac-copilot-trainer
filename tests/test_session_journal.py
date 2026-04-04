"""Session journal schema (#47)."""

from tools.session_journal import (
    JOURNAL_SCHEMA_VERSION,
    sample_valid_session_journal,
    validate_session_journal,
)


def test_sample_journal_validates():
    sample = sample_valid_session_journal()
    assert validate_session_journal(sample) == []


def test_schema_version_constant_matches_lua():
    assert JOURNAL_SCHEMA_VERSION == 1


def test_rejects_wrong_root_type():
    assert validate_session_journal([]) != []


def test_rejects_missing_keys():
    bad = {"schema_version": 1}
    errs = validate_session_journal(bad)
    assert any("missing keys" in e for e in errs)


def test_rejects_bad_exported_at():
    s = sample_valid_session_journal()
    s["exported_at"] = "not-iso"
    assert any("exported_at" in e for e in validate_session_journal(s))
