"""Tests for fleet registry loading (tools/process_miner/fleet.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.process_miner import fleet as fleet_mod
from tools.process_miner.aggregate import find_universal_scope_titles
from tools.process_miner.fleet import (
    USING_EXAMPLE_REGISTRY,
    load_fleet_registry,
)


def test_fleet_registry_loads_from_root_file(tmp_path: Path) -> None:
    registry_path = tmp_path / ".fleet-registry.yml"
    registry_path.write_text(
        "\n".join(
            [
                "repos:",
                '  - slug: "your-org/example-template-repo"',
                "    domain: infra",
                "    default: true",
                '  - slug: "your-org/example-legal-repo-a"',
                "    domain: legal",
            ]
        ),
        encoding="utf-8",
    )

    slug_domain, default_fleet_repos = load_fleet_registry(registry_path)

    assert slug_domain == {
        "your-org/example-template-repo": "infra",
        "your-org/example-legal-repo-a": "legal",
    }
    assert default_fleet_repos == (
        "your-org/example-template-repo",
        "your-org/example-legal-repo-a",
    )


def test_fleet_registry_malformed_content_gracefully_degrades(tmp_path: Path) -> None:
    registry_path = tmp_path / ".fleet-registry.yml"

    registry_path.write_text("not-a-mapping\n", encoding="utf-8")
    slug_domain, default_fleet_repos = load_fleet_registry(registry_path)
    assert slug_domain == {}
    assert default_fleet_repos == ()

    registry_path.write_text("repos:\n  - slug: [\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid YAML"):
        load_fleet_registry(registry_path)

    registry_path.write_text(
        "\n".join(
            [
                "repos:",
                "  slug: your-org/example-legal-repo-a",
                "  domain: legal",
            ]
        ),
        encoding="utf-8",
    )
    slug_domain, default_fleet_repos = load_fleet_registry(registry_path)
    assert slug_domain == {}
    assert default_fleet_repos == ()

    registry_path.write_text(
        "\n".join(
            [
                "repos:",
                "  - slug: your-org/example-legal-repo-a",
                "  - domain: legal",
            ]
        ),
        encoding="utf-8",
    )
    slug_domain, default_fleet_repos = load_fleet_registry(registry_path)
    assert slug_domain == {}
    assert default_fleet_repos == ()


def test_fleet_registry_empty_file_and_empty_repos(tmp_path: Path) -> None:
    registry_path = tmp_path / ".fleet-registry.yml"

    registry_path.write_text("", encoding="utf-8")
    slug_domain, default_fleet_repos = load_fleet_registry(registry_path)
    assert slug_domain == {}
    assert default_fleet_repos == ()

    registry_path.write_text("repos: []\n", encoding="utf-8")
    slug_domain, default_fleet_repos = load_fleet_registry(registry_path)
    assert slug_domain == {}
    assert default_fleet_repos == ()

    title_repos = {"shared pattern": set()}
    assert find_universal_scope_titles(title_repos, slug_domain) == set()


def test_fleet_registry_slug_normalization(tmp_path: Path) -> None:
    registry_path = tmp_path / ".fleet-registry.yml"
    registry_path.write_text(
        'repos:\n  - slug: " Your-Org /Example-Repo "\n    domain: infra\n',
        encoding="utf-8",
    )

    slug_domain, _ = load_fleet_registry(registry_path)
    assert slug_domain == {"your-org/example-repo": "infra"}


def test_find_registry_falls_back_to_shipped_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet_mod, "_repo_root_candidates", lambda: ())
    monkeypatch.delenv("FLEET_REGISTRY_PATH", raising=False)
    found = fleet_mod._find_registry()
    assert found is not None
    assert found.resolve() == fleet_mod._SHIPPED_EXAMPLE_REGISTRY.resolve()
    slug_domain, repos = load_fleet_registry(found)
    assert "your-org/example-template-repo" in slug_domain
    assert len(repos) >= 10


def test_using_example_registry_flag() -> None:
    assert isinstance(USING_EXAMPLE_REGISTRY, bool)


def test_domain_for_repo_returns_none_when_registry_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fleet_mod._fleet_cache = None
    monkeypatch.setattr(fleet_mod, "yaml", None)
    monkeypatch.setattr(
        fleet_mod,
        "_find_registry",
        lambda: fleet_mod._SHIPPED_EXAMPLE_REGISTRY,
    )
    assert fleet_mod.domain_for_repo("your-org/example-repo") is None
    fleet_mod._fleet_cache = None


def test_fleet_registry_env_override_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "no-such-registry.yml"
    monkeypatch.setenv("FLEET_REGISTRY_PATH", str(missing))
    with pytest.raises(FileNotFoundError, match="FLEET_REGISTRY_PATH"):
        load_fleet_registry()


def test_fleet_registry_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry_path = tmp_path / "custom-fleet.yml"
    registry_path.write_text(
        'repos:\n  - slug: "your-org/from-env"\n    domain: test\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("FLEET_REGISTRY_PATH", str(registry_path))

    slug_domain, default_fleet_repos = load_fleet_registry()
    assert slug_domain == {"your-org/from-env": "test"}
    assert default_fleet_repos == ("your-org/from-env",)
