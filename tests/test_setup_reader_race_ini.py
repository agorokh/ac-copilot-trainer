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


def test_race_ini_setup_resolution_is_scoped_to_car0(tmp_path):
    """An AI/opponent setup in another section must not be attributed to player car 0."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    car_root = ac_root / "setups" / "ks_porsche_911_gt3_r_2016" / "spa"
    car_root.mkdir(parents=True)
    ai_setup = car_root / "AiSetup.ini"
    car0_setup = car_root / "Realistic_BB_v3.ini"
    ai_setup.write_text("[FUEL]\nVALUE=20\n", encoding="utf-8")
    car0_setup.write_text("[FUEL]\nVALUE=45\n", encoding="utf-8")
    (ac_root / "cfg" / "race.ini").write_text(
        f"[CAR_1]\n_EXT_SETUP_FILENAME={ai_setup}\n[CAR_0]\n_EXT_SETUP_FILENAME={car0_setup}\n",
        encoding="utf-8",
    )
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute('local sr = require("setup_reader"); return sr.activeSetupIniPath({}, nil)')
    assert out == str(car0_setup), out


def test_race_ini_setup_resolution_is_cached_within_session(tmp_path):
    """The applied setup is a spawn-time fact.

    Later CM edits to race.ini must not alter archives for the same sim session.
    """
    setup_ini = _write_setup_combo(tmp_path, "{setup_ini}")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')
    first = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert first == str(setup_ini), first
    other = setup_ini.with_name("OtherSetup.ini")
    other.write_text("[FUEL]\nVALUE=15\n", encoding="utf-8")
    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.write_text(f"[CAR_0]\n_EXT_SETUP_FILENAME={other}\n", encoding="utf-8")
    out = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert out == str(setup_ini), out


def test_race_ini_setup_resolution_refreshes_when_session_changes(tmp_path):
    """A long-lived Lua VM must not carry one session's race.ini setup into the next."""
    setup_ini = _write_setup_combo(tmp_path, "{setup_ini}")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')
    first = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert first == str(setup_ini), first
    other = setup_ini.with_name("OtherSetup.ini")
    other.write_text("[FUEL]\nVALUE=15\n", encoding="utf-8")
    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.write_text(f"[CAR_0]\n_EXT_SETUP_FILENAME={other}\n", encoding="utf-8")

    out = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 2 })")

    assert out == str(other), out


def test_race_ini_missing_setup_pointer_is_negative_cached_within_session(tmp_path):
    """No race.ini setup pointer should be cached per session, then refreshed next session."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    car_root = ac_root / "setups" / "ks_porsche_911_gt3_r_2016" / "spa"
    car_root.mkdir(parents=True)
    other = car_root / "OtherSetup.ini"
    other.write_text("[FUEL]\nVALUE=15\n", encoding="utf-8")
    race_ini = ac_root / "cfg" / "race.ini"
    race_ini.write_text("[CAR_0]\nSETUP=\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')
    first = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert first != str(other), first
    race_ini.write_text(f"[CAR_0]\n_EXT_SETUP_FILENAME={other}\n", encoding="utf-8")

    same_session = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    next_session = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 2 })")

    assert same_session != str(other), same_session
    assert next_session == str(other), next_session


def test_race_ini_read_failure_is_not_negative_cached(tmp_path):
    """A missing/locked race.ini should retry instead of pinning no-setup for the session."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    car_root = ac_root / "setups" / "ks_porsche_911_gt3_r_2016" / "spa"
    car_root.mkdir(parents=True)
    setup_ini = car_root / "LateSetup.ini"
    setup_ini.write_text("[FUEL]\nVALUE=33\n", encoding="utf-8")
    race_ini = ac_root / "cfg" / "race.ini"
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')
    first = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert first != str(setup_ini), first

    race_ini.write_text(f"[CAR_0]\n_EXT_SETUP_FILENAME={setup_ini}\n", encoding="utf-8")
    out = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")

    assert out == str(setup_ini), out


def test_missing_setup_file_pointer_is_negative_cached_within_session(tmp_path):
    """A readable race.ini pointing at a missing setup is confirmed no-setup for that session."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    car_root = ac_root / "setups" / "ks_porsche_911_gt3_r_2016" / "spa"
    car_root.mkdir(parents=True)
    setup_ini = car_root / "MissingThenCreated.ini"
    race_ini = ac_root / "cfg" / "race.ini"
    race_ini.write_text(f"[CAR_0]\n_EXT_SETUP_FILENAME={setup_ini}\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')
    first = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert first != str(setup_ini), first
    setup_ini.write_text("[FUEL]\nVALUE=33\n", encoding="utf-8")

    same_session = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    next_session = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 2 })")

    assert same_session != str(setup_ini), same_session
    assert next_session == str(setup_ini), next_session


def test_missing_ext_setup_reports_no_setup(tmp_path):
    """A readable race.ini without ``_EXT_SETUP_FILENAME`` reports no applied setup."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    (ac_root / "cfg" / "race.ini").write_text("[CAR_0]\nSETUP=\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        'local sr = require("setup_reader"); '
        "local s, digest, no_setup = sr.snapshotActive({}, nil); "
        'return (s == nil and "nil" or "snap") .. "|" .. tostring(digest) .. "|" '
        ".. tostring(no_setup)"
    )
    assert out == "nil||true", out


def test_active_setup_ini_path_surfaces_confirmed_no_setup(tmp_path):
    """#531 / PR #547: `activeSetupIniPath` second return is True only for a CONFIRMED
    race.ini no-setup — the connect-edge `setup.active` broadcaster publishes a CLEARED
    state on that flag, never on a transient miss."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    (ac_root / "cfg" / "race.ini").write_text("[CAR_0]\nSETUP=\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        'local sr = require("setup_reader"); '
        "local p, no_setup = sr.activeSetupState({}, nil); "
        'return tostring(p) .. "|" .. tostring(no_setup)'
    )
    assert out == "nil|true", out


def test_active_setup_state_never_reports_unreadable_guess(tmp_path):
    """Codex on PR #547: a vanilla race.ini (SETUP= name, no _EXT pointer) can fall through
    to a synthesized folder-guess path that names a file which was never readable — the
    broadcaster must see 'unresolved' (nil, False), never a phantom setup and never a
    confirmed no-setup (clearing on it would wipe a valid name)."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    # Vanilla shape: SETUP names a file that does not exist anywhere on disk.
    (ac_root / "cfg" / "race.ini").write_text("[CAR_0]\nSETUP=GhostSetup.ini\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        'local sr = require("setup_reader"); '
        "local p, no_setup = sr.activeSetupState({}, nil); "
        'return tostring(p) .. "|" .. tostring(no_setup)'
    )
    assert out == "nil|false", out


def test_active_setup_ini_path_resolved_setup_is_not_no_setup(tmp_path):
    setup_ini = _write_setup_combo(tmp_path, "{setup_ini}")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        'local sr = require("setup_reader"); '
        "local p, no_setup = sr.activeSetupState({}, nil); "
        'return tostring(p) .. "|" .. tostring(no_setup)'
    )
    assert out == f"{setup_ini}|false", out


def test_confirmed_no_race_ini_setup_blocks_legacy_folder_guess(tmp_path):
    """A confirmed race.ini no-setup should not hallucinate ``setups/unknown/unknown/race.ini``."""
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    fallback = ac_root / "setups" / "unknown" / "unknown" / "race.ini"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("[FUEL]\nVALUE=45\n", encoding="utf-8")
    (ac_root / "cfg" / "race.ini").write_text("[CAR_0]\nSETUP=\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute(
        'local sr = require("setup_reader"); '
        "local s, digest, no_setup = sr.snapshotActive({}, nil); "
        'return (s == nil and "nil" or "snap") .. "|" .. tostring(digest) .. "|" '
        ".. tostring(no_setup)"
    )
    assert out == "nil||true", out


def test_race_ini_setup_cache_resets_on_new_spawn_with_reused_session_index(tmp_path):
    """#466 B1: a new Quick-Drive spawn that REUSES the session index but bakes a different setup
    must archive the NEW setup once the trainer signals the spawn via ``resetRaceIniCache()``.

    The reset is the spawn discriminator the session index alone cannot provide: without it the
    cache holds the spawn-time setup (``test_race_ini_setup_resolution_is_cached_within_session`` —
    the same-spawn in-place-edit case that must NOT flap the archive), and the trainer calls the
    reset only on a real re-spawn (``resetSessionState`` / ``resetRollingDrivingState``).
    """
    setup_ini = _write_setup_combo(tmp_path, "{setup_ini}")  # Realistic_BB_v3.ini
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')
    first = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert first == str(setup_ini), first

    other = setup_ini.with_name("OtherSetup.ini")
    other.write_text("[FUEL]\nVALUE=15\n", encoding="utf-8")
    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.write_text(f"[CAR_0]\n_EXT_SETUP_FILENAME={other}\n", encoding="utf-8")

    rt.execute("sr.resetRaceIniCache()")  # the trainer's new-spawn hook
    out = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")

    assert out == str(other), out


def test_transient_race_ini_miss_does_not_folder_guess(tmp_path):
    """#466 B2: a momentarily missing/locked ``cfg/race.ini`` must yield nil (retry) rather than a
    legacy ``setups/<car>/<track>/`` folder guess, which can archive the WRONG setup. A later real
    read then resolves the applied setup — the transient miss is not negative-cached.
    """
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    # A folder-guess candidate (lupa car/track ids resolve to "unknown") that must NOT be attributed
    # while race.ini is momentarily unreadable.
    guess = ac_root / "setups" / "unknown" / "unknown" / "race.ini"
    guess.parent.mkdir(parents=True)
    guess.write_text("[FUEL]\nVALUE=99\n", encoding="utf-8")
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    rt.execute('sr = require("setup_reader")')

    # cfg/race.ini absent → transient → nil, NOT the folder guess.
    miss = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert miss != str(guess), miss
    assert miss is None, f"expected nil on a transient race.ini miss, got {miss!r}"

    # CM writes race.ini naming the applied setup → resolves it (retry after the transient miss).
    applied = ac_root / "setups" / "unknown" / "unknown" / "Applied.ini"
    applied.write_text("[FUEL]\nVALUE=45\n", encoding="utf-8")
    (ac_root / "cfg" / "race.ini").write_text(
        f"[CAR_0]\n_EXT_SETUP_FILENAME={applied}\n", encoding="utf-8"
    )
    out = rt.execute("return sr.activeSetupIniPath({}, { currentSessionIndex = 1 })")
    assert out == str(applied), out


def test_vanilla_setup_without_ext_filename_still_folder_guesses(tmp_path):
    """#466 B2 guard: a readable race.ini with vanilla ``SETUP=<name>`` and no
    ``_EXT_SETUP_FILENAME`` must still resolve via the legacy folder guess — the
    transient-miss fix must not re-break the vanilla-setup fallback (927b07ed, #461).
    """
    ac_root = tmp_path / "Assetto Corsa"
    (ac_root / "cfg").mkdir(parents=True)
    guess = ac_root / "setups" / "unknown" / "unknown" / "race.ini"
    guess.parent.mkdir(parents=True)
    guess.write_text("[FUEL]\nVALUE=45\n", encoding="utf-8")
    (ac_root / "cfg" / "race.ini").write_text(
        "[CAR_0]\nSETUP=Realistic_BB_v3.ini\n", encoding="utf-8"
    )
    rt = _runtime(str(tmp_path).replace("\\", "/"))
    out = rt.execute('local sr = require("setup_reader"); return sr.activeSetupIniPath({}, nil)')
    # The Lua folder guess builds paths with forward slashes; normalize for the Windows comparison.
    assert out == str(guess).replace("\\", "/"), out
