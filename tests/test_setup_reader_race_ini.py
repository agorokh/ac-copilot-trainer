"""setup_reader.lua resolves the APPLIED setup from ``cfg/race.ini`` (#461).

When CSP does not expose ``car.setupFilename`` (most builds), and for a setup the #461 autonomous
harness bakes into ``race.ini`` before spawn, the trainer used to archive an EMPTY setup snapshot
pointing at a non-existent ``setups/<car>/<track>/race.ini``. The reader now consults
``[CAR_0] _EXT_SETUP_FILENAME`` (AC/CM's own key for the selected setup), so the per-lap archive
records which setup was actually driven — the #461 acceptance ("lap archive's setup snapshot matches
the requested setup").
"""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"


def _runtime(doc_root: str):
    """A lupa runtime: ``ac.getFolder(Documents)`` pinned to ``doc_root``, modules path set."""
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(
        "ac = { log = function() end, "
        f'getFolder = function(id) return "{doc_root}" end, '
        "FolderID = { Documents = 1, Root = 0 } }"
    )
    modules_path = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{modules_path}/?.lua"')
    return rt


def _write_setup_combo(tmp_path: pathlib.Path, ext_setup_value: str) -> pathlib.Path:
    """Create ``Assetto Corsa/`` with a race.ini + a Realistic_BB_v3 setup under ``tmp_path``."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    setup_ini = ac_root / "setups" / "ks_porsche_911_gt3_r_2016" / "spa" / "Realistic_BB_v3.ini"
    setup_ini.parent.mkdir(parents=True)
    setup_ini.write_text("[FUEL]\nVALUE=45\n[PRESSURE_LF]\nVALUE=20\n", encoding="utf-8")
    ext = ext_setup_value.format(setup_ini=setup_ini)
    (ac_root / "cfg" / "race.ini").write_text(
        f"[CAR_0]\nSETUP=Realistic_BB_v3.ini\n_EXT_SETUP_FILENAME={ext}\n", encoding="utf-8"
    )
    return setup_ini


def test_snapshot_resolves_applied_setup_from_race_ini(tmp_path):
    """The snapshot names the applied setup and harvests its keys (not an empty snap)."""
    setup_ini = _write_setup_combo(tmp_path, "{setup_ini}")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        """
        local sr = require("setup_reader")
        local p = sr.activeSetupIniPath({}, nil)
        local s, digest = sr.snapshotActive({}, nil)
        if not s then return "path=" .. tostring(p) .. "|SNAP=nil" end
        local fuel = ""
        for i = 1, #s.keys do
          local e = s.keys[i]
          if e.section == "FUEL" and e.key == "VALUE" then fuel = tostring(e.value) end
        end
        return "path=" .. tostring(p) .. "|snap=" .. tostring(s.path)
          .. "|fuel=" .. fuel .. "|digest=" .. tostring(digest ~= "" and "set" or "empty")
        """
    )
    assert out == (f"path={setup_ini}|snap=Realistic_BB_v3.ini|fuel=45|digest=set"), out


def test_missing_ext_setup_falls_through_to_folder_guess(tmp_path):
    """No ``_EXT_SETUP_FILENAME`` (and no setup file) → reader must not crash; snap stays nil."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    (ac_root / "cfg" / "race.ini").write_text("[CAR_0]\nSETUP=\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        'local sr = require("setup_reader"); local s = sr.snapshotActive({}, nil); '
        'return s == nil and "nil" or "snap"'
    )
    assert out == "nil", out
