"""MoTeC CSV import tests for issue #79."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tools.import_motec import (
    ImportOptions,
    MotecImportError,
    default_output_dir,
    import_file,
    main,
    parse_motec_csv,
)


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    path.write_text(
        "\n".join(",".join(str(cell) for cell in row) for row in rows), encoding="utf-8"
    )


def test_import_motec_writes_schema_v1_reference_lap(tmp_path: Path) -> None:
    csv_path = tmp_path / "motec.csv"
    _write_csv(
        csv_path,
        [
            ["Lap", "Time", "Distance", "Speed", "Throttle", "Brake", "Steering", "Gear", "RPM"],
            ["", "s", "m", "km/h", "%", "%", "deg", ""],
            [1, 0.0, 0, 100, 0, 0, 0, 2, 5000],
            [1, 2.5, 250, 140, 50, 0, 45, 3, 6500],
            [1, 5.0, 500, 120, 100, 20, 90, 4, 7000],
            [1, 7.5, 750, 130, 80, 0, 45, 4, 7200],
            [1, 10.0, 1000, 150, 100, 0, 0, 5, 7400],
        ],
    )

    results = import_file(
        csv_path,
        ImportOptions(
            car="ks_porsche_911_gt3_rs",
            track="ks_magione",
            output_dir=tmp_path / "laps",
            track_length_m=1000,
        ),
    )

    assert len(results) == 1
    record = json.loads(results[0].path.read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["source"] == "imported"
    assert record["import_format"] == "motec_csv"
    assert record["lap"]["is_pb"] is False
    assert record["lap"]["is_valid"] is True
    assert record["car"]["id"] == "ks_porsche_911_gt3_rs"
    assert record["track"]["id"] == "ks_magione"
    assert record["trace"]["fields"] == [
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
        "rpm",
    ]
    assert record["trace"]["samples_count"] == 2000
    assert len(record["trace"]["samples"]) == 2000
    mid = record["trace"]["samples"][1000]
    assert mid[0] == pytest.approx(0.5, abs=1e-9)
    assert mid[3] == pytest.approx(1.0)
    assert mid[4] == pytest.approx(0.2)
    assert mid[5] == pytest.approx(0.2)  # 90 deg / default 450 deg steering lock
    assert mid[-1] == pytest.approx(7000)
    assert record["lap"]["lap_ms"] == pytest.approx(9995, abs=5)


def test_import_motec_splits_multi_lap_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "multi.csv"
    _write_csv(
        csv_path,
        [
            ["Lap", "Time", "distance_m", "speed_kmh", "tps", "bps", "steering_angle", "gear"],
            [1, 0, 0, 80, 0.0, 0.0, 0.0, 2],
            [1, 5, 500, 120, 1.0, 0.0, 0.2, 3],
            [2, 0, 0, 90, 0.0, 0.0, 0.0, 2],
            [2, 4, 500, 130, 1.0, 0.0, 0.2, 3],
        ],
    )

    results = import_file(
        csv_path,
        ImportOptions(car="car", track="track", output_dir=tmp_path / "laps", track_length_m=500),
    )

    assert [r.lap_number for r in results] == [1, 2]
    assert len(list((tmp_path / "laps").glob("lap_imported_*_motec_*.json"))) == 2


def test_import_motec_respects_radian_steering_units(tmp_path: Path) -> None:
    csv_path = tmp_path / "rad.csv"
    _write_csv(
        csv_path,
        [
            ["Time", "Distance", "Speed", "Throttle", "Brake", "Steering", "Gear"],
            ["s", "m", "km/h", "", "", "rad", ""],
            [0, 0, 100, 0, 0, 0, 2],
            [1, 100, 100, 1, 0, math.pi / 2, 3],
        ],
    )

    results = import_file(
        csv_path,
        ImportOptions(car="car", track="track", output_dir=tmp_path / "laps", track_length_m=100),
    )
    record = json.loads(results[0].path.read_text(encoding="utf-8"))

    assert record["trace"]["samples"][-1][5] == pytest.approx(0.2, abs=0.01)


def test_import_motec_reports_missing_required_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad.csv"
    _write_csv(csv_path, [["Time", "Distance", "Speed"], [0, 0, 100], [1, 100, 120]])

    with pytest.raises(MotecImportError, match="could not find a header"):
        parse_motec_csv(csv_path)


def test_import_motec_integrates_elapsed_without_time_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "integrated.csv"
    _write_csv(
        csv_path,
        [
            ["Spline", "Speed", "Throttle", "Brake", "Steering", "Gear"],
            ["", "mph", "%", "%", "", ""],
            [0.0, 60, 0, 0, 0, "N"],
            [0.5, 60, 50, 10, 0.5, 3],
            [0.5, 70, 70, 0, 0.2, 4],
            [1.0, 60, 100, 0, 0, "R"],
        ],
    )

    results = import_file(
        csv_path,
        ImportOptions(
            car="car",
            track="track",
            output_dir=tmp_path / "laps",
            track_length_m=1000,
        ),
    )
    record = json.loads(results[0].path.read_text(encoding="utf-8"))
    samples = record["trace"]["samples"]

    assert record["lap"]["lap_ms"] > 30_000
    assert samples[1000][1] == pytest.approx(70 * 1.609344)
    assert samples[1000][2] > samples[999][2]
    assert samples[1000][3] == pytest.approx(0.7)
    assert samples[1000][4] == pytest.approx(0.0)
    assert samples[-1][6] == -1


def test_import_motec_main_uses_csp_state_default_output_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = tmp_path / "cli.csv"
    _write_csv(
        csv_path,
        [
            ["Time", "Distance", "Speed", "Throttle", "Brake", "Steering", "Gear"],
            [0, 0, 100, 0, 0, 0, 2],
            [1, 100, 100, 1, 0, 0, 3],
        ],
    )

    rc = main(
        [
            str(csv_path),
            "--car",
            "car",
            "--track",
            "track",
            "--csp-state-dir",
            str(tmp_path / "state"),
            "--samples",
            "8",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "lap_ms=875" in out
    assert (tmp_path / "state" / "ac_copilot_trainer" / "journal" / "laps").exists()


def test_default_output_dir_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opts = ImportOptions(car="car", track="track")

    monkeypatch.setenv("AC_COPILOT_LAP_ARCHIVE_DIR", str(tmp_path / "env-laps"))
    assert default_output_dir(opts) == tmp_path / "env-laps"

    monkeypatch.delenv("AC_COPILOT_LAP_ARCHIVE_DIR")
    monkeypatch.setenv("AC_COPILOT_CSP_STATE_DIR", str(tmp_path / "state-env"))
    assert (
        default_output_dir(opts)
        == tmp_path / "state-env" / "ac_copilot_trainer" / "journal" / "laps"
    )

    monkeypatch.delenv("AC_COPILOT_CSP_STATE_DIR")
    monkeypatch.setattr("tools.import_motec._use_windows_ac_default", lambda: False)
    monkeypatch.chdir(tmp_path)
    assert default_output_dir(opts) == tmp_path / "journal" / "laps"
