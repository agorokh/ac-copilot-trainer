"""Integration tests for the tt_ingest retention pipeline + CLI parser (issue #353).

``retain_sessions`` is the local, network-free heart of ``export``: given already
fetched raw sessions it normalizes, immutably retains, and indexes them. These tests
drive it against the sanitized fixture and a ``tmp_path`` lake.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tt_ingest.cli import (
    INDEX_FILENAME,
    SESSIONS_INDEX_FILENAME,
    build_arg_parser,
    build_curriculum_from_files,
    build_reference_archive_from_files,
    coaching_endpoint,
    curriculum_endpoint,
    discover_curriculum_payloads,
    discover_reference_payloads,
    last_session_endpoint,
    last_session_window_endpoint,
    main,
    retain_coaching,
    retain_sessions,
)
from tools.tt_ingest.tt_normalize import TTNormalizeError

FIXTURE = Path(__file__).parent / "fixtures" / "tt_sessions_page.json"
LAST_SESSION_FIXTURE = Path(__file__).parent / "fixtures" / "tt_services_last_session.json"
DYNAMIC_REFERENCE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "tt_services_dynamic_reference.json"
)
ADVICE_FIXTURE = Path(__file__).parent / "fixtures" / "tt_services_advice.json"


def _sessions() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["sessions"]


def _last_session() -> dict:
    return json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))["data"]["session"]


def _bundle() -> dict:
    return {
        "reference_lap": {"username": "Reference Driver", "lap_time": "71035"},
        "reference_id": ["ref-uid-002", "20220611194228"],
        "segments": [
            {"segment": 1, "stories": [{"diagnosis": "Brake later", "time_loss": 0.12}]},
            {"segment": 2, "stories": [{"diagnosis": "Good corner", "time_loss": 0.0}]},
        ],
    }


def _curriculum_bundle() -> dict:
    return {
        "reference_lap": json.loads(DYNAMIC_REFERENCE_FIXTURE.read_text(encoding="utf-8"))["lap"],
        "dynamic_reference": ["ref-uid-002", "20220611194228"],
        "advice_reference": ["fake-uid-001", "20260629005756", "theoreticalBestRef"],
        "segments": [
            {"segment": 3, "advice_raw": json.loads(ADVICE_FIXTURE.read_text(encoding="utf-8"))}
        ],
    }


# --- retain_sessions end-to-end ---------------------------------------------------


def test_retain_sessions_writes_lake_tree(tmp_path) -> None:
    summary = retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    root = tmp_path / "journal" / "tt"
    assert summary.total == 3
    assert summary.retained_new == 3
    assert summary.skipped_existing == 0
    assert summary.lake_root == root

    # Raw session retained at the car/track/session path.
    raw = (
        root
        / "assettoCorsa"
        / "syn_mercedes_w09"
        / "ks_red_bull_ring"
        / "sess-aaa"
        / "session.json"
    )
    assert raw.exists()
    assert json.loads(raw.read_text())["id"] == "fake-uid-001#sess-aaa"

    # Both indexes present.
    sessions_index = json.loads((root / SESSIONS_INDEX_FILENAME).read_text())
    assert sessions_index["session_count"] == 3
    file_index = json.loads((root / INDEX_FILENAME).read_text())
    assert file_index["file_count"] == 3
    assert all("sha256" in f for f in file_index["files"])


def test_retain_sessions_is_immutable_on_rerun(tmp_path) -> None:
    retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    # Second run: same raw sessions are already present → all skipped, none re-written.
    summary = retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-29T00:00:00Z")
    assert summary.total == 3
    assert summary.retained_new == 0
    assert summary.skipped_existing == 3


def test_retain_sessions_summary_render(tmp_path) -> None:
    summary = retain_sessions(_sessions(), lake_base=tmp_path)
    rendered = summary.render()
    assert "retained 3 session(s)" in rendered
    assert "3 new" in rendered


def test_retain_sessions_empty(tmp_path) -> None:
    summary = retain_sessions([], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    assert summary.total == 0
    root = tmp_path / "journal" / "tt"
    assert (root / SESSIONS_INDEX_FILENAME).exists()
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 0


# --- argument parser --------------------------------------------------------------


def test_parser_export_defaults() -> None:
    args = build_arg_parser().parse_args(["export"])
    assert args.command == "export"
    assert args.limit == 50
    assert args.dry_run is False


def test_parser_export_flags() -> None:
    args = build_arg_parser().parse_args(
        ["export", "--limit", "10", "--max-pages", "2", "--dry-run", "--uid", "u9"]
    )
    assert args.limit == 10
    assert args.max_pages == 2
    assert args.dry_run is True
    assert args.uid == "u9"


def test_parser_auth_check() -> None:
    args = build_arg_parser().parse_args(["auth-check"])
    assert args.command == "auth-check"


def test_parser_coaching_defaults() -> None:
    args = build_arg_parser().parse_args(["coaching"])
    assert args.command == "coaching"
    assert args.segment_count == 7
    assert args.dry_run is False


def test_parser_coaching_flags() -> None:
    args = build_arg_parser().parse_args(["coaching", "--segment-count", "3", "--uid", "u9"])
    assert args.segment_count == 3
    assert args.uid == "u9"


def test_parser_reference_flags(tmp_path) -> None:
    out = tmp_path / "ref.json"
    args = build_arg_parser().parse_args(
        [
            "reference",
            "--input",
            str(LAST_SESSION_FIXTURE),
            "--output",
            str(out),
            "--allow-partial",
        ]
    )
    assert args.command == "reference"
    assert args.input == [LAST_SESSION_FIXTURE]
    assert args.output == out
    assert args.allow_partial is True


# --- retain_coaching (M-TT1) ------------------------------------------------------


def test_retain_coaching_writes_lake(tmp_path) -> None:
    summary = retain_coaching(_last_session(), _bundle(), lap=5, lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    session_dir = root / "assettoCorsa" / "ks_porsche_911_gt3_r_2016" / "magione" / "20260629005756"
    assert (session_dir / f"{last_session_endpoint(5)}.json").exists()
    coaching = json.loads((session_dir / f"{coaching_endpoint(5)}.json").read_text())
    assert coaching["reference_lap"]["username"] == "Reference Driver"
    assert summary.segments == 2
    assert summary.actionable == 1  # only the 0.12s loss is actionable; the 0.0 is not
    assert set(summary.written) == {last_session_endpoint(5), coaching_endpoint(5)}


def test_retain_coaching_per_lap_files_do_not_collide(tmp_path) -> None:
    # Two laps of the SAME session retain to distinct lap-keyed files — the write-once lake
    # never blocks the second lap, and each lap's last-session evidence stays coherent with
    # its coaching (PR #370 review fix).
    retain_coaching(_last_session(), _bundle(), lap=5, lake_base=tmp_path)
    summary = retain_coaching(_last_session(), _bundle(), lap=6, lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    session_dir = root / "assettoCorsa" / "ks_porsche_911_gt3_r_2016" / "magione" / "20260629005756"
    for lap in (5, 6):
        assert (session_dir / f"{coaching_endpoint(lap)}.json").exists()
        assert (session_dir / f"{last_session_endpoint(lap)}.json").exists()
    assert coaching_endpoint(6) in summary.written  # lap 6 was newly written, not blocked


def test_retain_coaching_is_write_once(tmp_path) -> None:
    retain_coaching(_last_session(), _bundle(), lap=5, lake_base=tmp_path)
    again = retain_coaching(_last_session(), _bundle(), lap=5, lake_base=tmp_path)
    assert again.written == []  # both endpoints already present → nothing re-written
    assert "nothing new" in again.render()


def test_retain_coaching_writes_distinct_segment_windows(tmp_path) -> None:
    first = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    second = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    second["data"]["telemetry"]["telemetry"]["reference"][0]["dist"] = 0.333333

    retain_coaching(
        _last_session(), _bundle(), lap=5, last_session_payload=first, lake_base=tmp_path
    )
    summary = retain_coaching(
        _last_session(), _bundle(), lap=5, last_session_payload=second, lake_base=tmp_path
    )

    root = tmp_path / "journal" / "tt"
    session_dir = root / "assettoCorsa" / "ks_porsche_911_gt3_r_2016" / "magione" / "20260629005756"
    endpoint = last_session_window_endpoint(5, second)
    assert endpoint in summary.written
    assert (session_dir / f"{endpoint}.json").exists()
    assert (session_dir / f"{last_session_endpoint(5)}.json").exists()


def test_retain_coaching_summary_render(tmp_path) -> None:
    rendered = retain_coaching(_last_session(), _bundle(), lap=5, lake_base=tmp_path).render()
    assert "session 20260629005756" in rendered
    assert "2 segment(s)" in rendered
    assert "1 actionable" in rendered


def test_retain_coaching_preserves_full_payload(tmp_path) -> None:
    # The FULL services payload (session + referenceLap + telemetry) must be retained as
    # last_session.json so the lake reconstructs what the endpoint returned (M-TT2 input).
    full = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    retain_coaching(
        _last_session(), _bundle(), lap=5, last_session_payload=full, lake_base=tmp_path
    )
    root = tmp_path / "journal" / "tt"
    session_dir = root / "assettoCorsa" / "ks_porsche_911_gt3_r_2016" / "magione" / "20260629005756"
    retained = json.loads((session_dir / f"{last_session_endpoint(5)}.json").read_text())
    assert retained.get("success") is True  # envelope preserved, not the stripped session
    assert "referenceLap" in retained["data"]  # reference evidence kept for M-TT2


def test_retain_coaching_indexes_endpoint_files(tmp_path) -> None:
    summary = retain_coaching(_last_session(), _bundle(), lap=5, lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    file_index = json.loads((root / INDEX_FILENAME).read_text())
    endpoints = {f["endpoint"] for f in file_index["files"]}
    assert {last_session_endpoint(5), coaching_endpoint(5)} <= endpoints
    assert summary.indexed == file_index["file_count"] >= 2


def test_reindex_lake_excludes_curriculum_endpoint(tmp_path) -> None:
    root = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    root.mkdir(parents=True)
    (root / f"{curriculum_endpoint(5)}.json").write_text("{}", encoding="utf-8")

    indexed = retain_sessions([], lake_base=tmp_path, generated_at="2026-06-30T00:00:00Z").indexed

    file_index = json.loads((tmp_path / "journal" / "tt" / INDEX_FILENAME).read_text())
    assert indexed == 0
    assert file_index["files"] == []


def test_retain_coaching_keys_on_given_session(tmp_path) -> None:
    # The lake key comes from the GIVEN session (game/car/track/session_key); a car object
    # (sessions-list shape) is unwrapped to its string id, never a dict-repr (#353 review).
    old = {
        "session_id": "u#20240101120000",
        "game_id": "assettoCorsa",
        "car": {"car_id": "ks_audi_r8_lms", "name": "Audi R8 LMS"},
        "track_id": "monza",
        "lap_number": 3,
    }
    retain_coaching(old, _bundle(), lap=3, lake_base=tmp_path)
    root = tmp_path / "journal" / "tt"
    assert (
        root
        / "assettoCorsa"
        / "ks_audi_r8_lms"
        / "monza"
        / "20240101120000"
        / f"{coaching_endpoint(3)}.json"
    ).exists()


# --- reference archive (M-TT2) ----------------------------------------------------


def test_build_reference_archive_from_files_writes_debug_partial(tmp_path) -> None:
    output = tmp_path / "tt_ref.json"
    summary = build_reference_archive_from_files(
        [LAST_SESSION_FIXTURE],
        output=output,
        allow_partial=True,
        track_length_m=2525.0,
        pretty=True,
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["import_format"] == "track_titan_reference_v1"
    assert record["generator"]["tt_reference"]["partial"] is True
    assert summary.partial is True
    assert summary.samples == record["trace"]["samples_count"]
    assert "PARTIAL debug" in summary.render()


def test_build_reference_archive_from_files_refuses_overwrite(tmp_path) -> None:
    output = tmp_path / "tt_ref.json"
    output.write_text("{}", encoding="utf-8")
    with pytest.raises(TTNormalizeError, match="output already exists"):
        build_reference_archive_from_files(
            [LAST_SESSION_FIXTURE],
            output=output,
            allow_partial=True,
            track_length_m=2525.0,
        )


def test_build_reference_archive_from_files_rejects_output_over_input(tmp_path) -> None:
    retained = tmp_path / f"{last_session_endpoint(5)}.json"
    retained.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="must not overwrite retained input"):
        build_reference_archive_from_files(
            [retained],
            output=retained,
            allow_partial=True,
            overwrite=True,
            track_length_m=2525.0,
        )


def test_build_reference_archive_from_files_wraps_write_error(tmp_path) -> None:
    parent_is_file = tmp_path / "not-a-dir"
    parent_is_file.write_text("x", encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="could not write"):
        build_reference_archive_from_files(
            [LAST_SESSION_FIXTURE],
            output=parent_is_file / "ref.json",
            allow_partial=True,
            track_length_m=2525.0,
        )


def test_discover_reference_payloads_filters_lake(tmp_path) -> None:
    root = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    root.mkdir(parents=True)
    raw = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    target = root / f"{last_session_endpoint(5)}.json"
    window = root / f"{last_session_window_endpoint(5, raw)}.json"
    target.write_text(json.dumps(raw), encoding="utf-8")
    window.write_text(json.dumps(raw), encoding="utf-8")

    assert discover_reference_payloads(lake_base=tmp_path, session_key="sess-1", lap=5) == [
        target,
        window,
    ]
    with pytest.raises(TTNormalizeError, match="no retained"):
        discover_reference_payloads(lake_base=tmp_path, session_key="sess-2", lap=5)


def test_discover_reference_payloads_requires_scope(tmp_path) -> None:
    root = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    root.mkdir(parents=True)

    with pytest.raises(TTNormalizeError, match="requires both"):
        discover_reference_payloads(lake_base=tmp_path, session_key="sess-1")
    with pytest.raises(TTNormalizeError, match="requires both"):
        discover_reference_payloads(lake_base=tmp_path, lap=5)


def test_reference_cli_requires_discovery_scope(tmp_path) -> None:
    first = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    second = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-2"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    raw = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    raw["data"]["session"]["id"] = "own#sess-1"
    raw["data"]["session"]["session_id"] = "own#sess-1"
    (first / f"{last_session_endpoint(5)}.json").write_text(json.dumps(raw), encoding="utf-8")
    raw["data"]["session"]["id"] = "own#sess-2"
    raw["data"]["session"]["session_id"] = "own#sess-2"
    (second / f"{last_session_endpoint(5)}.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SystemExit):
        main(
            [
                "reference",
                "--discover-lake",
                "--lake-base",
                str(tmp_path),
                "--output",
                str(tmp_path / "ref.json"),
                "--allow-partial",
            ]
        )


def test_reference_cli_writes_from_explicit_input(tmp_path, capsys) -> None:
    output = tmp_path / "cli_ref.json"
    rc = main(
        [
            "reference",
            "--input",
            str(LAST_SESSION_FIXTURE),
            "--output",
            str(output),
            "--allow-partial",
            "--track-length-m",
            "2525",
        ]
    )

    assert rc == 0
    assert output.exists()
    captured = capsys.readouterr().out
    assert "TT reference archive" in captured
    assert json.loads(output.read_text(encoding="utf-8"))["generator"]["tt_reference"]["partial"]


def test_reference_cli_requires_one_input_mode(tmp_path) -> None:
    with pytest.raises(SystemExit):
        main(["reference", "--output", str(tmp_path / "ref.json")])


# --- harness curriculum (M-TT3) ---------------------------------------------------


def test_build_curriculum_from_files_writes_artifact_and_pairs_session(tmp_path) -> None:
    session_dir = tmp_path / "lake" / "assettoCorsa" / "car" / "track" / "20260629005756"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output = session_dir / f"{curriculum_endpoint(5)}.json"

    summary = build_curriculum_from_files(
        coaching_path,
        output=output,
        generated_at="2026-06-30T00:00:00Z",
        pretty=True,
    )

    curriculum = json.loads(output.read_text(encoding="utf-8"))
    assert summary.objectives == 1
    assert summary.total_time_loss_s == pytest.approx(0.001)
    assert curriculum["generated_at"] == "2026-06-30T00:00:00Z"
    assert curriculum["session"]["session_key"] == "20260629005756"
    assert curriculum["objectives"][0]["intent"] == "improve_rotation_to_apex"


def test_build_curriculum_from_files_accepts_utf8_bom_json(tmp_path) -> None:
    coaching_path = tmp_path / f"{coaching_endpoint(5)}.json"
    session_path = tmp_path / f"{last_session_endpoint(5)}.json"
    output = tmp_path / f"{curriculum_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8-sig")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    summary = build_curriculum_from_files(coaching_path, output=output)

    assert summary.objectives == 1


def test_build_curriculum_from_files_rejects_symlinked_inputs(tmp_path) -> None:
    real_coaching = tmp_path / "real" / f"{coaching_endpoint(5)}.json"
    real_session = tmp_path / "real" / f"{last_session_endpoint(5)}.json"
    real_coaching.parent.mkdir()
    real_coaching.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    real_session.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    coaching_link = tmp_path / f"{coaching_endpoint(5)}.json"
    session_link = tmp_path / f"{last_session_endpoint(5)}.json"
    try:
        coaching_link.symlink_to(real_coaching)
        session_link.symlink_to(real_session)
    except OSError as exc:
        pytest.skip(f"symlink creation unsupported on this platform: {exc!r}")

    with pytest.raises(TTNormalizeError, match="coaching input must be a regular file"):
        build_curriculum_from_files(
            coaching_link,
            session_path=real_session,
            output=tmp_path / f"{curriculum_endpoint(5)}.json",
        )
    with pytest.raises(TTNormalizeError, match="last-session input must be a regular file"):
        build_curriculum_from_files(
            real_coaching,
            session_path=session_link,
            output=tmp_path / f"{curriculum_endpoint(5)}.json",
        )


def test_build_curriculum_from_files_refuses_overwrite_input(tmp_path) -> None:
    coaching_path = tmp_path / f"{coaching_endpoint(5)}.json"
    session_path = tmp_path / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="must not overwrite retained input"):
        build_curriculum_from_files(coaching_path, output=coaching_path, overwrite=True)


def test_build_curriculum_from_files_requires_session_payload(tmp_path) -> None:
    coaching_path = tmp_path / f"{coaching_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="no paired last-session payload"):
        build_curriculum_from_files(
            coaching_path, output=tmp_path / f"{curriculum_endpoint(5)}.json"
        )


def test_build_curriculum_from_files_rejects_unapproved_output_root(tmp_path) -> None:
    session_dir = tmp_path / "lake" / "assettoCorsa" / "car" / "track" / "sess-1"
    other_dir = tmp_path / "elsewhere"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="curriculum output must stay"):
        build_curriculum_from_files(
            coaching_path, output=other_dir / f"{curriculum_endpoint(5)}.json"
        )


def test_build_curriculum_from_files_rejects_custom_name_inside_tt_lake(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="must be named curriculum_lap"):
        build_curriculum_from_files(
            coaching_path, output=tmp_path / "journal" / "tt" / "custom.json"
        )


def test_build_curriculum_from_files_rejects_wrong_lap_name_inside_tt_lake(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="output lap must match"):
        build_curriculum_from_files(
            coaching_path, output=session_dir / f"{curriculum_endpoint(6)}.json"
        )


def test_build_curriculum_from_files_validates_lake_base_output_root(tmp_path) -> None:
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    coaching_path = input_dir / f"{coaching_endpoint(5)}.json"
    session_path = input_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    output_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"

    with pytest.raises(TTNormalizeError, match="must be named curriculum_lap"):
        build_curriculum_from_files(
            coaching_path,
            output=output_dir / "custom.json",
            output_base=tmp_path,
        )
    with pytest.raises(TTNormalizeError, match="output lap must match"):
        build_curriculum_from_files(
            coaching_path,
            output=output_dir / f"{curriculum_endpoint(6)}.json",
            output_base=tmp_path,
        )


def test_build_curriculum_from_files_rejects_different_session_inside_tt_lake(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    other_session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-2"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="must stay next to coaching_lap5.json"):
        build_curriculum_from_files(
            coaching_path, output=other_session_dir / f"{curriculum_endpoint(5)}.json"
        )


def test_discover_curriculum_payloads_filters_lake(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    assert discover_curriculum_payloads(lake_base=tmp_path, session_key="sess-1", lap=5) == (
        coaching_path,
        session_path,
    )
    with pytest.raises(TTNormalizeError, match="no retained coaching"):
        discover_curriculum_payloads(lake_base=tmp_path, session_key="sess-2", lap=5)


def test_discover_curriculum_payloads_pairs_window_when_base_missing(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    session_dir.mkdir(parents=True)
    raw = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = session_dir / f"{last_session_window_endpoint(5, raw)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(json.dumps(raw), encoding="utf-8")

    assert discover_curriculum_payloads(lake_base=tmp_path, session_key="sess-1", lap=5) == (
        coaching_path,
        session_path,
    )


def test_discover_curriculum_payloads_rejects_ambiguous_session_windows(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    session_dir.mkdir(parents=True)
    raw = json.loads(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"))
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    base_path = session_dir / f"{last_session_endpoint(5)}.json"
    window_path = session_dir / f"{last_session_window_endpoint(5, raw)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    base_path.write_text(json.dumps(raw), encoding="utf-8")
    raw["data"]["telemetry"]["telemetry"]["reference"][0]["dist"] = 0.444444
    window_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(TTNormalizeError, match="multiple paired last-session payloads"):
        discover_curriculum_payloads(lake_base=tmp_path, session_key="sess-1", lap=5)


def test_curriculum_cli_writes_from_explicit_input(tmp_path, capsys) -> None:
    coaching_path = tmp_path / f"{coaching_endpoint(5)}.json"
    session_path = tmp_path / f"{last_session_endpoint(5)}.json"
    output = tmp_path / "curriculum.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    rc = main(
        [
            "curriculum",
            "--coaching",
            str(coaching_path),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert output.exists()
    assert "TT harness curriculum" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["objectives"] == 1


def test_curriculum_cli_discover_lake_honors_session_override(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "20260629005756"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = tmp_path / "provided_last_session.json"
    output = session_dir / f"{curriculum_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    rc = main(
        [
            "curriculum",
            "--discover-lake",
            "--lake-base",
            str(tmp_path),
            "--session-key",
            "20260629005756",
            "--lap",
            "5",
            "--session",
            str(session_path),
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["objectives"] == 1


def test_curriculum_cli_discover_lake_rejects_session_override_mismatch(tmp_path) -> None:
    session_dir = tmp_path / "journal" / "tt" / "assettoCorsa" / "car" / "track" / "sess-1"
    session_dir.mkdir(parents=True)
    coaching_path = session_dir / f"{coaching_endpoint(5)}.json"
    session_path = tmp_path / "wrong_last_session.json"
    output = session_dir / f"{curriculum_endpoint(5)}.json"
    coaching_path.write_text(json.dumps(_curriculum_bundle()), encoding="utf-8")
    session_path.write_text(LAST_SESSION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(SystemExit):
        main(
            [
                "curriculum",
                "--discover-lake",
                "--lake-base",
                str(tmp_path),
                "--session-key",
                "sess-1",
                "--lap",
                "5",
                "--session",
                str(session_path),
                "--output",
                str(output),
            ]
        )


def test_curriculum_cli_requires_one_input_mode(tmp_path) -> None:
    with pytest.raises(SystemExit):
        main(["curriculum", "--output", str(tmp_path / "curriculum.json")])


def test_parser_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_arg_parser().parse_args([])


# --- regression tests for the PR-359 adversarial-review fixes ----------------------


def test_retain_sessions_idless_sessions_do_not_collide(tmp_path) -> None:
    # Two DISTINCT sessions both lacking a usable id must NOT collapse onto one lake path
    # (the old 'unknown_session' single bucket silently dropped the second + corrupted the index).
    s1 = {"car_id": "c", "track_id": "t", "game_id": "g", "bestLapTime": 1000}
    s2 = {"car_id": "c", "track_id": "t", "game_id": "g", "bestLapTime": 2000}
    summary = retain_sessions([s1, s2], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    assert summary.total == 2
    assert summary.retained_new == 2  # both retained — no silent drop
    root = tmp_path / "journal" / "tt"
    assert len(list(root.rglob("session.json"))) == 2  # two distinct raw files on disk
    file_index = json.loads((root / INDEX_FILENAME).read_text())
    assert file_index["file_count"] == 2
    # Distinct sha256 per session — the first file's hash is never mis-attributed to the second.
    assert len({f["sha256"] for f in file_index["files"]}) == 2


def test_retain_sessions_keeps_nan_session_and_whole_batch(tmp_path) -> None:
    good = {"id": "u#a", "car_id": "c", "track_id": "t", "game_id": "g"}
    nan_session = {
        "id": "u#b",
        "car_id": "c",
        "track_id": "t",
        "game_id": "g",
        "lap_attributes": {"fuelLevel": float("nan")},
    }
    after = {"id": "u#c", "car_id": "c", "track_id": "t", "game_id": "g"}
    summary = retain_sessions(
        [good, nan_session, after], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z"
    )
    # A non-finite telemetry float must NOT abort the batch or skip the indexes.
    assert summary.total == 3
    assert summary.failed == 0
    root = tmp_path / "journal" / "tt"
    assert (root / SESSIONS_INDEX_FILENAME).exists()
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 3


def test_retain_sessions_guards_unserializable_session(tmp_path) -> None:
    good = {"id": "u#a", "car_id": "c", "track_id": "t", "game_id": "g"}
    # A set is not JSON-serializable (even with allow_nan): the per-session write raises, but the
    # guard must keep the rest of the batch and still write both indexes.
    bad = {"id": "u#b", "car_id": "c", "track_id": "t", "game_id": "g", "weird": {1, 2, 3}}
    summary = retain_sessions([good, bad], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    assert summary.failed == 1
    assert summary.total == 1  # only the good session retained
    assert "1 session(s) skipped due to errors" in summary.render()
    root = tmp_path / "journal" / "tt"
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 1
    assert json.loads((root / SESSIONS_INDEX_FILENAME).read_text())["session_count"] == 1


def test_retain_sessions_partial_export_preserves_index(tmp_path) -> None:
    # A later partial export must NOT shrink the discovery index: the index is a derived
    # view of the WHOLE lake on disk, not of one batch (regression for index-rebuild bug).
    retain_sessions(_sessions(), lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    extra = {"id": "u#new", "car_id": "c", "track_id": "t", "game_id": "g"}
    summary = retain_sessions([extra], lake_base=tmp_path, generated_at="2026-06-29T00:00:00Z")
    assert summary.total == 1  # this batch processed one session...
    assert summary.indexed == 4  # ...but the index covers all 4 raw files on disk
    root = tmp_path / "journal" / "tt"
    assert json.loads((root / INDEX_FILENAME).read_text())["file_count"] == 4
    assert json.loads((root / SESSIONS_INDEX_FILENAME).read_text())["session_count"] == 4


def test_retain_sessions_raw_is_write_once_and_index_matches_disk(tmp_path) -> None:
    s = {"id": "u#a", "car_id": "c", "track_id": "t", "game_id": "g", "bestLapTime": 1000}
    retain_sessions([s], lake_base=tmp_path, generated_at="2026-06-28T00:00:00Z")
    root = tmp_path / "journal" / "tt"
    raw_path = next(root.rglob("session.json"))
    original = raw_path.read_text()
    # Re-export the SAME session id with DIFFERENT content: raw is write-once → unchanged,
    # and the rebuilt index reflects the retained (old) raw, never the new payload.
    summary = retain_sessions(
        [{**s, "bestLapTime": 9999}], lake_base=tmp_path, generated_at="2026-06-29T00:00:00Z"
    )
    assert summary.retained_new == 0
    assert raw_path.read_text() == original
    si = json.loads((root / SESSIONS_INDEX_FILENAME).read_text())
    assert si["sessions"][0]["best_lap_ms"] == 1000  # index agrees with disk, not the new payload
