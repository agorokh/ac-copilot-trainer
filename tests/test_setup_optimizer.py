"""Setup experiment tracking and next-setup suggestions (issue #114)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.ai_sidecar.server import (
    _run_setup_compare,
    _run_setup_rebuild,
    _run_setup_suggest,
)
from tools.ai_sidecar.setup_optimizer import (
    SetupExperimentError,
    _candidate_grid,
    compare_setups,
    load_records,
    rebuild_experiments,
    record_from_lap_archive,
    record_lap_archive,
    suggest_next_setup,
)


def _lap(
    *,
    lap_uuid: str,
    setup_hash: str,
    setup_name: str,
    lap_ms: int,
    front_bias: int,
    rear_wing: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": lap_uuid,
        "session_uuid": "sess-1",
        "exported_at": f"2026-06-16T00:00:{int(lap_uuid[-1]):02d}Z",
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "layout": None, "lengthM": 2525},
        "conditions": {"trackGripLevel": 0.97, "ambientTempC": 22},
        "lap": {"lap_n": int(lap_uuid[-1]), "lap_ms": lap_ms, "is_valid": True},
        "setup": {
            "hash": setup_hash,
            "path": f"C:/Users/arsen/Documents/Assetto Corsa/setups/car/magione/{setup_name}.ini",
            "snapshot": {
                "FRONT_BIAS.VALUE": str(front_bias),
                "WING_2.VALUE": str(rear_wing),
                "ABS.VALUE": "7",
            },
        },
    }


def _write_laps(lap_dir: Path) -> list[Path]:
    lap_dir.mkdir(parents=True)
    specs = [
        ("lap-a1", "old", "baseline", 100_000, 64, 8),
        ("lap-a2", "old", "baseline", 101_000, 64, 8),
        ("lap-a3", "old", "baseline", 99_000, 64, 8),
        ("lap-b4", "new", "candidate", 98_000, 66, 9),
        ("lap-b5", "new", "candidate", 97_500, 66, 9),
        ("lap-b6", "new", "candidate", 98_200, 66, 9),
        ("lap-c7", "wing10", "wing10", 99_300, 66, 10),
    ]
    paths = []
    for i, spec in enumerate(specs, start=1):
        path = lap_dir / f"lap_20260616-00000{i}_{spec[0]}.json"
        path.write_text(
            json.dumps(
                _lap(
                    *(),
                    **dict(
                        zip(
                            (
                                "lap_uuid",
                                "setup_hash",
                                "setup_name",
                                "lap_ms",
                                "front_bias",
                                "rear_wing",
                            ),
                            spec,
                            strict=True,
                        )
                    ),
                )
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def test_record_from_lap_archive_extracts_setup_params() -> None:
    rec = record_from_lap_archive(
        _lap(
            lap_uuid="lap-a1",
            setup_hash="old",
            setup_name="baseline",
            lap_ms=100_000,
            front_bias=64,
            rear_wing=8,
        ),
        source_path="C:/journal/laps/lap_1.json",
    )
    assert rec["experiment_id"] == "lap-a1"
    assert rec["lap"]["lap_ms"] == 100_000
    assert rec["setup"]["hash"] == "old"
    assert rec["setup"]["name"] == "baseline"
    assert rec["setup"]["params"]["FRONT_BIAS.VALUE"] == 64.0
    assert rec["conditions"]["trackGripLevel"] == 0.97


def test_rebuild_compare_and_suggest(tmp_path: Path) -> None:
    lap_dir = tmp_path / "journal" / "laps"
    _write_laps(lap_dir)

    summary = rebuild_experiments(lap_dir)
    assert summary["records"] == 7
    store = Path(summary["store_path"])
    records = load_records(store)
    assert len(records) == 7

    comparison = compare_setups(records, baseline_setup="old", candidate_setup="new")
    assert comparison["ok"] is True
    assert comparison["improvement_ms"] > 1500
    assert comparison["confidence"] > 0.95
    assert comparison["significant"] is True

    suggestion = suggest_next_setup(records, car_id="ks_porsche_911_gt3_r_2016", track_id="magione")
    assert suggestion["ok"] is True
    assert suggestion["method"] == "rbf_surrogate_expected_improvement"
    assert suggestion["candidate"]["changed_params"]
    assert suggestion["surrogate"]["expected_improvement_ms"] >= 0
    assert suggestion["rationale"]


def test_candidate_grid_clamps_nonnegative_params() -> None:
    records = [
        record_from_lap_archive(
            _lap(
                lap_uuid="lap-a1",
                setup_hash="best",
                setup_name="best",
                lap_ms=98_000,
                front_bias=0,
                rear_wing=8,
            )
        ),
        record_from_lap_archive(
            _lap(
                lap_uuid="lap-b2",
                setup_hash="slower",
                setup_name="slower",
                lap_ms=99_000,
                front_bias=1,
                rear_wing=8,
            )
        ),
    ]
    best = min(records, key=lambda rec: rec["lap"]["lap_ms"])

    grid = _candidate_grid(records, best, ["FRONT_BIAS.VALUE"])

    assert grid
    assert all(candidate["FRONT_BIAS.VALUE"] >= 0 for candidate in grid)


def test_record_lap_archive_upserts_without_duplicates(tmp_path: Path) -> None:
    lap_dir = tmp_path / "journal" / "laps"
    path = _write_laps(lap_dir)[0]
    store = tmp_path / "experiments.jsonl"

    first = record_lap_archive(path, store_path=store)
    second = record_lap_archive(path, store_path=store)

    assert first["inserted"] == 1
    assert second["updated"] == 1
    assert len(load_records(store)) == 1


def test_load_records_rejects_corrupt_store(tmp_path: Path) -> None:
    store = tmp_path / "experiments.jsonl"
    store.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")

    with pytest.raises(SetupExperimentError, match=r"experiments\.jsonl:2"):
        load_records(store)


def test_rebuild_experiments_deduplicates_experiment_ids(tmp_path: Path) -> None:
    lap_dir = tmp_path / "journal" / "laps"
    lap_dir.mkdir(parents=True)
    (lap_dir / "lap_20260616-000001_first.json").write_text(
        json.dumps(
            _lap(
                lap_uuid="lap-d1",
                setup_hash="old",
                setup_name="baseline",
                lap_ms=100_000,
                front_bias=64,
                rear_wing=8,
            )
        ),
        encoding="utf-8",
    )
    (lap_dir / "lap_20260616-000002_second.json").write_text(
        json.dumps(
            _lap(
                lap_uuid="lap-d1",
                setup_hash="new",
                setup_name="candidate",
                lap_ms=98_000,
                front_bias=66,
                rear_wing=9,
            )
        ),
        encoding="utf-8",
    )

    summary = rebuild_experiments(lap_dir)
    records = load_records(summary["store_path"])

    assert summary["records"] == 1
    assert summary["duplicates"] == [
        {"path": str(lap_dir / "lap_20260616-000002_second.json"), "experiment_id": "lap-d1"}
    ]
    assert len(records) == 1
    assert records[0]["setup"]["hash"] == "new"


def test_setup_optimizer_cli_smoke(tmp_path: Path, capsys) -> None:
    lap_dir = tmp_path / "journal" / "laps"
    _write_laps(lap_dir)
    store = tmp_path / "store.jsonl"

    _run_setup_rebuild(str(lap_dir), str(store))
    rebuild_out = json.loads(capsys.readouterr().out)
    assert rebuild_out["records"] == 7

    _run_setup_compare(str(store), "old", "new")
    compare_out = json.loads(capsys.readouterr().out)
    assert compare_out["significant"] is True

    _run_setup_suggest(str(store), "ks_porsche_911_gt3_r_2016", "magione")
    suggest_out = json.loads(capsys.readouterr().out)
    assert suggest_out["ok"] is True
    assert suggest_out["candidate"]["changed_params"]
