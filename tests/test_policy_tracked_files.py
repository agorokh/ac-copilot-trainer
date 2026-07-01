from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "policy_tracked_files.py"
SPEC = importlib.util.spec_from_file_location("policy_tracked_files", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
policy_tracked_files = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy_tracked_files)


def test_repo_root_is_anchored_to_script_location(monkeypatch) -> None:
    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        check: bool,
        text: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert args == ["git", "rev-parse", "--show-toplevel"]
        assert cwd == REPO_ROOT
        assert capture_output is True
        assert check is True
        assert text is True
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{REPO_ROOT}\n")

    monkeypatch.setattr(policy_tracked_files.subprocess, "run", fake_run)

    assert policy_tracked_files._repo_root() == REPO_ROOT


def test_tracked_files_filters_empty_sentinel_and_baseline(
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


def test_batches_reject_single_path_that_exceeds_character_budget() -> None:
    long_file = "deep/" + ("x" * 64)

    with pytest.raises(ValueError, match="tracked path exceeds"):
        policy_tracked_files._batches([long_file], max_chars=10)


def test_batches_use_smaller_windows_defaults(monkeypatch) -> None:
    monkeypatch.setattr(policy_tracked_files.sys, "platform", "win32")
    files = [f"{i}-" + ("x" * 300) for i in range(30)]

    batches = policy_tracked_files._batches(files)

    assert len(batches) > 1
    assert all(len(batch) <= policy_tracked_files.WINDOWS_BATCH_SIZE for batch in batches)
    assert all(
        sum(policy_tracked_files._argument_chars(item) for item in batch)
        <= policy_tracked_files.WINDOWS_MAX_ARG_CHARS
        for batch in batches
    )


def test_windows_argument_budget_counts_quoted_paths(monkeypatch) -> None:
    monkeypatch.setattr(policy_tracked_files.sys, "platform", "win32")
    path = "docs/with space/report.md"

    assert policy_tracked_files._argument_chars(path) > len(path) + 1
    assert (
        policy_tracked_files._file_arg_budget(Path("C:/repo with space/.secrets.baseline"))
        < policy_tracked_files.WINDOWS_MAX_ARG_CHARS
    )


def test_audit_baseline_accepts_hashed_findings(tmp_path: Path) -> None:
    baseline = tmp_path / ".secrets.baseline"
    baseline.write_text(
        json.dumps(
            {
                "results": {
                    "src/app.py": [
                        {
                            "filename": "src/app.py",
                            "hashed_secret": "a" * 40,
                            "type": "Secret",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert policy_tracked_files._audit_baseline(baseline) == []


def test_audit_baseline_rejects_raw_or_malformed_findings(tmp_path: Path) -> None:
    baseline = tmp_path / ".secrets.baseline"
    raw_key = "".join(("sec", "ret"))
    hashed_key = f"hashed_{raw_key}"
    baseline.write_text(
        json.dumps(
            {
                "results": {
                    "src/app.py": [
                        {
                            "filename": "src/app.py",
                            hashed_key: "not-a-sha1",
                            raw_key: "plain-text-fixture",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    errors = policy_tracked_files._audit_baseline(baseline)

    assert any("raw secret" in error for error in errors)
    assert any("hashed_secret" in error for error in errors)


def test_scan_baseline_file_uses_real_path_with_metadata_exclusion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline = tmp_path / ".secrets.baseline"
    calls: list[tuple[Path, Path, list[str], str | None]] = []

    def fake_run_detect_secrets(
        root: Path,
        baseline_arg: Path,
        files: list[str],
        *,
        exclude_lines: str | None = None,
    ) -> int:
        calls.append((root, baseline_arg, files, exclude_lines))
        return 0

    monkeypatch.setattr(
        policy_tracked_files,
        "_run_detect_secrets",
        fake_run_detect_secrets,
    )

    assert policy_tracked_files._scan_baseline_file(tmp_path, baseline) == 0
    assert calls == [
        (
            tmp_path,
            baseline,
            [".secrets.baseline"],
            policy_tracked_files.BASELINE_METADATA_EXCLUDE_LINES,
        )
    ]
