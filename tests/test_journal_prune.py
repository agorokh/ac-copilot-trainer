"""Retention tests for the lap-archive journal (#627).

The bar here is not "does it delete" — it is **does it refuse to delete the wrong thing**. These
are the operator's own telemetry files, so every protection gets its own failing-if-broken test.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tools.journal_prune import (
    DEFAULT_KEEP,
    apply_plan,
    archive_source,
    build_plan,
    main,
    referenced_names,
)


def _write_archive(laps: Path, name: str, *, source: str = "in_game", age_s: float = 0.0) -> Path:
    path = laps / name
    # Compact separators: this is what the Lua encoder emits, and what the plain scan keys on.
    path.write_text(
        json.dumps({"source": source, "lap": {"lap_ms": 90_000}}, separators=(",", ":")),
        encoding="utf-8",
    )
    if age_s:
        old = time.time() - age_s
        os.utime(path, (old, old))
    return path


def _journal(tmp_path: Path) -> tuple[Path, Path]:
    state = tmp_path / "ac_copilot_trainer"
    laps = state / "journal" / "laps"
    laps.mkdir(parents=True)
    return state, laps


def test_archive_source_reads_without_decoding(tmp_path: Path) -> None:
    state, laps = _journal(tmp_path)
    assert archive_source(_write_archive(laps, "lap_a.json")) == "in_game"
    assert archive_source(_write_archive(laps, "lap_b.json", source="imported")) == "imported"


def test_archive_source_is_none_when_undetermined(tmp_path: Path) -> None:
    """Undetermined must be distinguishable from 'in_game' — callers protect on ``None``."""
    state, laps = _journal(tmp_path)
    odd = laps / "lap_odd.json"
    odd.write_text('{"lap":{"lap_ms":1}}', encoding="utf-8")
    assert archive_source(odd) is None
    assert archive_source(laps / "does_not_exist.json") is None


def test_imported_archives_are_never_pruned(tmp_path: Path) -> None:
    """Imported laps are user data that driving cannot regenerate."""
    state, laps = _journal(tmp_path)
    _write_archive(laps, "lap_imported.json", source="imported", age_s=10_000)
    for i in range(5):
        _write_archive(laps, f"lap_local_{i}.json", age_s=9_000 - i)

    plan = build_plan(laps, state, keep=1)

    names = {p.name for p in plan.prune}
    assert "lap_imported.json" not in names
    assert {p.name for p in plan.protected_imported} == {"lap_imported.json"}


def test_undetermined_source_is_protected_not_pruned(tmp_path: Path) -> None:
    """A file we cannot classify must be kept. `None` is not permission to delete."""
    state, laps = _journal(tmp_path)
    odd = laps / "lap_odd.json"
    odd.write_text('{"lap":{"lap_ms":1}}', encoding="utf-8")
    os.utime(odd, (time.time() - 10_000,) * 2)
    for i in range(3):
        _write_archive(laps, f"lap_local_{i}.json", age_s=9_000 - i)

    plan = build_plan(laps, state, keep=1)

    assert "lap_odd.json" not in {p.name for p in plan.prune}


def test_archives_referenced_by_state_are_never_pruned(tmp_path: Path) -> None:
    """Deleting the file backing the active reference would silently break coaching."""
    state, laps = _journal(tmp_path)
    kept = _write_archive(laps, "lap_reference.json", age_s=10_000)
    for i in range(4):
        _write_archive(laps, f"lap_local_{i}.json", age_s=9_000 - i)
    (state / "bmw_m3_gt2__magione.json").write_text(
        json.dumps({"bestLapArchivePath": f"journal/laps/{kept.name}"}),
        encoding="utf-8",
    )

    plan = build_plan(laps, state, keep=1)

    assert "lap_reference.json" not in {p.name for p in plan.prune}
    assert {p.name for p in plan.protected_referenced} == {"lap_reference.json"}
    assert referenced_names(state) == {"lap_reference.json"}


def test_newest_are_always_kept(tmp_path: Path) -> None:
    state, laps = _journal(tmp_path)
    for i in range(10):
        _write_archive(laps, f"lap_{i:02d}.json", age_s=10_000 - i * 100)

    plan = build_plan(laps, state, keep=4)

    assert len(plan.prune) == 6
    assert {p.name for p in plan.prune} == {f"lap_{i:02d}.json" for i in range(6)}


def test_keep_larger_than_journal_prunes_nothing(tmp_path: Path) -> None:
    state, laps = _journal(tmp_path)
    for i in range(3):
        _write_archive(laps, f"lap_{i}.json", age_s=100 - i)

    assert build_plan(laps, state, keep=DEFAULT_KEEP).prune == ()


def test_dry_run_is_the_default_and_deletes_nothing(tmp_path: Path, capsys) -> None:
    state, laps = _journal(tmp_path)
    for i in range(8):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i * 10)

    code = main(["--state-dir", str(state), "--keep", "2"])

    assert code == 0
    assert len(list(laps.glob("lap_*.json"))) == 8, "a dry run must not delete anything"
    out = capsys.readouterr().out
    assert "would remove" in out
    assert "--apply" in out


def test_apply_deletes_only_the_planned_files(tmp_path: Path, capsys) -> None:
    state, laps = _journal(tmp_path)
    _write_archive(laps, "lap_imported.json", source="imported", age_s=10_000)
    for i in range(8):
        _write_archive(laps, f"lap_{i}.json", age_s=9_000 - i * 10)

    plan = build_plan(laps, state, keep=2)
    planned = {p.name for p in plan.prune}
    code = main(["--state-dir", str(state), "--keep", "2", "--apply"])

    assert code == 0
    survivors = {p.name for p in laps.glob("lap_*.json")}
    assert planned and planned.isdisjoint(survivors)
    assert "lap_imported.json" in survivors
    assert "removed" in capsys.readouterr().out


def test_apply_reports_errors_without_raising(tmp_path: Path) -> None:
    """One unremovable file must not abort the whole prune."""
    state, laps = _journal(tmp_path)
    for i in range(4):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i)
    plan = build_plan(laps, state, keep=1)
    for path in plan.prune:
        path.unlink()  # vanish before apply: simulates a concurrent delete

    removed, errors = apply_plan(plan)

    assert removed == 0
    assert len(errors) == len(plan.prune)


def test_missing_journal_is_reported_not_crashed(tmp_path: Path) -> None:
    assert main(["--state-dir", str(tmp_path / "nope")]) == 1
