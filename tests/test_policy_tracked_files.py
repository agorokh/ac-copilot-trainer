from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "policy_tracked_files.py"
SPEC = importlib.util.spec_from_file_location("policy_tracked_files", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
policy_tracked_files = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy_tracked_files)


def test_tracked_files_filters_empty_git_ls_files_sentinel(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        assert args == ["git", "ls-files", "-z"]
        assert cwd == tmp_path
        assert capture_output is True
        assert check is True
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"src/app.py\0.secrets.baseline\0\0",
        )

    monkeypatch.setattr(policy_tracked_files.subprocess, "run", fake_run)

    assert policy_tracked_files._tracked_files(tmp_path) == ["src/app.py"]


def test_batches_respect_count_and_character_budgets() -> None:
    files = ["a" * 10, "b" * 10, "c" * 10]

    assert policy_tracked_files._batches(files, size=2, max_chars=100) == [
        [files[0], files[1]],
        [files[2]],
    ]
    assert policy_tracked_files._batches(files, size=100, max_chars=22) == [
        [files[0], files[1]],
        [files[2]],
    ]


def test_batches_keep_single_path_that_exceeds_character_budget() -> None:
    long_file = "deep/" + ("x" * 64)

    assert policy_tracked_files._batches([long_file], max_chars=10) == [[long_file]]
