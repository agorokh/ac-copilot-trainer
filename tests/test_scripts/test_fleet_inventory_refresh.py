"""Tests for scripts/fleet_inventory_refresh.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "fleet_inventory_refresh.py"
YAML_PATH = ROOT / "docs/01_Vault/AcCopilotTrainer/fleet/fleet_inventory.yml"
INDEX_PATH = ROOT / "docs/01_Vault/AcCopilotTrainer/fleet/_index.md"


def _load_fir():
    name = "fleet_inventory_refresh_testmod"
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fir = _load_fir()


def test_encode_contents_path() -> None:
    assert fir._encode_contents_path("docs/01_Vault") == "docs/01_Vault"
    assert fir._encode_contents_path(".claude/settings.json") == ".claude/settings.json"
    assert fir._encode_contents_path("a/b c") == "a/b%20c"


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        ("HTTP 404: gone", True),
        ("HTTP 403: no", False),
        (None, False),
    ],
)
def test_is_not_found(err: str | None, expected: bool) -> None:
    assert fir._is_not_found(err) is expected


def test_render_table_row_ok() -> None:
    row = fir.render_table_row(
        {
            "slug": "agorokh/x",
            "domain": "infra",
            "github": {
                "language": "Python",
                "pushed_at": "2026-01-02T03:04:05Z",
                "error": None,
            },
            "template_sync": {"copier_answers_present": True, "error": None},
            "vault": {"project_key": "MyVault", "error": None},
            "agent_config": {"settings_json_present": True, "error": None},
        }
    )
    assert "| agorokh/x | infra | Python | yes | MyVault | yes |" in row
    assert "| 2026-01-02 03:04:05 | ok |" in row


def test_write_index_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    idx = tmp_path / "_index.md"
    idx.write_text(
        f"before\n{fir.MARK_BEGIN}\nOLD\n{fir.MARK_END}\nafter\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(fir, "INDEX_PATH", idx)
    fir.write_index(
        [
            {
                "slug": "agorokh/a",
                "domain": "legal",
                "github": {"language": None, "pushed_at": None, "error": "HTTP 500"},
                "template_sync": {"error": "skipped"},
                "vault": {"error": "skipped"},
                "agent_config": {"error": "skipped"},
            }
        ]
    )
    body = idx.read_text(encoding="utf-8")
    assert "OLD" not in body
    assert "| agorokh/a | legal |" in body
    assert "| error |" in body


def test_render_index_missing_markers_raises() -> None:
    with pytest.raises(ValueError, match="markers missing"):
        fir.render_index_with_table([], "no markers here")


def test_refresh_repos_uses_fetcher() -> None:
    def fake_fetch(_owner: str, _repo: str, _token: str | None) -> dict[str, object]:
        return {
            "github": {"language": "Go", "pushed_at": None, "error": None},
            "template_sync": {"copier_answers_present": False, "error": None},
            "vault": {"vault_root_present": False, "project_key": None, "error": None},
            "agent_config": {
                "settings_json_present": False,
                "hook_event_count": None,
                "error": None,
            },
        }

    out = fir.refresh_repos(
        [{"slug": "agorokh/z", "domain": "infra", "name": "z"}],
        None,
        fake_fetch,
    )
    assert len(out) == 1
    assert out[0]["github"]["language"] == "Go"


def test_merge_from_fleet_py_adds_all_default_slugs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT))
    from tools.process_miner.fleet import DEFAULT_FLEET_REPOS

    base = [{"slug": "agorokh/template-repo", "name": "template-repo", "domain": "infra"}]
    out = fir.merge_from_fleet_py(base)
    assert {r["slug"] for r in out} == set(DEFAULT_FLEET_REPOS)


def test_refresh_repos_preserves_activity_when_fetch_omits() -> None:
    def fake_fetch(_owner: str, _repo: str, _token: str | None) -> dict[str, object]:
        return {
            "github": {"language": "Python", "pushed_at": None, "error": None},
            "template_sync": {"copier_answers_present": False, "error": None},
            "vault": {"vault_root_present": False, "project_key": None, "error": None},
            "agent_config": {
                "settings_json_present": False,
                "hook_event_count": None,
                "error": None,
            },
        }

    out = fir.refresh_repos(
        [
            {
                "slug": "agorokh/z",
                "domain": "infra",
                "activity": {"note": "hand-maintained"},
            }
        ],
        None,
        fake_fetch,
    )
    assert out[0].get("activity") == {"note": "hand-maintained"}


def test_fleet_inventory_yml_slugs_match_fleet_py(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT))
    from tools.process_miner.fleet import DEFAULT_FLEET_REPOS

    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    repos = data.get("repos") or []
    slugs = {r["slug"] for r in repos if isinstance(r, dict) and "slug" in r}
    assert slugs == set(DEFAULT_FLEET_REPOS)


def test_main_only_index_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yml = tmp_path / "fleet_inventory.yml"
    yml.write_text(
        yaml.safe_dump(
            {
                "inventory_version": 1,
                "repos": [{"slug": "agorokh/x", "name": "x", "domain": "infra"}],
            }
        ),
        encoding="utf-8",
    )
    idx = tmp_path / "_index.md"
    idx.write_text(
        f"x\n{fir.MARK_BEGIN}\n| old |\n{fir.MARK_END}\ny\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(fir, "YAML_PATH", yml)
    monkeypatch.setattr(fir, "INDEX_PATH", idx)
    assert fir.main(["--only-index"]) == 0
    assert "agorokh/x" in idx.read_text(encoding="utf-8")


def test_main_non_mapping_repo_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yml = tmp_path / "fleet_inventory.yml"
    yml.write_text(
        yaml.safe_dump({"inventory_version": 1, "repos": ["bad"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(fir, "YAML_PATH", yml)
    assert fir.main(["--dry-run"]) == 1


def test_main_invalid_slug_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yml = tmp_path / "fleet_inventory.yml"
    yml.write_text(
        yaml.safe_dump({"inventory_version": 1, "repos": [{"slug": "bad", "domain": "x"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(fir, "YAML_PATH", yml)
    assert fir.main(["--dry-run"]) == 1


def test_main_invalid_yaml_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yml = tmp_path / "bad.yml"
    yml.write_text("repos: [unclosed\n", encoding="utf-8")
    monkeypatch.setattr(fir, "YAML_PATH", yml)
    assert fir.main(["--dry-run"]) == 1


def test_main_missing_repos_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yml = tmp_path / "n.yml"
    yml.write_text("inventory_version: 1\n", encoding="utf-8")
    monkeypatch.setattr(fir, "YAML_PATH", yml)
    assert fir.main(["--dry-run"]) == 1


def test_main_only_index_and_dry_run_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fir, "YAML_PATH", Path("/nonexistent/fleet_inventory.yml"))
    assert fir.main(["--only-index", "--dry-run"]) == 2


def test_main_only_index_and_from_fleet_py_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fir, "YAML_PATH", Path("/nonexistent/fleet_inventory.yml"))
    assert fir.main(["--only-index", "--from-fleet-py"]) == 2
