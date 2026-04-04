"""Session journal schema (#47)."""

from copy import deepcopy

from tools.session_journal import (
    JOURNAL_SCHEMA_VERSION,
    sample_valid_session_journal,
    validate_session_journal,
)


def test_sample_journal_validates():
    sample = sample_valid_session_journal()
    assert validate_session_journal(sample) == []


def test_minimal_journal_validates():
    """Smallest valid payload: optional/null fields pared down; omit reserved llm_debrief."""
    sample = sample_valid_session_journal()
    minimal = deepcopy(sample)
    del minimal["llm_debrief"]
    minimal["conditions"] = {"track_grip": None}
    minimal["summary"] = {"laps_completed": 1}
    minimal["lap_history"] = []
    minimal["corners_last_lap"] = []
    minimal["coaching_hints_last"] = []
    assert validate_session_journal(minimal) == []


def test_schema_version_constant_matches_lua():
    assert JOURNAL_SCHEMA_VERSION == 1


def test_rejects_wrong_root_type():
    assert validate_session_journal([]) != []


def test_rejects_missing_keys():
    bad = {"schema_version": 1}
    errs = validate_session_journal(bad)
    assert any("missing keys" in e for e in errs)


def test_rejects_unknown_top_level_keys():
    bad = dict(sample_valid_session_journal())
    bad["foo"] = "bar"
    errs = validate_session_journal(bad)
    assert any("unknown keys" in e for e in errs)


def test_rejects_wrong_schema_version():
    s = sample_valid_session_journal()
    s["schema_version"] = 999
    errs = validate_session_journal(s)
    assert any("schema_version must be" in e for e in errs)


def test_rejects_bad_exported_at():
    s = sample_valid_session_journal()
    s["exported_at"] = "not-iso"
    assert any("exported_at" in e for e in validate_session_journal(s))


def test_rejects_non_mapping_car_and_track():
    sample = sample_valid_session_journal()
    bad_car = dict(sample, car="not a dict")
    errs_car = validate_session_journal(bad_car)
    assert any("car must be an object" in e for e in errs_car)

    bad_track = dict(sample, track="not a dict")
    errs_track = validate_session_journal(bad_track)
    assert any("track must be an object" in e for e in errs_track)


def test_rejects_missing_car_and_track_ids():
    s1 = sample_valid_session_journal()
    s1["car"] = {}
    assert any("car must contain id" in e for e in validate_session_journal(s1))

    s2 = sample_valid_session_journal()
    s2["track"] = {}
    assert any("track must contain id" in e for e in validate_session_journal(s2))


def test_conditions_track_grip_types():
    s = sample_valid_session_journal()
    s["conditions"] = {"track_grip": "slippery"}
    assert any("conditions.track_grip" in e for e in validate_session_journal(s))

    s_ok = sample_valid_session_journal()
    s_ok["conditions"] = {"track_grip": None}
    assert validate_session_journal(s_ok) == []


def test_summary_numeric_fields():
    s = sample_valid_session_journal()
    for key in ("laps_completed", "best_lap_ms", "last_lap_ms", "avg_lap_ms"):
        bad = deepcopy(s)
        bad["summary"] = {key: "x"}
        assert any(f"summary.{key}" in e for e in validate_session_journal(bad))

    ok = deepcopy(s)
    ok["summary"] = {
        "laps_completed": None,
        "best_lap_ms": None,
        "last_lap_ms": None,
        "avg_lap_ms": None,
    }
    assert validate_session_journal(ok) == []


def test_lap_history_structure():
    s = sample_valid_session_journal()
    s["lap_history"] = {}
    assert any("lap_history must be an array" in e for e in validate_session_journal(s))

    s2 = sample_valid_session_journal()
    s2["lap_history"] = [1, 2]
    assert any("lap_history[0] must be an object" in e for e in validate_session_journal(s2))

    s3 = sample_valid_session_journal()
    s3["lap_history"] = [{"lap_ms": "slow", "corner_count": 0}]
    assert any("lap_history[0].lap_ms" in e for e in validate_session_journal(s3))


def test_llm_debrief_reserved():
    s = sample_valid_session_journal()
    s["llm_debrief"] = "not yet"
    assert any("llm_debrief" in e for e in validate_session_journal(s))
