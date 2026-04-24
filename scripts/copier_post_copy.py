#!/usr/bin/env python3
"""Post-copy / post-update hook for Copier: renames + text substitution for child projects.

Runs in the destination repository root (Copier _tasks cwd). Idempotent when answers match
canonical template defaults (ProjectTemplate, project_template, project-template).

Symlink policy (see ``_should_scan``): symlinks are *always* skipped, regardless of whether
their lexical path matches ``EXAMPLE_FILE_ALLOWLIST`` or their suffix is in ``TEXT_SUFFIXES``.
Without this guard a symlinked stub (e.g. ``ops/service.yaml.example`` pointing outside the
repo) would survive the lexical ``relative_to(ROOT)`` check and ``_rewrite_tree`` would mutate
the symlink target — a serious foot-gun on ``copier update``. Do not relax this without
also rejecting writes that escape ``ROOT``.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

_IDENT_PKG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IDENT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# project_name doubles as the canonical `repo_id` in ops/service.yaml and the
# entry registered in workstation-ops/ops/sources.yaml, so it must be a
# PEP 503 / repo-slug string. This regex MUST stay in sync with the
# `project_name.validator` regex in copier.yml; see CodeRabbit feedback on
# PR #86 — an edited or legacy `.copier-answers.yml` can otherwise smuggle
# values like "Foo Bar" or "foo--bar" past copier.yml validation.
_SLUG_NAME = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")

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

# Specific stub files (relative POSIX paths, anchored at ROOT) that need
# canonical-name rewriting even though their suffix isn't in TEXT_SUFFIXES.
# Use an explicit allowlist instead of broadening TEXT_SUFFIXES with `.example`,
# so future `.example` files (e.g. third-party config samples) aren't silently
# mutated. **Maintenance contract:** if you rename or relocate one of the listed
# stubs, update the corresponding entry below; otherwise the rewrite will
# silently no-op for the moved file. Symlinked entries are explicitly rejected
# in `_should_scan` so this constant can never cause writes outside ROOT.
#
# **Why hard-coded POSIX strings (not Path objects):** the matching key in
# `_should_scan` is `path.relative_to(ROOT).as_posix()` — already a POSIX
# string, so storing strings here keeps the comparison cheap, cross-platform
# safe (Windows paths are normalized via `as_posix()` before comparison), and
# prevents a "fix" that introduces `Path` objects + `resolve()`, which would
# silently re-enable the symlink-escape risk this module guards against.
EXAMPLE_FILE_ALLOWLIST = frozenset(
    {
        "ops/service.yaml.example",
    }
)

# Do not rewrite this script's own string literals (canonical default names).
# copier.yml documents ProjectTemplate paths; rewriting corrupts comments and causes noisy updates.
# .copier-answers.yml holds _src_path URLs that may contain project-template substrings.
SKIP_REWRITE_FILES = frozenset(
    {
        "scripts/copier_post_copy.py",
        "copier.yml",
        ".copier-answers.yml",
        ".claude/pitfalls-hub.json",  # hub_path intentionally references template-repo (hub-spoke)
    }
)


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
    """Read `.copier-answers.yml` and return the project-identity subset
    (`project_name`, `project_key`, `package_name`) as a string map.

    Falls back to a hand-rolled key/value parser when PyYAML isn't
    importable in the destination environment, and raises on non-mapping
    YAML to fail loud rather than silently no-op.
    """
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
    # Mirror copier.yml's `project_name` validator so an edited or legacy
    # `.copier-answers.yml` cannot smuggle a non-slug value (e.g. "Foo Bar",
    # "foo--bar", "Foo") past the post-copy hook. project_name is written
    # verbatim into ops/service.yaml `repo_id`, which workstation-ops keys on.
    if not _SLUG_NAME.fullmatch(project_name):
        raise ValueError(
            "copier_post_copy: project_name must be a PEP 503 / repo-slug "
            "(lowercase letters and digits separated by single hyphens or "
            f"underscores, e.g. 'alpaca-trading'); got {project_name!r}"
        )


def _should_scan(path: Path) -> bool:
    """Return True iff ``path`` is a regular file inside ROOT that should be
    rewritten by ``_rewrite_tree``.

    Order is load-bearing: directories and symlinks are rejected first
    (defense against `_rewrite_tree` mutating files outside the destination
    project root), THEN ROOT containment is enforced lexically (no
    ``resolve()`` so symlinks can't redirect us out of tree), and only then
    do the cheap name/suffix fast paths and the explicit
    ``EXAMPLE_FILE_ALLOWLIST`` fallback run.
    """
    if path.is_dir():
        return False
    # Reject symlinks for *all* scan paths, but especially for the explicit
    # EXAMPLE_FILE_ALLOWLIST entries: a symlinked `ops/service.yaml.example`
    # would otherwise pass the lexical relative_to check and cause
    # `_rewrite_tree` to rewrite the symlink target — potentially mutating
    # files outside the repo (very bad on `copier update`).
    if path.is_symlink():
        return False
    # Enforce ROOT containment FIRST (before the suffix/name fast paths),
    # otherwise an out-of-tree non-symlink text file like `/tmp/foo.py` or
    # `/tmp/Dockerfile` would slip through and `_rewrite_tree` would mutate
    # it. Avoid resolve() so the lexical comparison stays cheap and stable.
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False
    # Reject non-regular files (FIFOs, device nodes, sockets, hard-link-to-
    # device, etc.). `_rewrite_tree` reads/writes via Path.read_text /
    # write_text; calling that on a FIFO or character device would block
    # forever or corrupt unrelated state. Only regular files are safe.
    # (Symlinks were already rejected above; `is_file()` follows symlinks,
    # so the order of these two checks must remain symlink → relative_to →
    # is_file.) See Qodo PR #86 follow-up.
    if not path.is_file():
        return False
    name = path.name
    if name in TEXT_NAMES:
        return True
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return rel.as_posix() in EXAMPLE_FILE_ALLOWLIST


def _patch_pyproject(text: str, project_name: str, package_name: str) -> str:
    """Rewrite the canonical ``project-template`` / ``project_template``
    identifiers inside ``pyproject.toml`` text to the rendered values.

    Kept separate from :func:`_rewrite_tree`'s blanket substitution because
    a new ``package_name`` may contain ``project_template`` as a substring,
    which would corrupt unrelated TOML values.
    """

    def esc_toml_str(s: str) -> str:
        """Return ``s`` escaped for safe inclusion in a TOML basic string."""
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
    """Return True for directory names that ``_rewrite_tree`` must skip
    (vendor/build artefacts that should never be string-rewritten)."""
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
    """Walk ``ROOT`` and rewrite the template's canonical identifiers
    (``project-template``, ``project_template``, ``ProjectTemplate``,
    vault path) to the rendered project's values.

    Skips files rejected by :func:`_should_scan` (directories, symlinks,
    non-regular files, out-of-tree paths, and files whose extension is
    not in ``TEXT_SUFFIXES`` / ``TEXT_NAMES`` / ``EXAMPLE_FILE_ALLOWLIST``).
    ``pyproject.toml`` is handled separately by :func:`_patch_pyproject`.
    """
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
    """Entry point for the Copier post-copy hook.

    Validates the rendered ``.copier-answers.yml``, patches
    ``pyproject.toml`` (via :func:`_patch_pyproject`), rewrites the
    canonical template identifiers across the destination tree (via
    :func:`_rewrite_tree`), and relocates / merges any
    ``ProjectTemplate``-named directories. Returns a POSIX exit code: 0
    on success, 1 on transient I/O failure, 2 on validation failure.
    """
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
