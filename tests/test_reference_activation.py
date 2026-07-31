"""Imported reference-lap activation tests for issue #79."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"


def _to_lua(lua: Any, value: Any) -> Any:
    if isinstance(value, dict):
        tbl = lua.table()
        for k, v in value.items():
            tbl[k] = _to_lua(lua, v)
        return tbl
    if isinstance(value, list):
        tbl = lua.table()
        for i, v in enumerate(value, start=1):
            tbl[i] = _to_lua(lua, v)
        return tbl
    return value


def _runtime(tmp_path: Path, files: list[str]):
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    root = str(tmp_path).replace("\\", "/")
    quoted_files = ", ".join(repr(name) for name in files)
    rt.execute(
        f"""
        ac = {{
          FolderID = {{ ScriptConfig = 2 }},
          getFolder = function(_) return {root!r} end,
          getTrackLayout = function() return "" end,
        }}
        io.scanDir = function(_, _) return {{ {quoted_files} }} end
        package.path = package.path .. ";{modules_path}/?.lua"
        """
    )

    def json_parse(raw: str) -> Any:
        return _to_lua(rt, json.loads(str(raw)))

    rt.globals()["JSON"] = rt.table_from({"parse": json_parse})
    return rt


def _record(
    lap_ms: int, *, car: str = "car_a", track: str = "track_a", valid: bool = True
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "imported",
        "import_format": "motec_csv",
        "car": {"id": car},
        "track": {"id": track, "layout": None},
        "lap": {"lap_ms": lap_ms, "is_valid": valid},
        "trace": {
            "fields": [
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
            ],
            "samples": [
                [0.0, 100, 0, 1, 0, 0, 2, 0, 0, 0],
                [0.5, 120, lap_ms / 2, 1, 0.5, 0.1, 3, 0, 0, 0],
                [0.99, 140, lap_ms, 1, 0, 0, 4, 0, 0, 0],
            ],
        },
    }


def test_best_imported_reference_scans_fastest_matching_car_track(tmp_path: Path) -> None:
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    (laps / "lap_imported_slow.json").write_text(json.dumps(_record(100_000)), encoding="utf-8")
    (laps / "lap_imported_fast.json").write_text(json.dumps(_record(90_000)), encoding="utf-8")
    (laps / "lap_imported_wrong_track.json").write_text(
        json.dumps(_record(80_000, track="other_track")),
        encoding="utf-8",
    )
    (laps / "lap_imported_invalid.json").write_text(
        json.dumps(_record(70_000, valid=False)),
        encoding="utf-8",
    )

    rt = _runtime(
        tmp_path,
        [
            "lap_imported_slow.json",
            "lap_imported_fast.json",
            "lap_imported_wrong_track.json",
            "lap_imported_invalid.json",
        ],
    )
    ref = rt.execute(
        """
        local p = require("persistence")
        return p.bestImportedReference({ id = "car_a" }, { trackName = "track_a" })
        """
    )

    assert ref["lapMs"] == 90_000
    assert len(ref["trace"]) == 3
    assert ref["source"] == "imported"


def test_choose_imported_reference_requires_flag_and_faster_lap(tmp_path: Path) -> None:
    rt = _runtime(tmp_path, [])
    result = rt.execute(
        """
        local p = require("persistence")
        local imported = { lapMs = 90000 }
        return {
          disabled = p.chooseImportedReference(100000, imported, false) ~= nil,
          faster = p.chooseImportedReference(100000, imported, true).lapMs,
          noLocal = p.chooseImportedReference(nil, imported, true).lapMs,
          slower = p.chooseImportedReference(80000, imported, true) ~= nil,
        }
        """
    )

    assert result["disabled"] is False
    assert result["faster"] == 90_000
    assert result["noLocal"] == 90_000
    assert result["slower"] is False


def test_settings_ui_exposes_reference_lap_controls() -> None:
    src = (MODULES_DIR / "hud_settings.lua").read_text(encoding="utf-8")

    assert "Reference lap" in src
    assert "useImportedReference" in src
    assert "Prefer imported reference over local PB" in src
    assert "Open reference laps folder" in src


# ---------------------------------------------------------------------------
# #627: the tail prefilter that stops the whole-journal parse
# ---------------------------------------------------------------------------


def _counting_runtime(tmp_path: Path, files: list[str]):
    """A runtime whose ``JSON.parse`` counts calls, so "did it FULLY parse?" is observable."""
    rt = _runtime(tmp_path, files)
    calls = {"n": 0}

    def counting_parse(raw: str) -> Any:
        calls["n"] += 1
        return _to_lua(rt, json.loads(str(raw)))

    rt.globals()["JSON"] = rt.table_from({"parse": counting_parse})
    return rt, calls


def test_non_imported_archive_is_excluded_without_a_full_parse(tmp_path: Path) -> None:
    """#627: the 250 KB parse must not happen for archives the tail proves are not imported.

    This is the whole point: on the rig, 401 archives / 480.5 MB were parsed on every reference
    refresh and ZERO were imported.
    """
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    local_lap = _record(95_000)
    local_lap["source"] = "in_game"
    (laps / "lap_local.json").write_text(json.dumps(local_lap), encoding="utf-8")

    rt, calls = _counting_runtime(tmp_path, ["lap_local.json"])
    ref = rt.execute(
        """
        local p = require("persistence")
        return p.bestImportedReference({ id = "car_a" }, { trackName = "track_a" })
        """
    )

    assert ref is None
    assert calls["n"] == 0, "an in_game archive was fully JSON-parsed; the prefilter did not fire"


def test_prefilter_is_independent_of_json_key_order(tmp_path: Path) -> None:
    """The encoder emits keys in hash order, so position must not matter.

    A tail-only window was tried first and REJECTED by measurement: on the rig ``"source"`` sat a
    median of 247 KB from EOF, and 58 of 80 sampled archives had it outside an 8 KiB tail. This
    pins the whole-buffer scan so that regression cannot come back.
    """
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    rec = _record(90_000)
    raw = json.dumps(rec)
    # Force "source" to the very front, then pad far past any plausible tail window.
    assert raw.index('"source"') < 200
    padded = raw[:-1] + ',"zz_pad":"' + ("x" * 400_000) + '"}'
    # Past the measured median distance-from-EOF (247 KB), so reintroducing a tail window of any
    # plausible size — 8 KiB, 64 KiB, 256 KiB — fails this test rather than sneaking through.
    assert padded.index('"source"') < len(padded) - 262_144
    (laps / "lap_front_source.json").write_text(padded, encoding="utf-8")

    rt, calls = _counting_runtime(tmp_path, ["lap_front_source.json"])
    ref = rt.execute(
        """
        local p = require("persistence")
        return p.bestImportedReference({ id = "car_a" }, { trackName = "track_a" })
        """
    )

    assert calls["n"] == 1, "an imported archive must still be decoded whatever the key order"
    assert ref is not None and ref["lapMs"] == 90_000


def test_prefilter_fails_open_on_an_unreadable_file(tmp_path: Path) -> None:
    """A missing/unopenable archive must not be reported as "definitely not imported"."""
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        """
        local p = require("persistence")
        return p._archiveMayBeImported("does_not_exist_anywhere.json")
        """
    )
    assert verdict is True


def test_prefilter_handles_a_differently_spaced_encoder(tmp_path: Path) -> None:
    """`"source": "in_game"` (spaced) is still PROOF of non-imported, so it must be excluded.

    Our encoder emits the compact form, so this path never runs for archives this app wrote — but
    a hand-edited or externally-produced file should not force a full decode either.
    """
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    path = laps / "lap_spaced.json"
    path.write_text('{"source": "in_game", "lap": {"lap_ms": 1}}', encoding="utf-8")
    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        f"""
        local p = require("persistence")
        return p._archiveMayBeImported({str(path).replace(chr(92), "/")!r})
        """
    )
    assert verdict is False


def test_prefilter_spaced_path_scans_every_match_not_just_the_first(tmp_path: Path) -> None:
    """A nested `source` key must not shadow a later top-level `"source": "imported"`.

    The compact fast path is a whole-buffer OR. The tolerant path has to be one too: taking only
    the first match reports a genuinely imported archive as PROVEN not-imported and silently drops
    the user's lap. That is the one direction this filter is never allowed to be wrong in.
    """
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    path = laps / "lap_nested_source.json"
    # Pretty-printed (spaced), with a nested `source` ahead of the real one.
    path.write_text(
        json.dumps({"meta": {"source": "motec_export"}, "source": "imported"}, indent=2),
        encoding="utf-8",
    )
    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        f"""
        local p = require("persistence")
        return p._archiveMayBeImported({str(path).replace(chr(92), "/")!r})
        """
    )
    assert verdict is True


def test_prefilter_fails_open_on_a_json_escaped_source_value(tmp_path: Path) -> None:
    """`"source":"impor\\u0074ed"` decodes to "imported" but matches none of our byte literals.

    Comparing raw bytes to a decoded string is only valid while nothing is escaped. Reporting
    "proven not imported" here would silently disable a user-supplied reference — the one
    direction this filter is never allowed to be wrong in.
    """
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    path = laps / "lap_escaped.json"
    backslash = chr(92)
    raw = '{"source":"impor' + backslash + 'u0074ed","lap":{"lap_ms":1}}'
    assert json.loads(raw)["source"] == "imported", "fixture must really decode to imported"
    path.write_text(raw, encoding="utf-8")

    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        f"""
        local p = require("persistence")
        return p._archiveMayBeImported({str(path).replace(chr(92), "/")!r})
        """
    )
    assert verdict is True


def test_prefilter_still_excludes_an_ordinary_escaped_free_archive(tmp_path: Path) -> None:
    """The escape guard must not turn the fast path off for the files it exists to exclude."""
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    path = laps / "lap_plain.json"
    path.write_text('{"source":"in_game","lap":{"lap_ms":1}}', encoding="utf-8")

    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        f"""
        local p = require("persistence")
        return p._archiveMayBeImported({str(path).replace(chr(92), "/")!r})
        """
    )
    assert verdict is False


def test_prefilter_fails_open_when_the_read_itself_fails(tmp_path: Path) -> None:
    """Opening succeeds but reading throws — distinct from the file simply not existing."""
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    path = laps / "lap_read_explodes.json"
    path.write_text('{"source":"in_game"}', encoding="utf-8")
    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        f"""
        local p = require("persistence")
        local realOpen = io.open
        io.open = function(...)
          local f = realOpen(...)
          if f == nil then return nil end
          return {{
            read = function() error("simulated I/O failure") end,
            close = function() return f:close() end,
          }}
        end
        local v = p._archiveMayBeImported({str(path).replace(chr(92), "/")!r})
        io.open = realOpen
        return v
        """
    )
    assert verdict is True, "a failed read must fall back to decoding, not to 'not imported'"


def test_prefilter_fails_open_when_there_is_no_source_key_at_all(tmp_path: Path) -> None:
    """No recognised key => unknown shape => decode it. A `false` verdict must always be proof."""
    laps = tmp_path / "ac_copilot_trainer" / "journal" / "laps"
    laps.mkdir(parents=True)
    path = laps / "lap_no_source.json"
    path.write_text('{"lap": {"lap_ms": 1}}', encoding="utf-8")
    rt = _runtime(tmp_path, [])
    verdict = rt.execute(
        f"""
        local p = require("persistence")
        return p._archiveMayBeImported({str(path).replace(chr(92), "/")!r})
        """
    )
    assert verdict is True
