"""Explicit offline MOZA review using synthetic data and an isolated ledger."""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from tests.test_lap_qualification import assessment
from tests.test_moza_ingest import evaluation, imported, view
from tests.test_track_map import _corner_archive
from tools.lap_qualification import register_attribution
from tools.session_review import build_moza_session_report, moza, write_session_report
from tools.session_review.report import SessionReviewError, render_html, render_markdown


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "attributions.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}))
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))


def native(*, identity="subject", degrade=8, authority=None):
    record = _corner_archive(degrade=degrade)
    record.update(schema_version=1, session_uuid=identity + "-session", lap_uuid=identity)
    record["lap"].update(lap_n=1, is_pb=True)
    if authority:
        record["qualification"] = assessment(record, authority=authority, promoted=True)
    return record


def write(tmp_path, payload, name="selected.json"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cache_inspection_is_useful_but_not_promoted_or_rewritten(tmp_path):
    selected = write(tmp_path, view())
    before = selected.read_bytes()
    report = build_moza_session_report(selected)
    review = report["moza_review"]
    assert review["status"] == "inspection_only"
    assert review["authority"] == "unknown"
    assert len(review["qualification"]) == 6
    assert not any(item["allowed"] for item in review["qualification"].values())
    assert not any(item["available"] for item in review["channels"])
    assert review["inspection"]["detail_point_count"] == 3
    assert review["observed_lap"]["lap_ms"] == 40000
    assert not report["problems"] and not report["spoken_summary"]
    assert report["session"]["best_lap_ms"] is None
    assert not review["native_comparison"]["available"]
    saved = write_session_report(
        report, output_dir=tmp_path / "journal" / "reports", protected_inputs=[selected]
    )
    markdown = saved.markdown_path.read_text(encoding="utf-8")
    assert "inspection_only" in markdown and "Channel availability" in markdown
    assert "No repeated corner loss" not in markdown
    assert "Best lap" not in markdown and "Spoken Summary" not in markdown
    assert str(tmp_path) not in saved.json_path.read_text(encoding="utf-8")
    assert selected.read_bytes() == before


def test_normalized_inspection_never_reconstructs_original_view(tmp_path):
    selected = write(tmp_path, imported())
    evaluated = write(tmp_path, evaluation(), "evaluation.json")
    report = build_moza_session_report(selected, evaluation_file=evaluated, oracle_enabled=True)
    review = report["moza_review"]
    assert review["selected"]["kind"] == "moza_inspection_archive"
    assert not review["available"]
    assert review["oracle"]["reason"] == "original_moza_view_unavailable"


def test_legacy_native_selection_does_not_infer_moza_or_human(tmp_path):
    report = build_moza_session_report(write(tmp_path, native()))
    review = report["moza_review"]
    assert review["status"] == "analysis_available"
    assert review["authority"] == "legacy_unknown"
    assert review["selected"]["source"] == "in_game"
    assert review["corner_observations"]
    assert set(review["corner_observations"][0]) == {"index", "apex_spline", "min_speed_kmh"}
    assert report["session"]["best_lap_ms"] is None
    assert not report["history"] and not report["spoken_summary"] and not report["problems"]
    assert "legacy_unknown" in render_markdown(report)
    assert "legacy_unknown" in render_html(report)


def test_attributed_original_native_allows_analysis_only(tmp_path):
    record = native()
    selected = write(tmp_path, record)
    before = selected.read_bytes()
    register_attribution(selected, assessment(record))
    report = build_moza_session_report(selected)
    review = report["moza_review"]
    assert review["status"] == "analysis_available" and review["authority"] == "shared"
    assert review["corner_observations"][0]["min_speed_kmh"] > 0
    for use, decision in review["qualification"].items():
        assert decision["allowed"] is (use == "analysis")
    assert not report["spoken_summary"] and not report["problems"]
    assert selected.read_bytes() == before


def test_finite_extra_native_fields_without_semantics_are_not_qualified(tmp_path):
    record = native()
    record["trace"]["fields"].append("extra_unqualified_channel")
    for sample in record["trace"]["samples"]:
        sample.append(42)
    record["qualification"] = assessment(record)
    report = build_moza_session_report(write(tmp_path, record))
    review = report["moza_review"]
    assert review["available"]
    extra = next(row for row in review["channels"] if row["name"] == "extra_unqualified_channel")
    assert extra["present"] and not extra["available"]
    assert extra["reason"] == "channel_semantics_unverified"
    for renderer in (render_html, render_markdown):
        rendered = renderer(report)
        assert rendered.index("Selected lap corner measurements") < rendered.index(
            "Channel availability"
        )


def test_qualified_same_combo_native_comparison_uses_existing_corner_measurements(tmp_path):
    selected = write(tmp_path, native(authority="shared"))
    matched = write(
        tmp_path, native(identity="target", degrade=0, authority="human"), "matched.json"
    )
    report = build_moza_session_report(selected, matched_native_file=matched)
    review = report["moza_review"]
    comparison = review["native_comparison"]
    assert comparison["available"] and comparison["corners"][0]["time_loss_s"] > 0
    assert (
        comparison["corners"][0]["min_speed_kmh"]
        < comparison["corners"][0]["reference_min_speed_kmh"]
    )
    assert "not_recording_identity_proof" in review["matched_native"]["association"]
    assert "Qualified native corner comparison" in render_markdown(report)
    assert "Time delta s" in render_html(report)
    assert not report["spoken_summary"] and report["session"]["best_lap_ms"] is None


@pytest.mark.parametrize("authority", ["shared", "ai", "unknown"])
def test_analysis_only_target_never_becomes_reference(tmp_path, authority):
    selected = write(tmp_path, native(authority="shared"))
    matched = write(tmp_path, native(identity="target", authority=authority), "matched.json")
    comparison = build_moza_session_report(selected, matched_native_file=matched)["moza_review"][
        "native_comparison"
    ]
    assert not comparison["available"] and not comparison["corners"]
    assert "control_authority_not_human" in comparison["reason"]


@pytest.mark.parametrize("schema", [None, True, 2, "1"])
def test_selected_and_matched_native_require_strict_file_schema(tmp_path, schema):
    record = native()
    if schema is None:
        del record["schema_version"]
    else:
        record["schema_version"] = schema
    invalid = write(tmp_path, record)
    assert (
        build_moza_session_report(invalid)["moza_review"]["reason"] == "unsupported_archive_schema"
    )
    selected = write(tmp_path, native(identity="other"), "other.json")
    comparison = build_moza_session_report(selected, matched_native_file=invalid)["moza_review"][
        "native_comparison"
    ]
    assert comparison["reason"] == "matched_native:unsupported_archive_schema"


@pytest.mark.parametrize("damage", ["combo", "missing_brake", "duplicate", "source"])
def test_native_pair_rejections_are_explicit(tmp_path, damage):
    record = native(identity="target", authority=None)
    if damage == "combo":
        record["car"]["id"] = "other-car"
    elif damage == "missing_brake":
        index = record["trace"]["fields"].index("brake")
        record["trace"]["samples"][0][index] = None
    elif damage == "duplicate":
        record = native(authority="shared")
    else:
        record["source"] = "imported"
    selected = write(tmp_path, native(authority="shared"))
    matched = write(tmp_path, record, "matched.json")
    comparison = build_moza_session_report(selected, matched_native_file=matched)["moza_review"][
        "native_comparison"
    ]
    assert not comparison["available"] and not comparison["corners"]


@pytest.mark.parametrize(
    "damage", [None, [], {"fields": [], "samples": {}}, {"fields": [], "samples": []}]
)
def test_bad_trace_is_reported_without_fabricated_corners(tmp_path, damage):
    record = native()
    record["trace"] = damage
    report = build_moza_session_report(write(tmp_path, record))
    assert not report["moza_review"]["available"]
    assert not report["moza_review"].get("corner_observations")
    assert not report["problems"]


def test_zero_evaluation_and_mismatch_remain_separate_from_inspection(tmp_path):
    selected = write(tmp_path, view())
    evaluated = write(tmp_path, evaluation(), "evaluation.json")
    review = build_moza_session_report(selected, evaluation_file=evaluated, oracle_enabled=True)[
        "moza_review"
    ]
    assert review["status"] == "inspection_only"
    assert review["authority"] == "shared"
    assert review["oracle"]["reason"] == "zero_evaluated_laps"
    assert review["oracle"]["snapshot"] is None
    bad = evaluation()
    bad["summary"]["laps"][0]["id"] = "different-lap"
    write(tmp_path, bad, "evaluation.json")
    review = build_moza_session_report(selected, evaluation_file=evaluated, oracle_enabled=True)[
        "moza_review"
    ]
    assert review["status"] == "inspection_only" and review["inspection"]["detail_point_count"] == 3
    assert review["evaluation"]["status"] == "unavailable"
    assert review["oracle"]["status"] == "unavailable"
    assert review["authority"] == "unknown"


def test_native_never_joins_evaluation_by_time(tmp_path):
    selected = write(tmp_path, native())
    evaluated = write(tmp_path, evaluation(), "evaluation.json")
    review = build_moza_session_report(selected, evaluation_file=evaluated, oracle_enabled=True)[
        "moza_review"
    ]
    assert review["evaluation"]["reason"] == "original_moza_view_unavailable"
    assert review["oracle"]["reason"] == "original_moza_view_unavailable"


def test_unrecognized_source_cannot_use_legacy_permission_in_native_workflow(tmp_path):
    record = native()
    record["source"] = "unrecognized"
    review = build_moza_session_report(write(tmp_path, record))["moza_review"]
    assert review["reason"] == "selected_native_source_required"
    assert review["selected"]["kind"] == "lap_archive"
    assert not review["available"]
    assert not any(channel["available"] for channel in review["channels"])


def test_capture_is_used_for_analysis_without_mutable_second_read(tmp_path, monkeypatch):
    selected = write(tmp_path, native())
    original = selected.read_bytes()
    reader = moza.read_selected_json
    calls = []

    def capture(path):
        result = reader(path)
        calls.append(path)
        selected.write_text("{}")
        return result

    monkeypatch.setattr(moza, "read_selected_json", capture)
    report = build_moza_session_report(selected)
    assert calls == [selected]
    assert report["moza_review"]["available"]
    assert report["moza_review"]["selected"]["sha256"] == hashlib.sha256(original).hexdigest()


def test_changed_during_capture_is_explicit_unavailable(tmp_path, monkeypatch):
    def fail(_path):
        raise moza.MozaImportError("input_changed_during_read")

    monkeypatch.setattr(moza, "read_selected_json", fail)
    report = build_moza_session_report(tmp_path / "selected.json")
    assert report["moza_review"]["status"] == "input_unavailable"
    assert "input_changed_during_read" in render_markdown(report)


def test_html_escapes_provider_labels(tmp_path):
    payload = view()
    for value in (payload["overview"], payload["details"]["summary"]):
        value["carModel"] = "<script>bad()</script>"
    report = build_moza_session_report(write(tmp_path, payload))
    html = render_html(report)
    assert "<script>bad()</script>" not in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html


def test_writer_requires_protection_for_moza_report(tmp_path):
    report = build_moza_session_report(write(tmp_path, view()))
    with pytest.raises(SessionReviewError, match="protected_inputs_required"):
        write_session_report(report, output_dir=tmp_path / "journal" / "reports")


@pytest.mark.parametrize("suffix", ["json", "md", "html"])
@pytest.mark.parametrize("alias", [False, True])
def test_writer_rejects_every_input_alias_before_any_output(tmp_path, suffix, alias):
    selected = write(tmp_path, native())
    report = build_moza_session_report(selected)
    from tools.session_review.report import _report_basename

    output = tmp_path / "journal" / "reports"
    output.mkdir(parents=True)
    colliding = output / (_report_basename(report) + "." + suffix)
    protected = tmp_path / "protected.json" if alias else colliding
    protected.write_text("private input")
    if alias:
        os.link(protected, colliding)
    with pytest.raises(SessionReviewError, match="report_output_aliases_input"):
        write_session_report(report, output_dir=output, protected_inputs=[selected, protected])
    assert protected.read_text() == "private input"
    assert set(output.iterdir()) == {colliding}
