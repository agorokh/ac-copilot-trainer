"""Fleet list and repo → domain tags for cross-repo mining (#70).

Loads from an external `.fleet-registry.yml` (gitignored) at the repo
root, falling back to `fleet.example.yml` shipped alongside this module.
The example file uses placeholder repo slugs because the real fleet
list includes private repositories whose existence and classification
should not be embedded in the public source tree.

To use locally:

  cp tools/process_miner/fleet.example.yml .fleet-registry.yml
  # edit .fleet-registry.yml with your actual fleet
"""

from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional dep at import time
    yaml = None


_REGISTRY_FILENAMES = (".fleet-registry.yml", ".fleet-registry.yaml")
_EXAMPLE_FILENAME = "fleet.example.yml"


def _repo_root_candidates() -> tuple[Path, ...]:
    """Walk up from this file until we find a likely repo root."""
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    for parent in (here.parent, *here.parents):
        candidates.append(parent)
        if (parent / ".git").exists():
            break
    return tuple(candidates)


def _find_registry() -> Path | None:
    for root in _repo_root_candidates():
        for name in _REGISTRY_FILENAMES:
            candidate = root / name
            if candidate.exists():
                return candidate
    # fallback to shipped example
    here = Path(__file__).resolve().parent
    example = here / _EXAMPLE_FILENAME
    if example.exists():
        return example
    return None


def _load_registry() -> dict:
    """Load the fleet registry from disk; return {} on any error."""
    if yaml is None:
        return {}
    path = _find_registry()
    if path is None:
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _build_repo_domain() -> dict[str, str]:
    data = _load_registry()
    repos = data.get("repos") or []
    domain_map: dict[str, str] = {}
    for entry in repos:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        domain = entry.get("domain")
        if isinstance(slug, str) and isinstance(domain, str):
            domain_map[slug.strip().lower()] = domain
    return domain_map


def _build_fleet_repos() -> tuple[str, ...]:
    data = _load_registry()
    repos = data.get("repos") or []
    slugs: list[str] = []
    for entry in repos:
        if isinstance(entry, dict):
            slug = entry.get("slug")
            if isinstance(slug, str):
                slugs.append(slug)
    return tuple(slugs)


REPO_DOMAIN: dict[str, str] = _build_repo_domain()
DEFAULT_FLEET_REPOS: tuple[str, ...] = _build_fleet_repos()


def domain_for_repo(repo_slug: str) -> str | None:
    """Return domain tag or None if unknown."""
    key = repo_slug.strip().lower().replace(" ", "")
    return REPO_DOMAIN.get(key)
