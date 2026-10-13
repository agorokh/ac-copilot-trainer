"""Synthetic-only MOZA processed views; no vendor or personal lap fixtures."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tools.lap_qualification import USES, qualify_archive
from tools.moza_ingest import MOZA_IMPORT_FORMAT, MozaImportError, normalize_view, reader
from tools.moza_ingest.__main__ import main


def view() -> dict:
    points = [
        {
            "distance": distance,
            "time": time,
            "speed": 90.0,
            "throttle": 25.0,
            "brake": 50.0,
            "gear": 3,
            "steering": -8.0,
            "x": distance,
            "y": 12.0,
        }
        for distance, time in [(2.0, 0.12), (500.0, 20.0), (997.0, 39.9)]
    ]
    overview = {
        "lapId": "synthetic-lap",
        "carModel": "Synthetic Car",
        "track": {"trackName": "Synthetic Track", "trackId": "synthetic_track", "trackConfig": ""},
        "lapTime": 40.0,
        "lapNumber": 1,
        "sampleCount": 123,
        "finishedLap": True,
        "isValidLap": True,
    }
    return {
        "schemaVersion": "tracecore.view.v1",
        "overview": overview,
        "details": {
            "lapId": "synthetic-lap",
            "summary": {
                **{key: value for key, value in copy.deepcopy(overview).items() if key != "track"},
                **overview["track"],
            },
            "segments": [
                {
                    "id": "segment-1",
                    "startDistance": 0.0,
                    "endDistance": 1000.0,
                    "startMapProgress": 0.0,
                    "endMapProgress": 1.0,
                    "points": points,
                }
            ],
        },
    }


def source(payload: dict) -> dict:
    raw = json.dumps(payload, allow_nan=False).encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "captured_at": "2026-10-13T00:00:00+00:00",
        "status": "stable_captured_bytes",
    }


def imported(payload: dict | None = None) -> dict:
    payload = view() if payload is None else payload
    return normalize_view(payload, source=source(payload))


def evaluation(*, intervened=True, evaluated=0) -> dict:
    return {
        "schemaVersion": 1,
        "sessionId": "synthetic-session",
        "algorithmVersion": "synthetic-v1",
        "summary": {
            "observedLapCount": 1,
            "completeLapCount": 1,
            "evaluatedLapCount": evaluated,
            "laps": [
                {
                    "id": "synthetic-lap",
                    "recordUid": "synthetic-lap",
                    "sessionId": "synthetic-session",
                    "lapTimeSeconds": 40.0,
                    "lapNumber": 1,
                    "complete": True,
                    "finalized": True,
                    "isValidLap": True,
                    "aiIntervened": intervened,
                    "eligibility": "ai-debug-only" if intervened else "eligible",
                    "totalScore": 99.0,
                    "stabilityScore": 88.0,
                    "dimensions": [{"score": 95.0}],
                }
            ],
        },
    }


def test_accepted_inspection_is_sparse_and_cannot_be_promoted(monkeypatch, tmp_path):
    ledger = tmp_path / "empty-ledger.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}))
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    record = imported()
    assert record["source"] == "imported"
    assert record["import_format"] == MOZA_IMPORT_FORMAT != "motec_csv"
    assert record["import_status"] == "accepted_for_inspection"
    assert record["lap"] == {
        "lap_n": 1,
        "lap_ms": 40000,
        "is_pb": False,
        "is_valid": True,
        "complete": True,
    }
    fields = record["trace"]["fields"]
    assert not {"steer", "eMs", "spline", "px", "py", "pz"} & set(fields)
    assert record["trace"]["samples"][0][fields.index("throttle")] == 0.25
    assert record["trace"]["samples"][0][fields.index("brake")] == 0.5
    assert record["trace"]["samples"][0][fields.index("moza_steering")] == -8
    assert record["moza"]["declared_sample_count"] == 123
    assert record["trace"]["samples_count"] == 3
    assert record["car"]["id"] is None and record["track"]["layout"] is None
    assert record["qualification"]["authority"] == "unknown"
    assert not any(record["qualification"]["supported_uses"].values())
    for use in USES:
        result = qualify_archive(
            record, use=use, expected_combo=("different_car", "different_track", "layout")
        )
        assert not result.allowed
        assert "attribution_store_unavailable" not in result.reasons
    assert record["moza"]["processed_extent"]["first_time_s"] == 0.12
    assert record["moza"]["processed_extent"]["lap_minus_last_time_s"] == pytest.approx(0.1)


def test_missing_optional_channels_validity_and_conditions_are_not_filled():
    payload = view()
    for section in (payload["overview"], payload["details"]["summary"]):
        section.pop("isValidLap")
        section["finishedLap"] = False
    points = payload["details"]["segments"][0]["points"]
    points[1].pop("steering")
    points[1]["throttle"] = None
    record = imported(payload)
    assert record["lap"]["is_valid"] is None
    assert record["lap"]["complete"] is False
    assert record["conditions"] == {}
    assert "throttle" not in record["trace"]["fields"]
    assert "moza_steering" not in record["trace"]["fields"]
    assert record["moza"]["missing_channel_counts"]["steering"] == 1
    assert record["moza"]["incomplete_channels"]["steering"]["values"] == [-8.0, None, -8.0]


def test_repeated_processed_points_preserved_without_coverage_repair():
    payload = view()
    points = payload["details"]["segments"][0]["points"]
    points.insert(1, copy.deepcopy(points[0]))
    record = imported(payload)
    assert record["trace"]["samples_count"] == 4
    assert record["moza"]["processed_extent"]["nonforward_distance_steps"] == 1
    assert record["moza"]["processed_extent"]["nonforward_time_steps"] == 1
    assert record["moza"]["native_coverage"] == "unavailable"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda p: p.update(schemaVersion="tracecore.view.v2"), "unsupported_view_schema"),
        (lambda p: p.update(overview=[]), "invalid_overview"),
        (lambda p: p["details"].update(summary=[]), "invalid_detail_summary"),
        (lambda p: p["details"].update(lapId="other"), "lap_identity_mismatch"),
        (lambda p: p["overview"].update(sampleCount=True), "invalid_sample_count"),
        (lambda p: p.update(conditions=[]), "invalid_conditions"),
        (lambda p: p.update(appVersion={}), "invalid_source_version"),
        (lambda p: p.update(viewVersion="unknown"), "view_version_mismatch"),
        (lambda p: p["overview"].update(track="Synthetic Track"), "invalid_track_metadata"),
        (
            lambda p: p["details"]["summary"].update(trackId="wrong"),
            "producer_track_identity_conflict",
        ),
        (lambda p: p["details"].update(segments={}), "invalid_segments"),
        (lambda p: p["details"]["segments"][0].update(points=[]), "invalid_segment_points"),
        (
            lambda p: p["details"]["segments"][0]["points"][0].update(speed="90"),
            "invalid_point_speed",
        ),
        (
            lambda p: p["details"]["segments"][0]["points"][0].update(brake=101),
            "point_out_of_range_brake",
        ),
        (
            lambda p: p["details"]["segments"][0]["points"][0].update(gear=True),
            "invalid_point_gear",
        ),
    ],
)
def test_malformed_view_rejected(mutation, reason):
    payload = view()
    mutation(payload)
    with pytest.raises(MozaImportError, match=reason):
        imported(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_pure_normalizer_rejects_nonfinite(value):
    payload = view()
    receipt = source(payload)
    payload["details"]["segments"][0]["points"][0]["speed"] = value
    with pytest.raises(MozaImportError, match="nonfinite_json_value"):
        normalize_view(payload, source=receipt)


def test_duplicate_segments_and_summary_conflicts_rejected():
    payload = view()
    payload["details"]["segments"].append(copy.deepcopy(payload["details"]["segments"][0]))
    with pytest.raises(MozaImportError, match="duplicate_segment_identity"):
        imported(payload)
    payload = view()
    payload["details"]["summary"]["isValidLap"] = False
    with pytest.raises(MozaImportError, match="detail_summary_conflict"):
        imported(payload)


@pytest.mark.parametrize(
    "patch",
    [{"sha256": "bad"}, {"bytes": True}, {"status": "changed_in_flight"}, {"captured_at": []}],
)
def test_malformed_source_metadata_rejected(patch):
    payload = view()
    receipt = source(payload)
    receipt.update(patch)
    with pytest.raises(MozaImportError):
        normalize_view(payload, source=receipt)


def test_exact_evaluation_join_retains_ai_evidence_but_zero_advice():
    payload, ev = view(), evaluation()
    record = normalize_view(
        payload, source=source(payload), evaluation=ev, evaluation_source=source(ev)
    )
    result = record["moza"]["evaluation"]
    assert result["identity_join"] == "cache.lapId=evaluation.id=evaluation.recordUid"
    assert result["reason"] == "zero_evaluated_laps"
    assert result["advice"] is None and result["status"] == "unavailable"
    assert "totalScore" in result["observed_score_fields"] and "totalScore" not in result
    assert record["qualification"]["authority"] == "shared"
    assert record["session_uuid"] != ev["sessionId"]
    assert not any(record["qualification"]["supported_uses"].values())


def test_false_ai_flag_is_not_human_proof_or_advice():
    payload, ev = view(), evaluation(intervened=False, evaluated=1)
    record = normalize_view(
        payload, source=source(payload), evaluation=ev, evaluation_source=source(ev)
    )
    assert record["qualification"]["authority"] == "unknown"
    assert record["moza"]["evaluation"]["advice"] is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda e: e.update(schemaVersion="1"), "unsupported_evaluation_schema"),
        (lambda e: e.update(summary=[]), "invalid_evaluation_summary"),
        (lambda e: e["summary"].update(evaluatedLapCount=True), "invalid_evaluation_count"),
        (
            lambda e: e["summary"]["laps"][0].update(recordUid="other"),
            "evaluation_identity_conflict",
        ),
        (
            lambda e: e["summary"]["laps"][0].update(sessionId="other"),
            "evaluation_session_conflict",
        ),
        (lambda e: e["summary"]["laps"][0].update(lapTimeSeconds=41), "evaluation_lap_conflict"),
        (
            lambda e: e["summary"]["laps"].append(copy.deepcopy(e["summary"]["laps"][0])),
            "duplicate_evaluation_identity",
        ),
    ],
)
def test_evaluation_identity_and_shape_fail_closed(mutation, reason):
    payload, ev = view(), evaluation()
    mutation(ev)
    with pytest.raises(MozaImportError, match=reason):
        normalize_view(payload, source=source(payload), evaluation=ev, evaluation_source=source(ev))


def test_unmatched_evaluation_does_not_assign_authority():
    payload, ev = view(), evaluation()
    ev["summary"]["laps"][0].update(id="other", recordUid="other")
    record = normalize_view(
        payload, source=source(payload), evaluation=ev, evaluation_source=source(ev)
    )
    assert record["qualification"]["authority"] == "unknown"
    assert record["moza"]["evaluation"]["reason"] == "evaluation_identity_unmatched"


def test_stable_selected_reader_has_exact_bytes_and_hash(tmp_path):
    path = tmp_path / "cache.json"
    raw = json.dumps(view()).encode()
    path.write_bytes(raw)
    result = reader.read_selected_json(path)
    assert result.payload == view()
    assert result.receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result.receipt["bytes"] == len(raw)
    assert result.receipt["cross_file_atomic"] is False
    assert path.read_bytes() == raw


@pytest.mark.parametrize(
    "raw,reason",
    [
        (b'{"x":1,"x":2}', "duplicate_json_key"),
        (b'{"x":NaN}', "nonfinite_json_value"),
        (b'{"x":Infinity}', "nonfinite_json_value"),
        (b"[]", "json_root_not_object"),
        (b"null", "json_root_not_object"),
        (b"\xff", "invalid_json"),
    ],
)
def test_strict_json_reader(tmp_path, raw, reason):
    path = tmp_path / "cache.json"
    path.write_bytes(raw)
    with pytest.raises(MozaImportError, match=reason):
        reader.read_selected_json(path)


def test_changed_in_flight_even_same_size_and_mtime_rejected(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    path.write_bytes(b'{"x":1}')
    original_stat = path.stat()
    original_read = reader._read_once
    calls = 0

    def changed(selected, limit):
        nonlocal calls
        result = original_read(selected, limit)
        calls += 1
        if calls == 1:
            selected.write_bytes(b'{"x":2}')
            os.utime(selected, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        return result

    monkeypatch.setattr(reader, "_read_once", changed)
    with pytest.raises(MozaImportError, match="input_changed_during_read"):
        reader.read_selected_json(path)


def test_replaced_identity_rejected(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    path.write_bytes(b"{}")
    original_read = reader._read_once
    calls = 0

    def replaced(selected, limit):
        nonlocal calls
        result = original_read(selected, limit)
        calls += 1
        if calls == 1:
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(b"{}")
            replacement.replace(selected)
        return result

    monkeypatch.setattr(reader, "_read_once", replaced)
    with pytest.raises(MozaImportError, match="input_changed_during_read"):
        reader.read_selected_json(path)


def test_reader_size_and_regular_file_bounds(tmp_path):
    path = tmp_path / "cache.json"
    path.write_bytes(b'{"x":1}')
    with pytest.raises(MozaImportError, match="input_too_large"):
        reader.read_selected_json(path, max_bytes=3)
    with pytest.raises(MozaImportError, match="input_not_regular_file"):
        reader.read_selected_json(tmp_path)


def test_write_once_alias_existing_and_atomic_publication(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text("{}")
    output = tmp_path / "output.json"
    with pytest.raises(MozaImportError, match="output_aliases_input"):
        reader.write_once_json(path, {"x": 1}, inputs=[path])
    hardlink = tmp_path / "input-link.json"
    os.link(path, hardlink)
    with pytest.raises(MozaImportError, match="output_aliases_input"):
        reader.write_once_json(hardlink, {"x": 1}, inputs=[path])
    real_link = reader.os.link

    def assert_complete(temporary, destination):
        assert not destination.exists()
        assert json.loads(temporary.read_text()) == {"x": 1}
        real_link(temporary, destination)

    monkeypatch.setattr(reader.os, "link", assert_complete)
    reader.write_once_json(output, {"x": 1}, inputs=[path])
    assert json.loads(output.read_text()) == {"x": 1}
    with pytest.raises(MozaImportError, match="output_exists"):
        reader.write_once_json(output, {"x": 2}, inputs=[path])
    assert not list(tmp_path.glob(".moza-import-*"))
    assert path.read_text() == "{}"


def test_failed_publication_leaves_no_partial_output(tmp_path, monkeypatch):
    output = tmp_path / "output.json"

    def failure(*_args):
        raise OSError("synthetic unsupported link")

    monkeypatch.setattr(reader.os, "link", failure)
    with pytest.raises(MozaImportError, match="output_publication_failed"):
        reader.write_once_json(output, {"x": 1})
    assert not output.exists()
    assert not list(tmp_path.iterdir())


def test_cli_only_selected_files_no_overwrite_and_no_live_promotion(tmp_path, capsys):
    path, ev_path, output = tmp_path / "cache.json", tmp_path / "eval.json", tmp_path / "out.json"
    path.write_text(json.dumps(view()))
    ev_path.write_text(json.dumps(evaluation()))
    args = ["--cache", str(path), "--evaluation", str(ev_path), "--output", str(output)]
    assert main(args) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["production_eligible"] is False
    original_output = output.read_bytes()
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "output_exists"
    assert output.read_bytes() == original_output


def test_invalid_cli_input_does_not_write_output(tmp_path, capsys):
    path, output = tmp_path / "cache.json", tmp_path / "out.json"
    path.write_text('{"schemaVersion":"future"}')
    assert main(["--cache", str(path), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "unsupported_view_schema"
    assert not output.exists()


def test_event_annotations_and_producer_ids_remain_unqualified():
    payload = view()
    payload["details"]["summary"].update(trackId="producer_track", trackConfig="variant")
    payload["overview"]["track"].update(trackId="producer_track", trackConfig="variant")
    interval = {
        "startDistance": 5,
        "endDistance": 10,
        "startMapProgress": 0.005,
        "endMapProgress": 0.01,
        "startTime": 1,
        "endTime": 2,
    }
    payload["details"]["drivingEvents"] = {
        "axis": "mapDistance",
        "distanceUnit": "m",
        "series": [{"id": "tire_slip", "available": True, "intervals": [interval]}],
    }
    record = imported(payload)
    events = record["moza"]["diagnostic_events"]
    assert events["status"] == "unqualified"
    assert events["series"][0]["intervals"][0] == interval
    assert record["moza"]["producer_identity"]["trackId"] == "producer_track"
    assert record["track"]["id"] is None
    assert record["coaching"]["rules_hints"] == []
    payload["details"]["drivingEvents"]["distanceUnit"] = "unknown"
    with pytest.raises(MozaImportError, match="unsupported_event_axis_or_units"):
        imported(payload)


@pytest.mark.parametrize("value", [1e308, -1.0, 0.0])
def test_invalid_lap_duration_is_structured_error(value):
    payload = view()
    payload["overview"]["lapTime"] = value
    payload["details"]["summary"]["lapTime"] = value
    with pytest.raises(MozaImportError, match="invalid_lap_time"):
        imported(payload)


def test_json_float_overflow_is_rejected_by_reader(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"number":1e999}')
    with pytest.raises(MozaImportError, match="nonfinite_json_value"):
        reader.read_selected_json(path)


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"lapNumber": True}, "invalid_evaluation_lap_number"),
        ({"isValidLap": False}, "evaluation_lap_status_conflict"),
        ({"complete": False}, "evaluation_lap_status_conflict"),
    ],
)
def test_evaluation_status_does_not_override_conflicting_cache(patch, reason):
    payload, ev = view(), evaluation()
    ev["summary"]["laps"][0].update(patch)
    with pytest.raises(MozaImportError, match=reason):
        normalize_view(payload, source=source(payload), evaluation=ev, evaluation_source=source(ev))


def test_source_timestamp_requires_timezone_and_actual_iso_datetime():
    payload = view()
    for bad in ("not-a-date", "2026-10-13", "2026-10-13T12:00:00"):
        receipt = source(payload)
        receipt["captured_at"] = bad
        with pytest.raises(MozaImportError, match="invalid_source_timestamp"):
            normalize_view(payload, source=receipt)


def test_racing_output_creation_never_overwrites_competitor(tmp_path, monkeypatch):
    output = tmp_path / "output.json"
    original_link = reader.os.link

    def raced(temporary, destination):
        destination.write_text("operator contents")
        original_link(temporary, destination)

    monkeypatch.setattr(reader.os, "link", raced)
    with pytest.raises(MozaImportError, match="output_exists"):
        reader.write_once_json(output, {"x": 1})
    assert output.read_text() == "operator contents"
    assert not list(tmp_path.glob(".moza-import-*"))


def test_optional_evaluation_requires_its_source_receipt():
    payload = view()
    with pytest.raises(MozaImportError, match="evaluation_source_required"):
        normalize_view(payload, source=source(payload), evaluation=evaluation())


def test_evaluation_stale_session_and_algorithm_metadata_rejected():
    payload, ev = view(), evaluation()
    ev["sessionStartedAtMs"] = 1000
    ev["savedAtMs"] = 999
    with pytest.raises(MozaImportError, match="evaluation_timestamp_conflict"):
        normalize_view(payload, source=source(payload), evaluation=ev, evaluation_source=source(ev))
    ev["savedAtMs"] = 1001
    ev["algorithmVersion"] = {"version": 1}
    with pytest.raises(MozaImportError, match="invalid_evaluation_version"):
        normalize_view(payload, source=source(payload), evaluation=ev, evaluation_source=source(ev))


@pytest.mark.parametrize(
    "operation,reason", [("read", "input_unavailable_or_changed"), ("write", "invalid_output")]
)
def test_resolve_runtime_error_is_structured(tmp_path, monkeypatch, operation, reason):
    path = tmp_path / "loop.json"

    def loop(*_args, **_kwargs):
        raise RuntimeError("synthetic symlink loop")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "resolve", loop)
        with pytest.raises(MozaImportError, match=reason):
            if operation == "read":
                reader.read_selected_json(path)
            else:
                reader.write_once_json(path, {"x": 1})
    assert not path.exists()
