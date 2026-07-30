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


def _write_archive(
    laps: Path,
    name: str,
    *,
    source: str = "in_game",
    age_s: float = 0.0,
    pad_bytes: int = 0,
) -> Path:
    path = laps / name
    payload: dict[str, object] = {"source": source, "lap": {"lap_ms": 90_000}}
    if pad_bytes:
        # Stand in for the trace array. Real archives are ~250 KB; tests that assert on reported
        # sizes need enough bytes that MB rounding can tell "reclaimed" from "reclaimed nothing".
        payload["trace"] = "x" * pad_bytes
    # Compact separators: this is what the Lua encoder emits, and what the plain scan keys on.
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
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


def test_archives_referenced_by_a_nested_report_are_never_pruned(tmp_path: Path) -> None:
    """Regression: the rig's ``journal/reports/*.json`` names 187 archives.

    A top-level-only scan of the state directory left every one of them unprotected. Anything
    that can name an archive, at any depth, must protect it.
    """
    state, laps = _journal(tmp_path)
    kept = _write_archive(laps, "lap_cited_by_report.json", age_s=10_000)
    for i in range(4):
        _write_archive(laps, f"lap_local_{i}.json", age_s=9_000 - i)
    reports = state / "journal" / "reports"
    reports.mkdir(parents=True)
    (reports / "session_abc_car_track.json").write_text(
        json.dumps({"laps": [{"archive": kept.name}]}),
        encoding="utf-8",
    )

    plan = build_plan(laps, state, keep=1)

    assert "lap_cited_by_report.json" not in {p.name for p in plan.prune}
    assert referenced_names(state) == {"lap_cited_by_report.json"}


def test_archives_do_not_protect_each_other(tmp_path: Path) -> None:
    """The ``journal/laps`` tree is excluded from the reference scan.

    Otherwise an archive naming its predecessor would keep the whole chain alive forever — and
    reading 480 MB of archives here would re-introduce the cost this work exists to remove.
    """
    state, laps = _journal(tmp_path)
    old = _write_archive(laps, "lap_old.json", age_s=10_000)
    citing = laps / "lap_citing.json"
    citing.write_text(
        json.dumps({"source": "in_game", "previous": old.name}, separators=(",", ":")),
        encoding="utf-8",
    )
    os.utime(citing, (time.time() - 9_000,) * 2)
    _write_archive(laps, "lap_newest.json", age_s=1)

    assert referenced_names(state) == set()
    assert "lap_old.json" in {p.name for p in build_plan(laps, state, keep=1).prune}


def test_reference_scan_ignores_lap_shaped_keys(tmp_path: Path) -> None:
    """``lap_history`` / ``lap_ms`` appear in every session file and are not filenames."""
    state, laps = _journal(tmp_path)
    _write_archive(laps, "lap_a.json", age_s=10_000)
    (state / "journal").mkdir(parents=True, exist_ok=True)
    (state / "journal" / "session_x.json").write_text(
        json.dumps({"lap_history": [{"lap_ms": 90_000}]}),
        encoding="utf-8",
    )

    assert referenced_names(state) == set()


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


def test_apply_reports_the_bytes_it_actually_reclaimed(tmp_path: Path, capsys) -> None:
    """The report is rendered after the unlink, so the size must be measured before it.

    Re-stat'ing a deleted file yields 0, which would have made every ``--apply`` run claim it
    reclaimed 0.0 MB — an operator reading that would reasonably conclude nothing happened.
    """
    state, laps = _journal(tmp_path)
    for i in range(8):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i * 10, pad_bytes=250_000)
    expected = build_plan(laps, state, keep=2).reclaimed_bytes
    assert expected > 1_000_000

    main(["--state-dir", str(state), "--keep", "2", "--apply"])

    out = capsys.readouterr().out
    assert "0.0 MB" not in out.split("removed")[1]
    assert f"{expected / 1_000_000:.1f} MB" in out


def test_keep_zero_is_honoured_and_negative_keep_is_rejected(tmp_path: Path) -> None:
    """``--keep 0`` must not be silently read as "unset" and fall back to the default."""
    state, laps = _journal(tmp_path)
    for i in range(3):
        _write_archive(laps, f"lap_{i}.json", age_s=100 - i)

    assert len(build_plan(laps, state, keep=0).prune) == 3
    # Rejected before the journal is even looked at.
    assert main(["--state-dir", str(tmp_path / "nope"), "--keep", "-1"]) == 2


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
