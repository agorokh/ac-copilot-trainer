"""Tests for ``scripts/doppler_doctor.py``.

Verifies the static checks behind the ``secrets-from-doppler`` invariant:

* ``env_file:`` directive in shipped ``ops/**/compose.yml`` → violation.
* Literal ``OPENAI_API_KEY=sk-...`` / ``Bearer sk-...`` in tracked source → violation.
* ``.env.example`` with non-placeholder values → violation.

Also verifies the script (a) returns 0 on a clean tree and (b) returns 1 on
each crafted violation, without touching the real repo root.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "doppler_doctor.py"

# Built at runtime so this test module does not trip doppler-doctor on itself.
_SAMPLE_SK = "sk-" + ("x" * 20)  # pragma: allowlist secret
_SAMPLE_PROJ = "sk-proj-" + ("x" * 20)  # pragma: allowlist secret


def _git_add(repo: Path, *paths: str) -> None:
    subprocess.run(["git", "add", *paths], cwd=repo, check=True)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    """A minimal repo skeleton that satisfies every check."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "ops" / "docker").mkdir(parents=True)
    (tmp_path / "ops" / "docker" / "compose.yml").write_text(
        "services:\n  app:\n    image: alpine\n    environment:\n      - GREETING=hello\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text(
        "# Catalogue only.\n"
        "OPENAI_API_KEY=\n"
        "DIAL_API_KEY=changeme\n"
        "ANTHROPIC_API_KEY=<value>\n"
        "WEBHOOK_URL=$(doppler --plain --silent secrets get WEBHOOK_URL)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_non_git_root_fails_closed(tmp_path: Path) -> None:
    """When ``git ls-files`` cannot run, the doctor must not report OK."""
    proc = _run(tmp_path)
    assert proc.returncode == 1
    assert "git ls-files failed" in proc.stdout + proc.stderr


def test_clean_repo_passes(clean_repo: Path) -> None:
    proc = _run(clean_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "doppler-doctor: OK" in proc.stdout


def test_untracked_compose_env_file_is_ignored(clean_repo: Path) -> None:
    """Untracked local compose scratch must not fail the doctor."""
    scratch = clean_repo / "ops" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "compose.yml").write_text(
        "services:\n  app:\n    image: alpine\n    env_file:\n      - .env\n",
        encoding="utf-8",
    )
    proc = _run(clean_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_env_file_in_compose_fails(clean_repo: Path) -> None:
    (clean_repo / "ops" / "docker" / "compose.yml").write_text(
        "services:\n  app:\n    image: alpine\n    env_file:\n      - .env\n",
        encoding="utf-8",
    )
    _git_add(clean_repo, "ops/docker/compose.yml")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "forbidden `env_file:` directive" in proc.stdout


def test_quoted_openai_key_fails(clean_repo: Path) -> None:
    (clean_repo / "src").mkdir()
    (clean_repo / "src" / "config.py").write_text(
        f'OPENAI_API_KEY="{_SAMPLE_PROJ}"\n',
        encoding="utf-8",
    )
    _git_add(clean_repo, "src/config.py")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "literal sk-…" in proc.stdout


def test_literal_openai_key_fails(clean_repo: Path) -> None:
    (clean_repo / "src").mkdir()
    (clean_repo / "src" / "config.py").write_text(
        f'KEY = "OPENAI_API_KEY={_SAMPLE_PROJ}"\n',
        encoding="utf-8",
    )
    _git_add(clean_repo, "src/config.py")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "literal sk-…" in proc.stdout


def test_bearer_sk_case_insensitive_fails(clean_repo: Path) -> None:
    (clean_repo / "scripts").mkdir()
    (clean_repo / "scripts" / "broken.sh").write_text(
        f'curl -H "authorization: bearer {_SAMPLE_SK}" https://example\n',
        encoding="utf-8",
    )
    _git_add(clean_repo, "scripts/broken.sh")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "Bearer sk-…" in proc.stdout


def test_bearer_sk_fails(clean_repo: Path) -> None:
    (clean_repo / "scripts").mkdir()
    (clean_repo / "scripts" / "broken.sh").write_text(
        f'AUTH="Bearer {_SAMPLE_SK}"\n',
        encoding="utf-8",
    )
    _git_add(clean_repo, "scripts/broken.sh")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "Bearer sk-…" in proc.stdout


def test_env_example_with_real_value_fails(clean_repo: Path) -> None:
    (clean_repo / ".env.example").write_text(
        f"DIAL_API_KEY={_SAMPLE_PROJ}\n",
        encoding="utf-8",
    )
    _git_add(clean_repo, ".env.example")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    # The .env.example check fires first; the sk-… check may also fire,
    # but the catalogue assertion is what we care about for this test.
    assert "key-name catalogue only" in proc.stdout or "literal sk-…" in proc.stdout


def test_allowlist_does_not_match_path_fragments(clean_repo: Path) -> None:
    """Substring false positives (e.g. ``docs_backup``) must not bypass scanning."""
    (clean_repo / "tmp" / "docs_backup").mkdir(parents=True)
    (clean_repo / "tmp" / "docs_backup" / "leak.py").write_text(
        f"OPENAI_API_KEY={_SAMPLE_SK}\n",
        encoding="utf-8",
    )
    _git_add(clean_repo, "tmp/docs_backup/leak.py")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "literal sk-…" in proc.stdout


def test_sk_in_tests_outside_fixtures_fails(clean_repo: Path) -> None:
    (clean_repo / "tests" / "unit").mkdir(parents=True)
    (clean_repo / "tests" / "unit" / "leak.py").write_text(
        f"OPENAI_API_KEY={_SAMPLE_SK}\n",
        encoding="utf-8",
    )
    _git_add(clean_repo, "tests/unit/leak.py")
    proc = _run(clean_repo)
    assert proc.returncode == 1
    assert "literal sk-…" in proc.stdout


def test_skip_dirs_ignore_clone_path_not_repo_relative(tmp_path: Path) -> None:
    """``.cache`` in the absolute clone path must not skip tracked in-repo files."""
    repo = tmp_path / ".cache" / "myproject"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "config.py").write_text(
        f'OPENAI_API_KEY="{_SAMPLE_PROJ}"\n',
        encoding="utf-8",
    )
    (repo / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    proc = _run(repo)
    assert proc.returncode == 1
    assert "literal sk-…" in proc.stdout


def test_allowed_paths_are_skipped(clean_repo: Path) -> None:
    """sk-… patterns under ``tests/fixtures/`` should NOT fail."""
    (clean_repo / "tests" / "fixtures").mkdir(parents=True)
    (clean_repo / "tests" / "fixtures" / "sample.py").write_text(
        f"OPENAI_API_KEY={_SAMPLE_SK}  # noqa: example only\n",
        encoding="utf-8",
    )
    _git_add(clean_repo, "tests/fixtures/sample.py")
    proc = _run(clean_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_real_repo_root_passes() -> None:
    """The actual template-repo must pass its own check."""
    proc = _run(REPO_ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
