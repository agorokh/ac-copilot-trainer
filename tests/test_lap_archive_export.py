from __future__ import annotations

import csv
import json
from pathlib import Path

from tools import lap_archive_export

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_csv_export_produces_stable_columns_from_fixture(tmp_path: Path) -> None:
    out = tmp_path / "lap.csv"
    count = lap_archive_export.export_csv([_FIXTURES / "lap_archive_valid.json"], out)

    rows = _rows(out)
    assert count == 3
    assert rows
    assert list(rows[0]) == list(lap_archive_export.CSV_COLUMNS)
    assert rows[1]["source_file"] == "lap_archive_valid.json"
    assert rows[1]["speed_kmh"] == "150.5"
    assert rows[1]["brake"] == "0.2"
    assert rows[1]["throttle"] == "0.7"
    assert rows[1]["steering"] == "-0.05"
    assert rows[1]["gear"] == "4"
    assert rows[1]["spline"] == "0.5"
    assert rows[1]["lap_distance_m"] == "1262.5"
    assert rows[1]["position_x_m"] == "20"
    assert rows[1]["position_y_m"] == "0.2"
    assert rows[1]["position_z_m"] == "30"


def test_invalid_laps_are_filtered_by_default_and_can_be_included(tmp_path: Path) -> None:
    default_out = tmp_path / "default.csv"
    include_out = tmp_path / "include.csv"
    inputs = [
        _FIXTURES / "lap_archive_valid.json",
        _FIXTURES / "lap_archive_invalid.json",
    ]

    default_count = lap_archive_export.export_csv(inputs, default_out)
    include_count = lap_archive_export.export_csv(inputs, include_out, include_invalid=True)

    assert default_count == 3
    assert {row["lap_uuid"] for row in _rows(default_out)} == {"lap-valid"}
    assert include_count == 4
    assert {row["lap_uuid"] for row in _rows(include_out)} == {"lap-valid", "lap-invalid"}


def test_missing_trace_fields_export_as_blank_cells(tmp_path: Path) -> None:
    out = tmp_path / "missing.csv"

    count = lap_archive_export.export_csv([_FIXTURES / "lap_archive_missing_fields.json"], out)

    assert count == 1
    row = _rows(out)[0]
    assert row["lap_uuid"] == "lap-missing-fields"
    assert row["speed_kmh"] == "88"
    assert row["time_s"] == "5"
    assert row["brake"] == ""
    assert row["throttle"] == ""
    assert row["steering"] == ""
    assert row["gear"] == ""
    assert row["position_x_m"] == ""
    assert row["lap_distance_m"] == ""


def test_motec_csv_export_writes_quoted_header_units_and_rows(tmp_path: Path) -> None:
    out = tmp_path / "lap_motec.csv"

    count = lap_archive_export.export_motec_csv([_FIXTURES / "lap_archive_valid.json"], out)

    assert count == 3
    with out.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][:2] == ["Driver", "AC Copilot Trainer"]
    assert rows[8][0] == "Beacon Markers"
    assert rows[9][:4] == ["Time", "Ground Speed", "Brake Pos", "Throttle Pos"]
    assert rows[10][:4] == ["s", "km/h", "%", "%"]
    assert rows[12][0] == "45"
    assert rows[12][1] == "150.5"
    assert rows[12][2] == "20"
    assert rows[12][3] == "70"


def test_motec_csv_uses_trace_elapsed_when_lap_ms_is_missing(tmp_path: Path) -> None:
    first = tmp_path / "lap_001.json"
    second = tmp_path / "lap_002.json"
    out = tmp_path / "fallback_motec.csv"

    first.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lap_uuid": "lap-without-ms-1",
                "session_uuid": "session-fallback",
                "lap": {"lap_n": 1, "is_valid": True},
                "trace": {
                    "fields": ["eMs", "speed"],
                    "samples": [[0, 80.0], [1000, 100.0], [3000, 110.0]],
                },
            }
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lap_uuid": "lap-without-ms-2",
                "session_uuid": "session-fallback",
                "lap": {"lap_n": 2, "lap_ms": 0, "is_valid": True},
                "trace": {
                    "fields": ["eMs", "speed"],
                    "samples": [[0, 90.0], [2000, 120.0]],
                },
            }
        ),
        encoding="utf-8",
    )

    count = lap_archive_export.export_motec_csv([first, second], out)

    assert count == 5
    with out.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[8] == ["Beacon Markers", "3 5"]
    data_rows = rows[11:]
    assert [row[0] for row in data_rows] == ["0", "1", "3", "3", "5"]
    assert [row[12] for row in data_rows] == ["3", "3", "3", "2", "2"]


def test_cli_writes_csv(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "cli.csv"

    rc = lap_archive_export.main(["--output", str(out), str(_FIXTURES / "lap_archive_valid.json")])

    captured = capsys.readouterr()
    assert rc == 0
    assert "wrote 3 sample rows" in captured.out
    assert _rows(out)[0]["lap_uuid"] == "lap-valid"


def test_cli_rejects_missing_input_path(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "cli.csv"
    missing = tmp_path / "missing.json"

    rc = lap_archive_export.main(["--output", str(out), str(missing)])

    captured = capsys.readouterr()
    assert rc == 2
    assert "input path does not exist" in captured.err
    assert not out.exists()
