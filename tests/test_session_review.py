from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tools.session_review.report import (
    SessionReviewError,
    build_session_report,
    main,
    render_markdown,
    report_dir_for_lap_dir,
    write_session_report,
)


def _corner_archive(
    *,
    lap_uuid: str,
    session_uuid: str,
    lap_n: int,
    exported_at: str,
    degrade: float = 0.0,
    source: str = "in_game",
    import_format: str | None = None,
    generator: dict | None = None,
) -> dict:
    radius, ds, n_pre, n_arc, n_post = 30.0, 2.0, 40, 30, 40
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z = 0.0, 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = []
    for i in range(n):
        if i < 25:
            v.append(55.0)
        elif i < apex_i:
            v.append(55.0 + (25.0 - 55.0) * (i - 25) / max(1, apex_i - 25) - degrade)
        elif i < n_pre + n_arc + 5:
            v.append(25.0 + (55.0 - 25.0) * (i - apex_i) / max(1, n_pre + n_arc + 5 - apex_i))
        else:
            v.append(55.0)
    brake = [0.8 if 25 <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_ms = [0.0]
    for i in range(1, n):
        t_ms.append(t_ms[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])) * 1000.0)
    total = ds * (n - 1)
    spline = [(ds * i) / total for i in range(n)]
    samples = [
        [spline[i], v[i] * 3.6, t_ms[i], throttle[i], brake[i], steer[i], 4, xs[i], 0.0, zs[i]]
        for i in range(n)
    ]
    payload = {
        "schema_version": 1,
        "source": source,
        "lap_uuid": lap_uuid,
        "session_uuid": session_uuid,
        "exported_at": exported_at,
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "lengthM": total},
        "lap": {"lap_n": lap_n, "lap_ms": int(t_ms[-1]), "is_valid": True},
        "setup": {"snapshot": {"FRONT_BIAS.VALUE": "66", "TRACTION_CONTROL.VALUE": "4"}},
        "trace": {
            "fields": [
                "spline",
                "speed",
                "eMs",
                "throttle",
                "brake",
                "steer",
                "gear",
                "px",
                "py",
                "pz",
            ],
            "samples": samples,
        },
        "corners": [
            {
                "label": "T1",
                "minSpeed": min(v) * 3.6,
                "exitSpeed": max(v[apex_i:]) * 3.6,
            }
        ],
    }
    if import_format is not None:
        payload["import_format"] = import_format
    if generator is not None:
        payload["generator"] = generator
    return payload


def _write_lap(root: Path, name: str, payload: dict) -> Path:
    path = root / f"lap_{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def session_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)
    _write_lap(
        laps,
        "ref",
        _corner_archive(
            lap_uuid="lap-ref",
            session_uuid="sess-reference",
            lap_n=1,
            exported_at="2026-06-29T10:00:00Z",
            degrade=0.0,
        ),
    )
    _write_lap(
        laps,
        "latest-1",
        _corner_archive(
            lap_uuid="lap-latest-1",
            session_uuid="sess-latest",
            lap_n=1,
            exported_at="2026-06-30T10:00:00Z",
            degrade=8.0,
        ),
    )
    _write_lap(
        laps,
        "latest-2",
        _corner_archive(
            lap_uuid="lap-latest-2",
            session_uuid="sess-latest",
            lap_n=2,
            exported_at="2026-06-30T10:05:00Z",
            degrade=6.0,
        ),
    )
    return laps


def test_build_session_report_selects_latest_and_ranks_corner_problem(
    session_corpus: Path,
) -> None:
    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    assert report["schema_version"] == 2
    assert report["session"]["session_uuid"] == "sess-latest"
    assert report["reference"]["source_file"] == "lap_ref.json"
    assert report["reference"]["kind"] == "your-best"
    assert report["reference_selection"] == {
        "requested_source": "auto",
        "active": True,
        "active_source": "your-best",
        "source_file": "lap_ref.json",
        "reason": "fastest valid same car/track reference",
    }
    assert report["problems"]
    top = report["problems"][0]
    assert top["label"] == "T1"
    assert top["laps_affected"] >= 1
    assert top["ranked_fixes"]
    assert report["source"]["selected_lap_files"] == ["lap_latest-1.json", "lap_latest-2.json"]
    assert report["screen_summary"][0].startswith("T1:")
    assert report["next_session_prep"][0].startswith("T1:")
    assert [row["session_uuid"] for row in report["history"]["trend"]["sessions"]] == [
        "sess-reference",
        "sess-latest",
    ]
    assert report["history"]["trend"]["corner_speed"][0]["points"]
    assert report["comparison"]["default_pair"]["a"] == "lap-latest-2"
    assert report["comparison"]["default_pair"]["b"] == "lap-ref"
    assert report["comparison"]["laps"][0]["trace"]["points"]


def test_reference_source_selects_track_titan_over_faster_candidate(
    session_corpus: Path,
) -> None:
    _write_lap(
        session_corpus,
        "tt",
        _corner_archive(
            lap_uuid="lap-tt",
            session_uuid="sess-tt",
            lap_n=1,
            exported_at="2026-06-29T11:00:00Z",
            degrade=3.0,
            source="imported",
            import_format="track_titan_reference_v1",
            generator={"tt_reference": {"partial": False}},
        ),
    )
    _write_lap(
        session_corpus,
        "pro",
        _corner_archive(
            lap_uuid="lap-pro",
            session_uuid="sess-pro",
            lap_n=1,
            exported_at="2026-06-29T11:10:00Z",
            degrade=0.0,
            source="imported",
            import_format="motec_csv",
        ),
    )

    report = build_session_report(
        [session_corpus],
        session="sess-latest",
        reference_source="tt",
        grip_ceiling_g=2.5,
        generated_at="stamp",
    )

    assert report["reference"]["source_file"] == "lap_tt.json"
    assert report["reference"]["kind"] == "tt"
    assert report["reference_selection"]["requested_source"] == "tt"
    assert report["reference_selection"]["active_source"] == "tt"
    assert any(row["reference_kind"] == "tt" for row in report["history"]["laps"])


def test_reference_source_none_disables_reference_comparison(session_corpus: Path) -> None:
    report = build_session_report(
        [session_corpus],
        reference_source="none",
        grip_ceiling_g=2.5,
        generated_at="stamp",
    )

    assert report["reference"] is None
    assert report["reference_selection"] == {
        "requested_source": "none",
        "active": False,
        "active_source": None,
        "source_file": None,
        "reason": "reference comparison disabled by request",
    }
    assert "Reference: none (reference comparison disabled by request)" in render_markdown(report)


def test_reference_path_pins_generated_reference(session_corpus: Path) -> None:
    generated_path = _write_lap(
        session_corpus,
        "generated",
        _corner_archive(
            lap_uuid="lap-generated",
            session_uuid="sess-generated",
            lap_n=1,
            exported_at="2026-06-29T11:20:00Z",
            degrade=4.0,
            source="imported",
            import_format="generated_reference_v1",
            generator={"name": "tools.ac_harness.reference_lap.synthetic"},
        ),
    )

    report = build_session_report(
        [session_corpus],
        session="sess-latest",
        reference_path=generated_path,
        grip_ceiling_g=2.5,
        generated_at="stamp",
    )

    assert report["reference"]["source_file"] == "lap_generated.json"
    assert report["reference"]["kind"] == "generated"
    assert report["reference_selection"]["reason"] == "explicit reference file selected"


def test_missing_exported_at_does_not_break_latest_selection(session_corpus: Path) -> None:
    lap_path = session_corpus / "lap_latest-1.json"
    payload = json.loads(lap_path.read_text(encoding="utf-8"))
    payload.pop("exported_at")
    lap_path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    assert report["session"]["session_uuid"] == "sess-latest"
    assert report["session"]["first_exported_at"] == "2026-06-30T10:05:00Z"


def test_unusable_reference_lap_falls_back_to_lap_only_analysis(session_corpus: Path) -> None:
    bad_ref = _corner_archive(
        lap_uuid="lap-bad-ref",
        session_uuid="sess-bad-ref",
        lap_n=1,
        exported_at="2026-06-29T09:00:00Z",
        degrade=0.0,
    )
    bad_ref["lap"]["lap_ms"] = 1
    bad_ref["trace"] = {"fields": [], "samples": []}
    _write_lap(session_corpus, "bad-ref", bad_ref)

    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    assert report["problems"]
    assert any("unusable reference" in item for item in report["source"]["skipped"])


def test_session_with_no_usable_trace_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)
    bad = _corner_archive(
        lap_uuid="bad-trace",
        session_uuid="sess-bad-trace",
        lap_n=1,
        exported_at="2026-06-30T10:00:00Z",
    )
    bad["trace"] = {"fields": [], "samples": []}
    _write_lap(laps, "bad-trace", bad)

    with pytest.raises(SessionReviewError, match="usable trace"):
        build_session_report([laps], session="sess-bad-trace")


def test_write_session_report_saves_markdown_and_json_under_reports(
    session_corpus: Path,
) -> None:
    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    written = write_session_report(report)

    assert written.markdown_path.is_file()
    assert written.json_path.is_file()
    assert written.html_path.is_file()
    assert written.markdown_path.parent.name == "reports"
    markdown = written.markdown_path.read_text(encoding="utf-8")
    assert "## Problem List" in markdown
    assert "## Next Session Prep" in markdown
    assert "## Lap History" in markdown
    payload = json.loads(written.json_path.read_text(encoding="utf-8"))
    assert payload["spoken_summary"] == report["spoken_summary"]
    assert payload["reference_selection"]["active"] is True
    html = written.html_path.read_text(encoding="utf-8")
    assert "Lap Compare" in html
    assert 'id="review-data"' in html
    assert "https://" not in html


def test_report_output_must_stay_under_journal_reports(session_corpus: Path) -> None:
    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    with pytest.raises(SessionReviewError, match="journal/reports"):
        write_session_report(report, output_dir="exports")


def test_absolute_sibling_report_dir_for_lap_dir_is_allowed(session_corpus: Path) -> None:
    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")
    output_dir = report_dir_for_lap_dir(session_corpus)

    written = write_session_report(report, output_dir=output_dir)

    assert written.markdown_path.parent == output_dir
    assert written.json_path.parent == output_dir
    assert written.html_path.parent == output_dir


def test_cli_generates_json_result(
    session_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--lap-dir", str(session_corpus), "--json", "--grip-ceiling-g", "2.5"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["markdown"]).is_file()
    assert Path(payload["json"]).is_file()
    assert Path(payload["html"]).is_file()
    assert payload["screen_summary"]
    assert payload["reference"]["kind"] == "your-best"
    assert payload["reference_selection"]["requested_source"] == "auto"


def test_session_without_valid_laps_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)
    bad = _corner_archive(
        lap_uuid="bad",
        session_uuid="sess-bad",
        lap_n=1,
        exported_at="2026-06-30T10:00:00Z",
    )
    bad["lap"]["is_valid"] = False
    _write_lap(laps, "bad", bad)

    with pytest.raises(SessionReviewError, match="no valid timed laps"):
        build_session_report([laps], session="sess-bad")
