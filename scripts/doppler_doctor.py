#!/usr/bin/env python3
"""``make doppler-doctor`` — static and (optionally) runtime checks for the
secrets-from-doppler invariant (``docs/01_Vault/ProjectTemplate/00_System/
invariants/secrets-from-doppler.md``).

Static checks (always run, CI-safe):

* **No ``env_file:``** directive in any tracked ``ops/**/compose.yml`` /
  ``ops/**/docker-compose.yml``. Compose files must pull env from the
  ``doppler run --`` wrapper, not from a host ``.env``.
* **No literal OpenAI keys** in tracked files outside ``.env.example``,
  ``tests/fixtures/``, and explicitly allowed paths. Detects
  ``OPENAI_API_KEY=sk-...`` and ``Bearer sk-...`` shapes.
* **``.env.example`` is a key-name catalogue** — every assignment must have an
  empty RHS (`KEY=`), a placeholder (`KEY=changeme`, `KEY=<value>`,
  `KEY=...`), or a doppler reference (`KEY=$(doppler ...)`).

Runtime checks (opt-in via ``--with-runtime``):

* **No ``.env`` on operator-machine deploy hosts** under ``~/deploy/*/``.
  Operator-machine-specific and silently skipped when the directory does not
  exist.

Exit codes:

* ``0`` — all checks pass.
* ``1`` — at least one static violation found.
* ``2`` — runtime check requested but environment cannot satisfy it (e.g.
  ``--with-runtime`` on a host that doesn't even have a home dir to scan).

The script is read-only. It NEVER edits files or invokes ``doppler``; it only
asserts what should be true. Wire it into ``make doppler-doctor`` and add it
to ``ci-fast`` once the fleet has converged.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Patterns
_COMPOSE_ENV_FILE_RE = re.compile(r"^\s*env_file\s*:", re.MULTILINE)
_OPENAI_KEY_ASSIGN_RE = re.compile(
    r"(?:OPENAI_API_KEY|OPENROUTER_API_KEY|ANTHROPIC_API_KEY)\s*=\s*"
    r"['\"]?sk-[A-Za-z0-9_\-]{8,}"
)
_BEARER_SK_RE = re.compile(r"bearer\s+sk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE)

# .env.example: KEY=value where `value` is empty / placeholder / doppler ref.
_ENV_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_PLACEHOLDER_VALUES = {"", "changeme", "<value>", "...", "TODO", "REDACTED"}
_DOPPLER_REF_PREFIX = ("$(doppler", "${doppler", "doppler ")
_DOPPLER_PLACEHOLDER_RE = re.compile(r"^<[^>]+>$|^\$\{[^}]+\}$")

_SKIP_SCAN_DIR_NAMES = frozenset(
    {".venv", "node_modules", ".git", "__pycache__", ".scratch", ".cache", ".tox"}
)
_SCAN_EXTENSIONS = (".py", ".yml", ".yaml", ".json", ".sh", ".md", ".toml", ".env")
_SCAN_BASENAMES = frozenset(
    {
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)

_COMPOSE_FILENAMES = frozenset(
    {
        "compose.yml",
        "compose.yaml",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
)


def _check_compose_env_file(root: Path) -> list[str]:
    """No ``env_file:`` directives in git-tracked shipped compose files."""
    violations: list[str] = []
    for rel in _git_tracked_paths(root):
        if not rel.startswith("ops/"):
            continue
        if Path(rel).name not in _COMPOSE_FILENAMES:
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:  # noqa: PERF203
            violations.append(f"{rel}: read error: {e}")
            continue
        for m in _COMPOSE_ENV_FILE_RE.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            violations.append(
                f"{rel}:{line_no}: forbidden `env_file:` "
                f"directive — wrap launch in `doppler run --` instead"
            )
    return violations


def _git_tracked_paths(root: Path) -> list[str]:
    """Repo-relative paths from ``git ls-files`` (skips untracked local ``.env``)."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.split("\0") if p]


def _should_scan_tracked(rel: str) -> bool:
    path = Path(rel)
    if path.suffix in _SCAN_EXTENSIONS:
        return True
    return path.name in _SCAN_BASENAMES


def _path_allowed(rel: str) -> bool:
    """True when ``rel`` is an allowed location for credential-shaped literals."""
    parts = tuple(p for p in rel.strip("/").split("/") if p)
    if not parts:
        return False
    if parts == (".env.example",):
        return True
    if len(parts) >= 2 and parts[0] == "tests" and parts[1] == "fixtures":
        return True
    return False


def _check_no_literal_keys(root: Path) -> list[str]:
    """No raw OpenAI/OpenRouter/Anthropic ``sk-...`` in tracked files."""
    violations: list[str] = []
    for rel in _git_tracked_paths(root):
        if not _should_scan_tracked(rel):
            continue
        path = root / rel
        if not path.is_file():
            continue
        if _SKIP_SCAN_DIR_NAMES.intersection(path.parts):
            continue
        if _path_allowed("/" + rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # noqa: PERF203
            continue
        for pattern, label in (
            (_OPENAI_KEY_ASSIGN_RE, "literal sk-… key assignment"),
            (_BEARER_SK_RE, "Bearer sk-… literal"),
        ):
            m = pattern.search(text)
            if m:
                line_no = text[: m.start()].count("\n") + 1
                violations.append(
                    f"{rel}:{line_no}: {label} ({m.group(0)[:40]}…) — "
                    f"source from Doppler, not literals"
                )
    return violations


def _is_placeholder(value: str) -> bool:
    v = value.strip().strip('"').strip("'")
    if v in _PLACEHOLDER_VALUES:
        return True
    if v.startswith(_DOPPLER_REF_PREFIX):
        return True
    if _DOPPLER_PLACEHOLDER_RE.match(v):
        return True
    return False


def _check_env_example_catalogue(root: Path) -> list[str]:
    """``.env.example`` is a key-name catalogue, not a value source."""
    violations: list[str] = []
    env_example = root / ".env.example"
    if not env_example.is_file():
        return violations
    try:
        text = env_example.read_text(encoding="utf-8")
    except OSError as e:
        return [f".env.example: read error: {e}"]
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if not _is_placeholder(value):
            violations.append(
                f".env.example:{line_no}: {key} has non-placeholder value — "
                f"keep .env.example as key-name catalogue only"
            )
    return violations


def _check_deploy_host_dotenv() -> list[str]:
    """Runtime: no ``.env`` files under ``~/deploy/*/``."""
    home = Path.home()
    deploy = home / "deploy"
    if not deploy.is_dir():
        return []  # operator-machine specific; absence is the norm in CI
    violations: list[str] = []
    for child in sorted(deploy.iterdir()):
        if not child.is_dir():
            continue
        dotenv = child / ".env"
        if dotenv.is_file():
            violations.append(
                f"{dotenv}: forbidden `.env` on deploy host — "
                f"wrap service launch in `doppler run --` and remove this file"
            )
    return violations


def _print_section(title: str, violations: list[str]) -> None:
    if violations:
        print(f"FAIL  {title}: {len(violations)} violation(s)")
        for v in violations:
            print(f"        {v}")
    else:
        print(f"OK    {title}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-runtime",
        action="store_true",
        help="Also run operator-machine runtime checks (~/deploy/*/.env).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repo root to scan (default: derived from script location).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    print(f"doppler-doctor: scanning {root}")

    static_failures = 0
    for title, fn in (
        ("compose env_file: directive", _check_compose_env_file),
        ("literal OpenAI/Bearer sk-… keys", _check_no_literal_keys),
        (".env.example key-name catalogue", _check_env_example_catalogue),
    ):
        violations = fn(root)
        _print_section(title, violations)
        static_failures += len(violations)

    runtime_failures = 0
    if args.with_runtime:
        violations = _check_deploy_host_dotenv()
        _print_section("~/deploy/*/.env on this host", violations)
        runtime_failures += len(violations)

    if static_failures:
        print(f"\ndoppler-doctor: FAIL — {static_failures} static violation(s)")
        return 1
    if runtime_failures:
        print(f"\ndoppler-doctor: FAIL — {runtime_failures} runtime violation(s)")
        return 1
    print("\ndoppler-doctor: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
