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
    # Positively accounted for, so a mutation that dropped it from every list would still fail.
    assert "lap_odd.json" in {p.name for p in plan.protected_imported}


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
    assert referenced_names(state)[0] == {"lap_reference.json"}


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
    assert referenced_names(state)[0] == {"lap_cited_by_report.json"}


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

    assert referenced_names(state)[0] == set()
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

    assert referenced_names(state)[0] == set()


def test_an_unreadable_state_file_vetoes_the_whole_prune(tmp_path: Path) -> None:
    """An empty reference set authorises deletion, so failing to read one must not look empty.

    AC holding a state file open, a dehydrated OneDrive placeholder, or an antivirus lock would
    otherwise present as "this file protects nothing" and every archive it was the sole protector
    of would be deleted.
    """
    state, laps = _journal(tmp_path)
    for i in range(4):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i)
    # A directory named `*.json`: `read_bytes` raises OSError on every platform.
    (state / "unreadable.json").mkdir()

    plan = build_plan(laps, state, keep=1)

    assert plan.unreadable_state, "the unreadable state file must be reported"
    assert plan.prune == (), "nothing may be pruned while the reference scan is incomplete"


def test_unreadable_state_file_is_reported_and_exits_nonzero(tmp_path: Path, capsys) -> None:
    state, laps = _journal(tmp_path)
    for i in range(4):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i)
    (state / "unreadable.json").mkdir()

    code = main(["--state-dir", str(state), "--keep", "1", "--apply"])

    assert code == 4
    assert len(list(laps.glob("lap_*.json"))) == 4
    assert "REFUSING TO PRUNE" in capsys.readouterr().out


def test_a_missing_state_dir_does_not_read_as_nothing_protected(tmp_path: Path) -> None:
    names, unreadable = referenced_names(tmp_path / "absent")
    assert names == set()
    assert unreadable, "an absent state dir is unknown protection, not absent protection"


def test_reference_matching_is_case_insensitive(tmp_path: Path) -> None:
    """This runs on a case-insensitive filesystem; casing must not un-protect an archive."""
    state, laps = _journal(tmp_path)
    _write_archive(laps, "lap_Ref_ABC.json", age_s=10_000)
    for i in range(3):
        _write_archive(laps, f"lap_local_{i}.json", age_s=9_000 - i)
    (state / "combo.json").write_text(json.dumps({"ref": "lap_ref_abc.JSON"}), encoding="utf-8")

    assert "lap_Ref_ABC.json" not in {p.name for p in build_plan(laps, state, keep=1).prune}


def test_build_plan_survives_an_archive_vanishing_mid_run(tmp_path: Path, monkeypatch) -> None:
    """`lap_archive.rotate` deletes from this directory after every lap, so this is expected."""
    state, laps = _journal(tmp_path)
    for i in range(5):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i)

    real_glob = Path.glob

    def vanishing_glob(self, pattern, *args, **kwargs):
        results = list(real_glob(self, pattern, *args, **kwargs))
        if pattern == "lap_*.json":
            for hit in results:
                if hit.name == "lap_2.json":
                    hit.unlink()  # gone between the glob and the sort key
        return iter(results)

    monkeypatch.setattr(Path, "glob", vanishing_glob)

    plan = build_plan(laps, state, keep=1)  # must not raise FileNotFoundError

    assert plan.total == 5
    assert not (laps / "lap_2.json").exists()


def test_apply_rechecks_source_before_unlinking(tmp_path: Path) -> None:
    """A lap can be archived while this runs; the plan is a snapshot, the file is the truth."""
    state, laps = _journal(tmp_path)
    for i in range(4):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i)
    plan = build_plan(laps, state, keep=1)
    victim = plan.prune[0]
    # It became an imported reference after the plan was built.
    victim.write_text(
        json.dumps({"source": "imported", "lap": {"lap_ms": 1}}, separators=(",", ":")),
        encoding="utf-8",
    )

    removed, errors = apply_plan(plan)

    assert victim.exists(), "a file that stopped classifying as in_game must not be deleted"
    assert removed == len(plan.prune) - 1
    assert any("no longer classifies" in e for e in errors)


def test_apply_keep_zero_requires_an_explicit_yes(tmp_path: Path) -> None:
    """`--keep 0` disables the only protection that does not depend on parsing a file."""
    state, laps = _journal(tmp_path)
    for i in range(3):
        _write_archive(laps, f"lap_{i}.json", age_s=100 - i)

    assert main(["--state-dir", str(state), "--keep", "0", "--apply"]) == 2
    assert len(list(laps.glob("lap_*.json"))) == 3, "the refused run must delete nothing"
    assert main(["--state-dir", str(state), "--keep", "0", "--apply", "--yes"]) == 0
    assert list(laps.glob("lap_*.json")) == []


def test_partial_failure_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    """A wrapper script must be able to tell a partial prune from a clean one."""
    state, laps = _journal(tmp_path)
    for i in range(4):
        _write_archive(laps, f"lap_{i}.json", age_s=10_000 - i)

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name == "lap_1.json":
            raise PermissionError("locked by another process")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    assert main(["--state-dir", str(state), "--keep", "1", "--apply"]) == 3
    assert (laps / "lap_1.json").exists()


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
