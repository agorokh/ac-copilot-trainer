"""Fleet list and repo → domain tags for cross-repo mining (#70).

Loads from an external `.fleet-registry.yml` (gitignored) at the repo
root, falling back to `fleet.example.yml` shipped alongside this module.
The example file uses placeholder repo slugs because the real fleet
list includes private repositories whose existence and classification
should not be embedded in the public source tree.

To use locally:

  cp tools/process_miner/fleet.example.yml .fleet-registry.yml
  # edit .fleet-registry.yml with your actual fleet

Override discovery with ``FLEET_REGISTRY_PATH`` (absolute path to a YAML file).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - optional dep at import time
    yaml = None

_LOG = logging.getLogger(__name__)

_REGISTRY_FILENAMES = (".fleet-registry.yml", ".fleet-registry.yaml")
_EXAMPLE_FILENAME = "fleet.example.yml"
_ENV_REGISTRY_PATH = "FLEET_REGISTRY_PATH"


def _normalize_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "")


def _repo_root_candidates() -> tuple[Path, ...]:
    """Walk up from this file until we find a likely repo root."""
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    for parent in here.parents:
        candidates.append(parent)
        if (parent / ".git").exists():
            break
    return tuple(candidates)


def _registry_path_from_env() -> Path | None:
    override = os.environ.get(_ENV_REGISTRY_PATH)
    if not override:
        return None
    path = Path(override).expanduser()
    if path.is_file():
        return path
    _LOG.warning("%s is set but not a file: %s", _ENV_REGISTRY_PATH, path)
    return None


def _find_registry() -> Path | None:
    env_path = _registry_path_from_env()
    if env_path is not None:
        return env_path
    for root in _repo_root_candidates():
        for name in _REGISTRY_FILENAMES:
            candidate = root / name
            if candidate.exists():
                return candidate
    here = Path(__file__).resolve().parent
    example = here / _EXAMPLE_FILENAME
    if example.exists():
        return example
    return None


def _load_registry_file(path: Path) -> dict:
    """Parse a fleet registry YAML file; return {} only when the file is missing."""
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load the fleet registry at "
            f"{path}. Install with: pip install -e '.[dev]'"
        )
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError as exc:
        _LOG.warning("Failed to read fleet registry %s: %s", path, exc)
        return {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in fleet registry {path}") from exc
    if not isinstance(data, dict):
        _LOG.warning("Fleet registry root must be a mapping: %s", path)
        return {}
    return data


def load_fleet_registry(
    registry_path: Path | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Load slug→domain map and default fleet repo slugs from a registry file."""
    if registry_path is None:
        found = _find_registry()
        if found is None:
            return {}, ()
        registry_path = found
    data = _load_registry_file(registry_path)
    return _build_repo_domain(data), _build_fleet_repos(data)


def _build_repo_domain(data: dict) -> dict[str, str]:
    repos = data.get("repos") or []
    if not isinstance(repos, list):
        return {}
    domain_map: dict[str, str] = {}
    for entry in repos:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        domain = entry.get("domain")
        if isinstance(slug, str) and isinstance(domain, str):
            domain_map[_normalize_slug(slug)] = domain
    return domain_map


def _build_fleet_repos(data: dict) -> tuple[str, ...]:
    repos = data.get("repos") or []
    if not isinstance(repos, list):
        return ()
    slugs: list[str] = []
    for entry in repos:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        domain = entry.get("domain")
        if isinstance(slug, str) and isinstance(domain, str):
            slugs.append(_normalize_slug(slug))
    return tuple(slugs)


_REGISTRY_DATA: dict
_REGISTRY_PATH = _find_registry()
if _REGISTRY_PATH is not None:
    _REGISTRY_DATA = _load_registry_file(_REGISTRY_PATH)
else:
    _REGISTRY_DATA = {}

REPO_DOMAIN: dict[str, str] = _build_repo_domain(_REGISTRY_DATA)
DEFAULT_FLEET_REPOS: tuple[str, ...] = _build_fleet_repos(_REGISTRY_DATA)


def domain_for_repo(repo_slug: str) -> str | None:
    """Return domain tag or None if unknown."""
    return REPO_DOMAIN.get(_normalize_slug(repo_slug))
