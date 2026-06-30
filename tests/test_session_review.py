from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tools.session_review.report import (
    SessionReviewError,
    build_session_report,
    main,
    write_session_report,
)


def _corner_archive(
    *,
    lap_uuid: str,
    session_uuid: str,
    lap_n: int,
    exported_at: str,
    degrade: float = 0.0,
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
    return {
        "schema_version": 1,
        "source": "in_game",
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
    }


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

    assert report["session"]["session_uuid"] == "sess-latest"
    assert report["reference"]["source_file"] == "lap_ref.json"
    assert report["problems"]
    top = report["problems"][0]
    assert top["label"] == "T1"
    assert top["laps_affected"] >= 1
    assert top["ranked_fixes"]
    assert report["source"]["selected_lap_files"] == ["lap_latest-1.json", "lap_latest-2.json"]
    assert report["screen_summary"][0].startswith("T1:")
    assert report["next_session_prep"][0].startswith("T1:")


def test_write_session_report_saves_markdown_and_json_under_reports(
    session_corpus: Path,
) -> None:
    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    written = write_session_report(report)

    assert written.markdown_path.is_file()
    assert written.json_path.is_file()
    assert written.markdown_path.parent.name == "reports"
    markdown = written.markdown_path.read_text(encoding="utf-8")
    assert "## Problem List" in markdown
    assert "## Next Session Prep" in markdown
    payload = json.loads(written.json_path.read_text(encoding="utf-8"))
    assert payload["spoken_summary"] == report["spoken_summary"]


def test_report_output_must_stay_under_journal_reports(session_corpus: Path) -> None:
    report = build_session_report([session_corpus], grip_ceiling_g=2.5, generated_at="stamp")

    with pytest.raises(SessionReviewError, match="journal/reports"):
        write_session_report(report, output_dir="exports")


def test_cli_generates_json_result(
    session_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--lap-dir", str(session_corpus), "--json", "--grip-ceiling-g", "2.5"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["markdown"]).is_file()
    assert Path(payload["json"]).is_file()
    assert payload["screen_summary"]


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
