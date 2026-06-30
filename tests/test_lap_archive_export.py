from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from tools import lap_archive_export

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_archive(
    path: Path,
    *,
    lap_uuid: str,
    session_uuid: str = "session-fallback",
    car_id: str = "ks_abarth500_assetto_corse",
    track_id: str = "magione",
    lap_n: int = 1,
    lap_ms: int | None = None,
    fields: list[str] | None = None,
    samples: list[list[float | int]] | None = None,
) -> None:
    lap: dict[str, object] = {"lap_n": lap_n, "is_valid": True}
    if lap_ms is not None:
        lap["lap_ms"] = lap_ms
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lap_uuid": lap_uuid,
                "session_uuid": session_uuid,
                "car": {"id": car_id},
                "track": {"id": track_id},
                "lap": lap,
                "trace": {
                    "fields": ["eMs", "speed"] if fields is None else fields,
                    "samples": [[0, 80.0]] if samples is None else samples,
                },
            }
        ),
        encoding="utf-8",
    )


def test_csv_export_produces_stable_columns_from_fixture(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out = Path("lap.csv")
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


def test_invalid_laps_are_filtered_by_default_and_can_be_included(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    default_out = Path("default.csv")
    include_out = Path("include.csv")
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


def test_missing_trace_fields_export_as_blank_cells(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out = Path("missing.csv")

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


def test_motec_csv_export_writes_quoted_header_units_and_rows(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out = Path("lap_motec.csv")

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


def test_motec_csv_uses_trace_elapsed_when_lap_ms_is_missing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "lap_001.json"
    second = tmp_path / "lap_002.json"
    out = Path("fallback_motec.csv")

    _write_archive(
        first,
        lap_uuid="lap-without-ms-1",
        lap_n=1,
        samples=[[0, 80.0], [1000, 100.0], [3000, 110.0]],
    )
    _write_archive(
        second,
        lap_uuid="lap-without-ms-2",
        lap_n=2,
        lap_ms=0,
        samples=[[0, 90.0], [2000, 120.0]],
    )

    count = lap_archive_export.export_motec_csv([first, second], out)

    assert count == 5
    with out.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[8] == ["Beacon Markers", "3 5"]
    data_rows = rows[11:]
    assert [row[0] for row in data_rows] == ["0", "1", "3", "3", "5"]
    assert [row[12] for row in data_rows] == ["3", "3", "3", "2", "2"]


def test_motec_csv_beacons_follow_exported_sample_range(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "lap_001.json"
    second = tmp_path / "lap_002.json"
    out = Path("sparse_motec.csv")
    _write_archive(
        first,
        lap_uuid="complete-lap",
        lap_n=1,
        lap_ms=3000,
        samples=[[0, 80.0], [3000, 100.0]],
    )
    _write_archive(
        second,
        lap_uuid="sparse-lap",
        lap_n=2,
        lap_ms=91000,
        samples=[[0, 90.0], [5000, 120.0]],
    )

    count = lap_archive_export.export_motec_csv([first, second], out)

    assert count == 4
    with out.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[5][5] == "8"
    assert rows[6][1] == "8"
    assert rows[8] == ["Beacon Markers", "3 8"]
    data_rows = rows[11:]
    assert [row[0] for row in data_rows] == ["0", "3", "3", "8"]
    assert [row[12] for row in data_rows] == ["3", "3", "91", "91"]


def test_motec_csv_ignores_empty_trace_for_beacons_and_offsets(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "lap_001.json"
    second = tmp_path / "lap_002.json"
    out = Path("empty_trace_motec.csv")
    _write_archive(
        first,
        lap_uuid="empty-trace-lap",
        lap_n=1,
        lap_ms=90000,
        samples=[],
    )
    _write_archive(
        second,
        lap_uuid="timed-lap",
        lap_n=2,
        lap_ms=3000,
        samples=[[0, 90.0], [3000, 120.0]],
    )

    count = lap_archive_export.export_motec_csv([first, second], out)

    assert count == 2
    with out.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[5][5] == "3"
    assert rows[8] == ["Beacon Markers", "3"]
    assert [row[0] for row in rows[11:]] == ["0", "3"]


def test_motec_csv_rejects_mixed_session_inputs(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "lap_001.json"
    second = tmp_path / "lap_002.json"
    out = Path("mixed_motec.csv")
    _write_archive(first, lap_uuid="session-a-lap", session_uuid="session-a")
    _write_archive(second, lap_uuid="session-b-lap", session_uuid="session-b")

    rc = lap_archive_export.main(
        ["--format", "motec-csv", "--output", str(out), str(first), str(second)]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "motec-csv inputs must contain one session/car/track" in captured.err
    assert not out.exists()


def test_cli_writes_csv(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out = Path("cli.csv")

    rc = lap_archive_export.main(["--output", str(out), str(_FIXTURES / "lap_archive_valid.json")])

    captured = capsys.readouterr()
    assert rc == 0
    assert "wrote 3 sample rows" in captured.out
    assert _rows(out)[0]["lap_uuid"] == "lap-valid"


def test_csv_stream_writes_to_file_like_without_temp_path() -> None:
    out = io.StringIO()

    count = lap_archive_export.export_csv_stream([_FIXTURES / "lap_archive_valid.json"], out)

    assert count == 3
    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert rows[0]["lap_uuid"] == "lap-valid"
    assert rows[0]["session_uuid"] == "session-a"


def test_cli_streams_csv_to_stdout_and_summary_to_stderr(capsys) -> None:
    rc = lap_archive_export.main(["--output", "-", str(_FIXTURES / "lap_archive_valid.json")])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.startswith("source_file,lap_uuid,session_uuid")
    assert "lap-valid" in captured.out
    assert "wrote 3 sample rows to -" in captured.err


def test_cli_rejects_missing_input_path(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out = Path("cli.csv")
    missing = Path("missing.json")

    rc = lap_archive_export.main(["--output", str(out), str(missing)])

    captured = capsys.readouterr()
    assert rc == 2
    assert "input path does not exist" in captured.err
    assert not out.exists()


def test_cli_rejects_absolute_output_path(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "absolute.csv"

    rc = lap_archive_export.main(["--output", str(out), str(_FIXTURES / "lap_archive_valid.json")])

    captured = capsys.readouterr()
    assert rc == 2
    assert "output path must be relative" in captured.err
    assert not out.exists()


def test_cli_rejects_escaping_output_path(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    escaped = tmp_path.parent / "escaped-laps.csv"

    rc = lap_archive_export.main(
        ["--output", "../escaped-laps.csv", str(_FIXTURES / "lap_archive_valid.json")]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "output path must stay within" in captured.err
    assert not escaped.exists()
