"""Tests for the curated-setup catalog (``tools/setup_catalog``).

The headline test is :func:`test_catalog_joins_simulated_driven_lap`: it builds a lakehouse-shaped
lap whose ``setup.hash`` is the rig-faithful djb2 of the curated file and asserts the catalog-lake
join returns the curated row — the regression the data-platform review asked for to prove the
bridge holds.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools.ai_sidecar.setup_model import parse_setup_ini
from tools.setup_catalog import registrar

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET = REPO_ROOT / "assets/setups/ks_porsche_911_gt3_r_2016/magione/Copilot_Balanced_Fast.ini"


def _djb2_reference(s: str) -> str:
    """Independent djb2 re-implementation — guards the production one against algorithm drift."""
    if not s:
        return ""
    h = 5381
    for byte in s.encode("utf-8"):
        h = (h * 33 + byte) & 0xFFFFFFFF
    return f"{h:08x}"


def test_djb2_known_answer() -> None:
    # 5381*33 + ord('a')=97 -> 177670 -> 0x2b606
    assert registrar.djb2_8hex("a") == "0002b606"
    assert registrar.djb2_8hex("") == ""


@pytest.mark.parametrize(
    "s", ["a", "FRONT_BIAS|VALUE=63", "x|y=1;z|w=2", "ks_porsche_911_gt3_r_2016"]
)
def test_djb2_matches_independent_impl(s: str) -> None:
    assert registrar.djb2_8hex(s) == _djb2_reference(s)


def test_canonical_string_is_sorted_and_formatted() -> None:
    text = "[B]\nVALUE=2\n[A]\nVALUE=1\n"
    # parts are 'A|VALUE=1' and 'B|VALUE=2', sorted, ';'-joined — order in file must not matter.
    assert registrar.canonical_setup_string(text) == "A|VALUE=1;B|VALUE=2"
    shuffled = "[A]\nVALUE=1\n[B]\nVALUE=2\n"
    assert registrar.canonical_setup_string(shuffled) == registrar.canonical_setup_string(text)


def test_canonical_hash_ignores_line_endings() -> None:
    # AC writes CRLF; our asset may be LF. splitlines() normalizes both, so the hash must agree.
    lf = "[ABS]\nVALUE=7\n[FUEL]\nVALUE=40\n"
    crlf = lf.replace("\n", "\r\n")
    assert registrar.canonical_hash(lf) == registrar.canonical_hash(crlf)
    assert len(registrar.canonical_hash(lf)) == 8


def test_build_record_from_curated_asset() -> None:
    assert ASSET.exists(), f"curated asset missing: {ASSET}"
    rec = registrar.build_record(ASSET, track_id="magione", author="AC Copilot Trainer")
    assert rec.car_id == "ks_porsche_911_gt3_r_2016"
    assert rec.name == "Copilot_Balanced_Fast"
    assert rec.track_id == "magione"
    assert len(rec.canonical_hash) == 8
    # The verified values survive the round-trip into numeric params.
    assert rec.params["FRONT_BIAS.VALUE"] == 63.0
    assert rec.params["WING_2.VALUE"] == 16.0
    assert rec.params["DIFF_COAST.VALUE"] == 60.0
    assert rec.params["TOE_OUT_LR.VALUE"] == 9.0
    assert rec.params["ARB_FRONT.VALUE"] == 6.0
    assert rec.param_count >= 50
    assert "brakes" in rec.by_category


def test_register_upsert_is_idempotent(tmp_path: Path) -> None:
    reg = tmp_path / "registry.jsonl"
    r1 = registrar.register_setup(ASSET, registry_path=reg, track_id="magione")
    r2 = registrar.register_setup(ASSET, registry_path=reg, track_id="magione")
    rows = registrar.load_registry(reg)
    assert len(rows) == 1  # second register replaces, not appends
    assert r1.canonical_hash == r2.canonical_hash
    assert rows[0]["name"] == "Copilot_Balanced_Fast"
    assert rows[0]["canonical_hash"] == r1.canonical_hash


def test_deploy_rejects_path_traversal(tmp_path: Path) -> None:
    (tmp_path / "setups").mkdir()
    with pytest.raises(ValueError, match="car_id"):
        registrar.deploy_setup(ASSET, tmp_path, car_id="../outside", track_id="magione")
    with pytest.raises(ValueError, match="track_id"):
        registrar.deploy_setup(ASSET, tmp_path, car_id="ks_porsche_911_gt3_r_2016", track_id="..")


def test_catalog_join_scoped_to_track(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Track-specific catalog rows must not absorb laps from other tracks."""
    pytest.importorskip("duckdb")
    from tools.coaching_lake.build_analytics import build_lake, run_query
    from tools.lap_archive_export import LAP_ARCHIVE_SCHEMA_VERSION

    text = ASSET.read_text(encoding="utf-8")
    chash = registrar.canonical_hash(text)
    snapshot = parse_setup_ini(text)

    monkeypatch.chdir(tmp_path)
    lap_dir = tmp_path / "journal" / "laps"
    lap_dir.mkdir(parents=True)
    for track, lap_uuid, lap_ms in (
        ("magione", "u-magione", 78123),
        ("spa", "u-spa", 120000),
    ):
        lap = {
            "schema_version": LAP_ARCHIVE_SCHEMA_VERSION,
            "lap_uuid": lap_uuid,
            "session_uuid": "s1",
            "exported_at": "2026-06-29T00:00:00Z",
            "car": {"id": "ks_porsche_911_gt3_r_2016"},
            "track": {"id": track},
            "lap": {"lap_n": 3, "lap_ms": lap_ms, "is_pb": True, "is_valid": True},
            "setup": {
                "hash": chash,
                "path": f"setups/ks_porsche_911_gt3_r_2016/{track}/Copilot_Balanced_Fast.ini",
                "snapshot": snapshot,
            },
            "conditions": {},
            "corners": [],
            "trace": {"fields": [], "samples": []},
        }
        (lap_dir / f"lap_{track}.json").write_text(json.dumps(lap), encoding="utf-8")

    build_lake("journal/laps", "journal/lake.duckdb", include_samples=False)

    reg = tmp_path / "registry.jsonl"
    registrar.register_setup(ASSET, registry_path=reg, track_id="magione")

    cols, rows = run_query("journal/lake.duckdb", registrar.catalog_join_sql(reg))
    by_name = {r[cols.index("name")]: r for r in rows}
    row = by_name["Copilot_Balanced_Fast"]
    assert row[cols.index("driven_laps")] == 1
    assert row[cols.index("best_ms")] == 78123


def test_script_invocation_from_checkout(tmp_path: Path) -> None:
    """Direct script path must work without `python -m`."""
    import subprocess

    reg = tmp_path / "registry.jsonl"
    script = REPO_ROOT / "tools/setup_catalog/registrar.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(ASSET),
            "--register",
            "--track-id",
            "magione",
            "--registry",
            str(reg),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert len(registrar.load_registry(reg)) == 1


def test_deploy_rejects_non_rig_host(tmp_path: Path) -> None:
    # No <ac_userdata>/setups folder -> not a rig host -> refuse (don't fabricate an AC tree).
    with pytest.raises(FileNotFoundError):
        registrar.deploy_setup(
            ASSET, tmp_path, car_id="ks_porsche_911_gt3_r_2016", track_id="magione"
        )


def test_deploy_is_additive_and_guards_overwrite(tmp_path: Path) -> None:
    (tmp_path / "setups").mkdir()  # pretend this is a real AC install
    dest = registrar.deploy_setup(
        ASSET, tmp_path, car_id="ks_porsche_911_gt3_r_2016", track_id="magione"
    )
    assert dest.exists()
    assert dest.read_bytes() == ASSET.read_bytes()
    # second deploy without force must refuse (never clobber operator setups)
    with pytest.raises(FileExistsError):
        registrar.deploy_setup(
            ASSET, tmp_path, car_id="ks_porsche_911_gt3_r_2016", track_id="magione"
        )
    # with force it overwrites
    registrar.deploy_setup(
        ASSET, tmp_path, car_id="ks_porsche_911_gt3_r_2016", track_id="magione", force=True
    )


def test_catalog_joins_simulated_driven_lap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end bridge proof: a lap whose setup.hash == canonical_hash(curated) joins the catalog.

    This is the regression the data-platform review asked for.
    """
    pytest.importorskip("duckdb")
    from tools.coaching_lake.build_analytics import build_lake, run_query
    from tools.lap_archive_export import LAP_ARCHIVE_SCHEMA_VERSION

    text = ASSET.read_text(encoding="utf-8")
    chash = registrar.canonical_hash(text)
    snapshot = parse_setup_ini(text)

    # Lake builder resolves db paths under <cwd>/journal — operate entirely inside tmp_path.
    monkeypatch.chdir(tmp_path)
    lap_dir = tmp_path / "journal" / "laps"
    lap_dir.mkdir(parents=True)
    lap = {
        "schema_version": LAP_ARCHIVE_SCHEMA_VERSION,
        "lap_uuid": "u-magione-1",
        "session_uuid": "s1",
        "exported_at": "2026-06-29T00:00:00Z",
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione"},
        "lap": {"lap_n": 3, "lap_ms": 78123, "is_pb": True, "is_valid": True},
        "setup": {
            "hash": chash,  # the rig writes exactly this djb2 for a driven lap on the curated file
            "path": "setups/ks_porsche_911_gt3_r_2016/magione/Copilot_Balanced_Fast.ini",
            "snapshot": snapshot,
        },
        "conditions": {},
        "corners": [],
        "trace": {"fields": [], "samples": []},
    }
    (lap_dir / "lap_magione_1.json").write_text(json.dumps(lap), encoding="utf-8")

    build_lake("journal/laps", "journal/lake.duckdb", include_samples=False)

    reg = tmp_path / "registry.jsonl"
    registrar.register_setup(ASSET, registry_path=reg, track_id="magione")

    cols, rows = run_query("journal/lake.duckdb", registrar.catalog_join_sql(reg))
    by_name = {r[cols.index("name")]: r for r in rows}
    assert "Copilot_Balanced_Fast" in by_name
    driven = by_name["Copilot_Balanced_Fast"][cols.index("driven_laps")]
    assert driven == 1, (
        f"expected the curated setup to join its driven lap, got driven_laps={driven}"
    )


def test_tunable_hash_empty_when_no_numerics() -> None:
    assert registrar.tunable_hash({}) == ""
    assert registrar.tunable_hash({"CAR.MODEL": "ks_porsche_911_gt3_r_2016"}) == ""


def test_load_registry_skips_malformed_lines(tmp_path: Path) -> None:
    reg = tmp_path / "registry.jsonl"
    reg.write_text(
        'not json\n{"car_id":"x","track_id":"t","name":"n"}\n[1,2,3]\n\n',
        encoding="utf-8",
    )
    rows = registrar.load_registry(reg)
    assert len(rows) == 1 and rows[0]["name"] == "n"


def test_main_register_list_and_join_sql(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reg = tmp_path / "registry.jsonl"
    rc = registrar._main(
        [str(ASSET), "--register", "--track-id", "magione", "--registry", str(reg)]
    )
    assert rc == 0
    assert "registered Copilot_Balanced_Fast" in capsys.readouterr().out
    assert len(registrar.load_registry(reg)) == 1

    assert registrar._main(["--list", "--registry", str(reg)]) == 0
    assert "Copilot_Balanced_Fast" in capsys.readouterr().out

    assert registrar._main(["--join-sql", "--registry", str(reg)]) == 0
    assert "LEFT JOIN laps" in capsys.readouterr().out


def test_main_deploy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "setups").mkdir()
    rc = registrar._main(
        [
            str(ASSET),
            "--deploy",
            str(tmp_path),
            "--car-id",
            "ks_porsche_911_gt3_r_2016",
            "--track-id",
            "magione",
        ]
    )
    assert rc == 0
    dest = (
        tmp_path / "setups" / "ks_porsche_911_gt3_r_2016" / "magione" / "Copilot_Balanced_Fast.ini"
    )
    assert dest.exists()
    assert "deployed ->" in capsys.readouterr().out


def test_main_errors_when_nothing_to_do(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):  # ini given, no action flag
        registrar._main([str(ASSET), "--registry", str(tmp_path / "r.jsonl")])
    with pytest.raises(SystemExit):  # action flag but no ini path
        registrar._main(["--register"])
