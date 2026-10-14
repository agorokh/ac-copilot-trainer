"""Synthetic file-boundary checks for the optional silent replay report."""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.test_moza_ingest import view
from tests.test_voice_shadow_replay import archive, restrict
from tools.ai_sidecar.voice import shadow_replay
from tools.session_review import build_moza_session_report, moza, write_session_report
from tools.session_review.report import render_html, render_markdown


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    path = tmp_path / "attributions.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(path))


def write(tmp_path, value, name):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_disabled_shadow_never_reads_reference_or_constructs_runtime(tmp_path, monkeypatch):
    selected = write(tmp_path, archive(), "selected.json")

    def unexpected(*args, **kwargs):
        raise AssertionError("disabled shadow must not construct a runtime")

    monkeypatch.setattr(shadow_replay, "build_shadow_replay", unexpected)
    report = build_moza_session_report(selected, reference_file=tmp_path / "missing.json")
    assert report["moza_review"]["available"]
    assert "moza_shadow" not in report


def test_report_replays_captured_inputs_and_publishes_silent_evidence(tmp_path):
    selected = write(tmp_path, restrict(archive()), "selected.json")
    reference = write(tmp_path, archive("reference"), "reference.json")
    original = {path: path.read_bytes() for path in (selected, reference)}
    report = build_moza_session_report(selected, shadow_enabled=True, reference_file=reference)
    shadow = report["moza_shadow"]
    assert shadow["available"] and shadow["enabled"]
    assert shadow["stimulus"]["authority"] == "shared"
    assert shadow["reference"]["authority"] == "legacy_unknown"
    assert shadow["decision"]["human_evaluation"] == "no_go"
    assert shadow["decision"]["live_activation"] == "no_go"
    assert shadow["lanes"]["observer"]["dispatched_count"] > 0
    assert shadow["selected_input"]["sha256"] == hashlib.sha256(original[selected]).hexdigest()
    assert shadow["reference_input"]["sha256"] == hashlib.sha256(original[reference]).hexdigest()
    assert not report["spoken_summary"] and not report["history"]
    saved = write_session_report(
        report, output_dir=tmp_path / "journal" / "reports", protected_inputs=[selected, reference]
    )
    for path in (saved.html_path, saved.markdown_path):
        rendered = path.read_text(encoding="utf-8")
        assert "Silent voice validation" in rendered
        assert "Measured brake onsets" in rendered
        assert "Reference conditions" in rendered
        assert "Observer cue timeline (silent)" in rendered
        assert "Observer cue timing budgets" in rendered
        assert "Observer scheduler decisions" in rendered
        assert "Coach v2 replay checks" in rendered
        assert "No speech or audio device" in rendered
        assert "legacy_unknown" in rendered and "no_go" in rendered
    assert str(tmp_path) not in saved.json_path.read_text(encoding="utf-8")
    for path, content in original.items():
        assert path.read_bytes() == content


@pytest.mark.parametrize("damage", ["missing", "schema", "json"])
def test_bad_reference_does_not_destroy_native_inspection(tmp_path, damage):
    selected = write(tmp_path, archive(), "selected.json")
    reference = tmp_path / "reference.json"
    if damage == "schema":
        reference.write_text('{"schema_version": 999}', encoding="utf-8")
    elif damage == "json":
        reference.write_text("not json", encoding="utf-8")
    report = build_moza_session_report(selected, shadow_enabled=True, reference_file=reference)
    assert report["moza_review"]["available"]
    assert not report["moza_shadow"]["available"]
    assert report["moza_shadow"]["reason"].startswith("reference_input:")
    assert report["moza_shadow"]["decision"]["live_activation"] == "no_go"


def test_bad_selected_file_reports_shadow_unavailable(tmp_path):
    report = build_moza_session_report(tmp_path / "missing.json", shadow_enabled=True)
    assert not report["moza_shadow"]["available"]
    assert report["moza_shadow"]["reason"].startswith("selected_input:")
    assert "Silent voice validation" in render_markdown(report)


def test_shared_reference_is_rejected_without_hiding_source_measurements(tmp_path):
    selected = write(tmp_path, restrict(archive()), "selected.json")
    reference = write(tmp_path, restrict(archive("reference")), "reference.json")
    report = build_moza_session_report(selected, shadow_enabled=True, reference_file=reference)
    shadow = report["moza_shadow"]
    assert report["moza_review"]["available"]
    assert not shadow["available"]
    assert shadow["measured_brake_events"]
    assert "reference:control_authority_not_human:shared" in shadow["decision"]["reasons"]


def test_cache_is_inspection_only_even_with_shadow_selected(tmp_path):
    selected = write(tmp_path, view(), "cache.json")
    reference = write(tmp_path, archive("reference"), "reference.json")
    report = build_moza_session_report(selected, shadow_enabled=True, reference_file=reference)
    assert report["moza_review"]["status"] == "inspection_only"
    assert not report["moza_shadow"]["available"]
    assert not report["moza_shadow"]["measured_brake_events"]


def test_reference_alias_cannot_become_independent_baseline(tmp_path):
    selected = write(tmp_path, archive(), "selected.json")
    report = build_moza_session_report(selected, shadow_enabled=True, reference_file=selected)
    assert not report["moza_shadow"]["available"]
    assert report["moza_shadow"]["reason"] == "reference:not_independent_of_stimulus"


def test_shadow_renderers_escape_phrases_and_keep_missing_dispatch_unavailable(tmp_path):
    selected = write(tmp_path, archive(), "selected.json")
    report = build_moza_session_report(selected)
    shadow = moza._shadow_unavailable("test_fixture")
    shadow["lanes"] = {
        "observer": {"cues": [{"phrase": "<script>bad()</script>", "t_dispatch_ms": None}]}
    }
    report["moza_shadow"] = shadow
    for renderer in (render_html, render_markdown):
        text = renderer(report)
        assert "<script>bad()</script>" not in text
        assert "&lt;script&gt;" in text
        assert "unavailable" in text


def test_shadow_uses_captured_selection_without_reopening_it(tmp_path, monkeypatch):
    selected = write(tmp_path, archive(), "selected.json")
    reference = write(tmp_path, archive("reference"), "reference.json")
    reads = []
    original = moza.read_selected_json

    def capture(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(moza, "read_selected_json", capture)
    build_moza_session_report(selected, shadow_enabled=True, reference_file=reference)
    assert reads == [selected, reference]
