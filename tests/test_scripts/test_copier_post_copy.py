"""Tests for ``scripts/copier_post_copy.py`` merge helpers."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest


def _load_copier_post_copy() -> types.ModuleType:
    """Import `scripts/copier_post_copy.py` as an isolated module for testing."""
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "copier_post_copy.py"
    spec = importlib.util.spec_from_file_location("copier_post_copy", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_relocate_or_merge_moves_when_destination_missing(tmp_path: Path) -> None:
    """When the destination tree doesn't exist, the source tree is moved wholesale."""
    mod = _load_copier_post_copy()
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "a").mkdir(parents=True)
    (src / "a" / "f.txt").write_text("x", encoding="utf-8")
    mod._relocate_or_merge_tree(active=True, src=src, dst=dst)
    assert not src.exists()
    assert (dst / "a" / "f.txt").read_text(encoding="utf-8") == "x"


def test_merge_missing_files_only_skips_existing(tmp_path: Path) -> None:
    """New files from template are copied; existing destination files are not overwritten."""
    mod = _load_copier_post_copy()
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "nested").mkdir(parents=True)
    (src / "nested" / "new.md").write_text("from-template", encoding="utf-8")
    (dst / "nested").mkdir(parents=True)
    (dst / "nested" / "existing.md").write_text("user-owned", encoding="utf-8")
    mod._merge_missing_files_only(src, dst)
    assert (dst / "nested" / "new.md").read_text(encoding="utf-8") == "from-template"
    assert (dst / "nested" / "existing.md").read_text(encoding="utf-8") == "user-owned"


def _script_path() -> Path:
    """Return the absolute path to `scripts/copier_post_copy.py`."""
    return Path(__file__).resolve().parents[2] / "scripts" / "copier_post_copy.py"


def test_script_invalid_yaml_exits_nonzero(tmp_path: Path) -> None:
    """A malformed `.copier-answers.yml` must exit with code 1 (transient failure)."""
    (tmp_path / ".copier-answers.yml").write_text("{broken", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_script_path())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1


def test_script_incomplete_answers_exit_code(tmp_path: Path) -> None:
    """A `.copier-answers.yml` missing required keys must exit code 2 (validation failure)."""
    (tmp_path / ".copier-answers.yml").write_text(
        "project_name: foo\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(_script_path())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "missing" in r.stderr.lower()


def test_should_scan_uses_example_allowlist(tmp_path: Path, monkeypatch) -> None:
    """`.example` files are scanned only when explicitly allowlisted (not by suffix)."""
    mod = _load_copier_post_copy()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "ops").mkdir()
    allowed = tmp_path / "ops" / "service.yaml.example"
    allowed.write_text("repo_id: ac-copilot-trainer\n", encoding="utf-8")
    other = tmp_path / "third_party.example"
    other.write_text("verbatim\n", encoding="utf-8")
    env_example = tmp_path / ".env.example"
    env_example.write_text("KEY=value\n", encoding="utf-8")
    assert mod._should_scan(allowed) is True
    assert mod._should_scan(other) is False
    assert mod._should_scan(env_example) is False


def test_should_scan_allowlist_path_handling(tmp_path: Path, monkeypatch) -> None:
    """Allowlist matches the os.walk-style absolute path (script's real input shape)."""
    mod = _load_copier_post_copy()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "ops").mkdir()
    allowed = tmp_path / "ops" / "service.yaml.example"
    allowed.write_text("repo_id: ac-copilot-trainer\n", encoding="utf-8")
    # Absolute path under ROOT (same shape produced by os.walk(ROOT) in main()).
    assert mod._should_scan(Path(allowed)) is True
    # A path outside ROOT must not be rewritten (relative_to raises ValueError).
    outside = tmp_path.parent / "stray.example"
    outside.write_text("noop\n", encoding="utf-8")
    assert mod._should_scan(outside) is False
    # Regression: ROOT containment must be enforced *before* the TEXT_NAMES /
    # TEXT_SUFFIXES fast paths, so out-of-tree files whose name/suffix would
    # otherwise match (e.g. `/tmp/foo.py`, `/tmp/Dockerfile`) are still
    # rejected. Without this guard `_rewrite_tree` could silently mutate
    # files outside the destination project root.
    outside_py = tmp_path.parent / "stray.py"
    outside_py.write_text("x = 1\n", encoding="utf-8")
    assert mod._should_scan(outside_py) is False
    outside_dockerfile = tmp_path.parent / "Dockerfile"
    outside_dockerfile.write_text("FROM scratch\n", encoding="utf-8")
    assert mod._should_scan(outside_dockerfile) is False


def test_should_scan_rejects_non_regular_files(tmp_path: Path, monkeypatch) -> None:
    """`_should_scan` must reject non-regular files (FIFOs, device nodes,
    sockets) even when their name/suffix would otherwise match
    ``TEXT_NAMES`` / ``TEXT_SUFFIXES``. Reading or writing those via
    ``Path.read_text`` would block forever or corrupt unrelated state.

    Skips on platforms where ``os.mkfifo`` is unavailable (e.g. Windows).
    """
    import os

    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo not available on this platform")
    mod = _load_copier_post_copy()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    fifo = tmp_path / "Dockerfile"
    try:
        os.mkfifo(fifo)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"mkfifo unsupported on this platform: {exc!r}")
    assert fifo.exists()
    assert not fifo.is_file()
    assert mod._should_scan(fifo) is False


def test_should_scan_rejects_symlinks(tmp_path: Path, monkeypatch) -> None:
    """Symlinks are never scanned, even when their lexical path is allowlisted."""
    mod = _load_copier_post_copy()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "ops").mkdir()
    target = tmp_path.parent / "external_target.yaml"
    target.write_text("repo_id: ac-copilot-trainer\n", encoding="utf-8")
    link = tmp_path / "ops" / "service.yaml.example"
    # Some platforms (notably Windows without admin / Developer Mode) reject
    # symlink creation with OSError; skip rather than fail flakily there.
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unsupported on this platform: {exc!r}")
    # The lexical path matches the allowlist, but the symlink check must veto.
    assert link.is_symlink()
    assert mod._should_scan(link) is False
    # A symlinked .md (suffix-allowed) must also be rejected to avoid out-of-tree writes.
    md_target = tmp_path.parent / "external_doc.md"
    md_target.write_text("# stub\n", encoding="utf-8")
    md_link = tmp_path / "linked_doc.md"
    try:
        md_link.symlink_to(md_target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unsupported on this platform: {exc!r}")
    assert mod._should_scan(md_link) is False


def test_script_rejects_unsafe_project_key(tmp_path: Path) -> None:
    """A path-injection-style `project_key` must exit code 2 (validation failure)."""
    (tmp_path / ".copier-answers.yml").write_text(
        "project_name: foo\nproject_key: Bad/Key\npackage_name: foo_pkg\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(_script_path())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2


def test_slug_name_pattern_matches_copier_yml_validator() -> None:
    """Defense against drift between `_SLUG_NAME` (post-copy hook) and the
    `project_name.validator` regex in `copier.yml` (Qodo PR #86 finding).
    Both patterns are duplicated by design (Jinja vs Python contexts) so a
    test asserts the regex literal stays in sync.

    The match is whitespace- and quote-tolerant (Qodo round-9 follow-up):
    we parse `copier.yml` as YAML, extract the `project_name.validator`
    template, and search for `regex_search(<quote><pattern><quote>)` with
    a regex that allows either ``'`` or ``"`` quoting and arbitrary
    whitespace inside the call.
    """
    yaml = pytest.importorskip("yaml")
    mod = _load_copier_post_copy()
    repo_root = Path(__file__).resolve().parents[2]
    copier_yml = (repo_root / "copier.yml").read_text(encoding="utf-8")
    pattern = mod._SLUG_NAME.pattern
    parsed = yaml.safe_load(copier_yml)
    validator = parsed.get("project_name", {}).get("validator")
    assert isinstance(validator, str), (
        "copier.yml must declare `project_name.validator` as a string "
        f"(got {type(validator).__name__}); the slug-sync contract relies on it."
    )
    quoted = re.escape(pattern)
    sync_re = re.compile(
        rf"regex_search\(\s*['\"]{quoted}['\"]\s*\)",
    )
    assert sync_re.search(validator), (
        "copier.yml `project_name.validator` must call "
        f"`regex_search('{pattern}')` (or with double quotes / extra "
        "whitespace) so it stays in lockstep with "
        f"scripts.copier_post_copy._SLUG_NAME. Validator was: {validator!r}"
    )


def test_validate_answer_strings_rejects_non_slug_project_name() -> None:
    """Mirror of copier.yml `project_name` validator (CodeRabbit PR #86): an
    edited or legacy `.copier-answers.yml` cannot smuggle non-slug values
    past the post-copy hook, which writes `project_name` verbatim into
    ops/service.yaml `repo_id`."""
    mod = _load_copier_post_copy()
    for bad in ("Foo Bar", "Foo", "foo--bar", "-foo", "foo-", "foo/bar"):
        with pytest.raises(ValueError, match="project_name"):
            mod._validate_answer_strings(bad, "Foo", "foo")
    # Sanity: representative valid slugs must still pass.
    for ok in ("foo", "alpaca-trading", "foo_bar", "foo123", "a-b-c"):
        mod._validate_answer_strings(ok, "Foo", "foo")
