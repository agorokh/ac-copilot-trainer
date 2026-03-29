#!/usr/bin/env python3
"""Post-copy / post-update hook for Copier: renames + text substitution for child projects.

Runs in the destination repository root (Copier _tasks cwd). Idempotent when answers match
canonical template defaults (ProjectTemplate, project_template, project-template).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

_IDENT_PKG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IDENT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

ROOT = Path.cwd()
ANSWERS = ROOT / ".copier-answers.yml"

SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        ".scratch",
        ".egg-info",
    }
)

TEXT_NAMES = frozenset(
    {
        ".cursorrules",
        "Makefile",
        "Dockerfile",
        "Justfile",
    }
)

TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".mdc",
        ".py",
        ".toml",
        ".yml",
        ".yaml",
        ".json",
        ".txt",
        ".sh",
    }
)

# Do not rewrite this script's own string literals (canonical default names).
# copier.yml documents ProjectTemplate paths; rewriting corrupts comments and causes noisy updates.
# .copier-answers.yml holds _src_path URLs that may contain project-template substrings.
SKIP_REWRITE_FILES = frozenset({"scripts/copier_post_copy.py", "copier.yml", ".copier-answers.yml"})


def _fallback_key_value_lines(raw: str) -> dict[str, str]:
    """Parse simple ``key: value`` lines when PyYAML is missing or top-level parse failed."""
    data: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("_"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        data[key] = val
    return data


def _load_answers(path: Path) -> dict[str, str]:
    if not path.is_file():
        print("copier_post_copy: no .copier-answers.yml; skipping", file=sys.stderr)
        return {}

    raw = path.read_text(encoding="utf-8")
    data: dict[str, str] | dict[object, object]

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        data = _fallback_key_value_lines(raw)
    else:
        loaded = yaml.safe_load(raw)
        if loaded is None:
            data = {}
        elif isinstance(loaded, dict):
            data = loaded
        else:
            raise ValueError(
                f"copier_post_copy: {path} must be a YAML mapping at the top level, "
                f"not {type(loaded).__name__}"
            )

    out: dict[str, str] = {}
    for k in ("project_name", "project_key", "package_name"):
        v = data.get(k)
        if isinstance(v, str) and v:
            out[k] = v
    return out


def _validate_answer_strings(project_name: str, project_key: str, package_name: str) -> None:
    """Reject path injection and invalid package identifiers (defense in depth vs copier.yml)."""
    for label, value in (
        ("project_name", project_name),
        ("project_key", project_key),
        ("package_name", package_name),
    ):
        if not value:
            raise ValueError(f"copier_post_copy: {label} is empty")
        if "\x00" in value or ".." in value:
            raise ValueError(f"copier_post_copy: illegal {label}: {value!r}")
        if "/" in value or "\\" in value:
            raise ValueError(
                f"copier_post_copy: {label} must be a single path segment, got {value!r}"
            )
    if not _IDENT_KEY.fullmatch(project_key):
        raise ValueError(
            "copier_post_copy: project_key must match ^[A-Za-z][A-Za-z0-9_]*$ "
            f"(got {project_key!r})"
        )
    if not _IDENT_PKG.fullmatch(package_name):
        raise ValueError(
            "copier_post_copy: package_name must be a valid Python identifier "
            f"(got {package_name!r})"
        )


def _should_scan(path: Path) -> bool:
    if path.is_dir():
        return False
    name = path.name
    if name in TEXT_NAMES:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def _patch_pyproject(text: str, project_name: str, package_name: str) -> str:
    def esc_toml_str(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    pn = esc_toml_str(project_name)
    pkg = esc_toml_str(package_name)
    # Use a callable repl so backslashes in ``pn`` are not interpreted by re.sub.
    text = re.sub(
        r'^name\s*=\s*"project-template"\s*$',
        lambda _m: f'name = "{pn}"',
        text,
        flags=re.MULTILINE,
    )
    text = text.replace(
        'include = ["project_template*", "tools*"]',
        f'include = ["{pkg}*", "tools*"]',
    )
    text = text.replace(
        'source = ["src/project_template", "tools"]',
        f'source = ["src/{pkg}", "tools"]',
    )
    return text


def _skip_dir(name: str) -> bool:
    if name in SKIP_DIRS:
        return True
    return name.endswith((".egg-info", ".dist-info"))


def _subst_canonical_names(text: str, pairs: list[tuple[str, str]]) -> str:
    """Replace template canonical strings without cascading when news contain old substrings.

    Two-phase: map each needle to a private-use placeholder, then substitute news. Order must
    be longest needles first so shorter needles are not applied inside longer matches.
    """
    for i, (old, new) in enumerate(pairs):
        if old == new:
            continue
        text = text.replace(old, f"\ue000{i:02d}\ue001")
    for i, (old, new) in enumerate(pairs):
        if old == new:
            continue
        text = text.replace(f"\ue000{i:02d}\ue001", new)
    return text


def _rewrite_tree(project_key: str, package_name: str, project_name: str) -> None:
    # Longer / path-like needles first so we do not partially replace inside longer matches.
    replacements: list[tuple[str, str]] = [
        ("docs/01_Vault/ProjectTemplate", f"docs/01_Vault/{project_key}"),
        ("src/project_template", f"src/{package_name}"),
        ("project-template", project_name),
        ("project_template", package_name),
        ("ProjectTemplate", project_key),
    ]

    for dirpath, dirnames, filenames in os.walk(ROOT, topdown=True):
        dirnames[:] = [d for d in dirnames if not _skip_dir(d)]
        for fn in filenames:
            path = Path(dirpath) / fn
            try:
                rel = path.relative_to(ROOT)
            except ValueError:
                continue
            if str(rel).replace("\\", "/") in SKIP_REWRITE_FILES:
                continue
            # pyproject.toml is patched by _patch_pyproject only; general replaces can corrupt
            # names when the new package_name still contains substrings like "project_template".
            if path.name == "pyproject.toml":
                continue
            if not _should_scan(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            orig = text
            text = _subst_canonical_names(text, replacements)
            if text != orig:
                path.write_text(text, encoding="utf-8", newline="\n")


def _relocate_or_merge_tree(*, active: bool, src: Path, dst: Path) -> None:
    """Move Copier-rendered ``src`` to ``dst``, or merge new files into an existing ``dst``."""
    if not active or not src.is_dir():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.move(str(src), str(dst))
        return
    _merge_missing_files_only(src, dst)
    shutil.rmtree(src)


def _merge_missing_files_only(src: Path, dst: Path) -> None:
    """Copy files from ``src`` into ``dst`` without overwriting existing files (vault-safe)."""
    if not src.is_dir():
        return
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        out = dst / rel
        if out.is_file():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)


def main() -> int:
    try:
        raw_nonempty = ANSWERS.is_file() and ANSWERS.read_text(encoding="utf-8").strip() != ""
        answers = _load_answers(ANSWERS)
    except Exception as err:  # noqa: BLE001 — YAML errors, I/O, bad top-level type
        print(f"copier_post_copy: failed to load {ANSWERS}: {err}", file=sys.stderr)
        return 1

    if not answers:
        return 0

    if raw_nonempty:
        for k in ("project_name", "project_key", "package_name"):
            if k not in answers:
                print(
                    f"copier_post_copy: incomplete {ANSWERS} (missing {k}); "
                    "refusing to guess defaults for renames.",
                    file=sys.stderr,
                )
                return 2

    project_name = answers.get("project_name", "project-template")
    project_key = answers.get("project_key", "ProjectTemplate")
    package_name = answers.get("package_name", "project_template")

    try:
        _validate_answer_strings(project_name, project_key, package_name)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 2

    vault_src = ROOT / "docs/01_Vault/ProjectTemplate"
    vault_dst = ROOT / f"docs/01_Vault/{project_key}"
    _relocate_or_merge_tree(
        active=project_key != "ProjectTemplate",
        src=vault_src,
        dst=vault_dst,
    )

    pkg_src = ROOT / "src/project_template"
    pkg_dst = ROOT / "src" / package_name
    _relocate_or_merge_tree(
        active=package_name != "project_template",
        src=pkg_src,
        dst=pkg_dst,
    )

    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        pt = pyproject.read_text(encoding="utf-8")
        patched = _patch_pyproject(pt, project_name, package_name)
        if patched != pt:
            pyproject.write_text(patched, encoding="utf-8", newline="\n")

    _rewrite_tree(project_key, package_name, project_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
