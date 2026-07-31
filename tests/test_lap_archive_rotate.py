"""`lap_archive.rotate` must never size-evict an imported reference (#627).

`rotate` runs after every completed lap and deletes oldest-first until the archive directory is
under its size cap. It sorts by filename and deletes until the number goes down — no notion of
what a file *is*.

Imported references are user-supplied data that driving cannot regenerate. Before this fix they
survived only by accident: the sort is alphabetical and `lap_<YYYYMMDD…>` orders before
`lap_imported_…` because digits precede `i`. That is not a guarantee. It fails if the in-game
naming ever changes, and it fails today the moment every in-game archive has already been evicted
and the directory is still over cap.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"

#: `rotate` clamps its cap to a 50 MB floor (`ARCHIVE_CAP_MIN_MB`), so fixtures must "weigh" more
#: than that to trigger eviction at all. Reported via a stubbed `io.fileSize` rather than by
#: writing hundreds of megabytes: `rotate` only ever consults that API for sizes.
_REPORTED_SIZE_MB = 100


def _runtime(tmp_path: pathlib.Path) -> Any:
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    script_config = str(tmp_path).replace("\\", "/")
    rt.globals()["_script_config"] = script_config
    rt.execute(
        f"""
        package.path = package.path .. ";{modules_path}/?.lua"
        ac = {{
          FolderID = {{ ScriptConfig = 1 }},
          getFolder = function(_) return _script_config end,
          log = function(_) end,
        }}
        """
    )
    return rt


def _laps_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True, exist_ok=True)
    return laps


def _wire_scandir(rt: Any, laps: pathlib.Path) -> None:
    """Provide the CSP `io.scanDir` / `io.fileSize` APIs `rotate` depends on."""

    def scan_dir(_dir: str, _mask: str) -> Any:
        return rt.table_from(sorted(p.name for p in laps.glob("lap_*.json")))

    def file_size(path: str) -> int:
        if not pathlib.Path(str(path)).exists():
            return -1
        return _REPORTED_SIZE_MB * 1024 * 1024

    rt.globals()["_py_scan_dir"] = scan_dir
    rt.globals()["_py_file_size"] = file_size
    # Wrapped in Lua closures on purpose: lupa exposes a Python callable as `userdata`, and
    # `rotate` gates on `type(io.scanDir) == "function"` before using it at all.
    rt.execute(
        """
        io.scanDir = function(dir, mask) return _py_scan_dir(dir, mask) end
        io.fileSize = function(path) return _py_file_size(path) end
        """
    )


def _write(laps: pathlib.Path, name: str) -> pathlib.Path:
    path = laps / name
    path.write_text('{"source":"in_game"}', encoding="utf-8")
    return path


def test_rotate_never_evicts_an_imported_reference(tmp_path: pathlib.Path) -> None:
    """Rotate must stop at the imported archive even when that leaves it over cap."""
    laps = _laps_dir(tmp_path)
    for i in range(6):
        _write(laps, f"lap_2026070{i}-120000_sess_1_90000_key.json")
    _write(laps, "lap_imported_20260101-000000_sess_motec_88000_key.json")

    rt = _runtime(tmp_path)
    _wire_scandir(rt, laps)
    rt.execute('local a = require("lap_archive"); a.rotate(30)')

    survivors = {p.name for p in laps.glob("lap_*.json")}
    # 700 MB against a 50 MB floor: rotate must exhaust every in-game archive and still be over
    # cap, so it reaches the imported one. Without the guard it deletes it. This is what makes the
    # test non-vacuous -- `lap_imported_*` sorts last, so a smaller overage would spare it by
    # accident and prove nothing.
    assert survivors == {"lap_imported_20260101-000000_sess_motec_88000_key.json"}


def test_rotate_leaves_the_cap_exceeded_rather_than_evicting_imports(
    tmp_path: pathlib.Path,
) -> None:
    """The pathological case the old alphabetical accident could not survive.

    Every archive is imported and the directory is far over cap. Deleting to reach the cap would
    mean destroying user data; exceeding the cap is the correct outcome.
    """
    laps = _laps_dir(tmp_path)
    for i in range(6):
        _write(laps, f"lap_imported_2026010{i}-000000_sess_motec_88000_key.json")

    rt = _runtime(tmp_path)
    _wire_scandir(rt, laps)
    rt.execute('local a = require("lap_archive"); a.rotate(30)')

    assert len(list(laps.glob("lap_*.json"))) == 6


def test_imported_archive_name_detection() -> None:
    rt = _runtime(pathlib.Path("."))
    result = rt.execute(
        """
        local a = require("lap_archive")
        return {
          imported = a._isImportedArchiveName("lap_imported_20260101-000000_s_motec_1_k.json"),
          inGame = a._isImportedArchiveName("lap_20260101-000000_s_1_1_k.json"),
          nonString = a._isImportedArchiveName(nil),
        }
        """
    )
    assert result["imported"] is True
    assert result["inGame"] is False
    assert result["nonString"] is False
