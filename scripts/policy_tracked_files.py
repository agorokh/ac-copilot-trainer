#!/usr/bin/env python3
"""Secret scan every tracked path with a Windows-safe Python entrypoint."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

POSIX_BATCH_SIZE = 100
POSIX_MAX_ARG_CHARS = 24_000
WINDOWS_BATCH_SIZE = 25
WINDOWS_MAX_ARG_CHARS = 4_000
WINDOWS_COMMAND_HEADROOM = 128
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
_RAW_SECRET_KEYS = frozenset({"secret", "secret_value", "raw_secret", "value"})


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    raw = result.stdout.split(b"\0")
    return [
        path
        for chunk in raw
        if (path := chunk.decode("utf-8", errors="surrogateescape")) and path != ".secrets.baseline"
    ]


def _batches(
    items: list[str],
    size: int | None = None,
    max_chars: int | None = None,
) -> list[list[str]]:
    if size is None:
        size = WINDOWS_BATCH_SIZE if sys.platform == "win32" else POSIX_BATCH_SIZE
    if max_chars is None:
        max_chars = WINDOWS_MAX_ARG_CHARS if sys.platform == "win32" else POSIX_MAX_ARG_CHARS
    batches: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for item in items:
        item_chars = _argument_chars(item)
        if item_chars > max_chars:
            raise ValueError(
                f"tracked path exceeds the platform argv budget ({item_chars}>{max_chars}): {item}"
            )
        if current and (len(current) >= size or current_chars + item_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)
    return batches


def _argument_chars(value: str) -> int:
    chars = len(value) + 1
    if sys.platform == "win32" and (any(char.isspace() for char in value) or '"' in value):
        chars += 2 + value.count('"')
    return chars


def _file_arg_budget(baseline: Path) -> int:
    limit = WINDOWS_MAX_ARG_CHARS if sys.platform == "win32" else POSIX_MAX_ARG_CHARS
    base_cmd = [
        sys.executable,
        "-m",
        "detect_secrets.pre_commit_hook",
        "--baseline",
        str(baseline),
    ]
    headroom = WINDOWS_COMMAND_HEADROOM if sys.platform == "win32" else 0
    return limit - sum(_argument_chars(arg) for arg in base_cmd) - headroom


def _audit_baseline(baseline: Path) -> list[str]:
    try:
        data = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f".secrets.baseline is not valid JSON: {exc}"]
    results = data.get("results")
    if not isinstance(results, dict):
        return [".secrets.baseline missing object 'results'"]
    errors: list[str] = []
    for filename, findings in results.items():
        if not isinstance(filename, str) or not isinstance(findings, list):
            errors.append(".secrets.baseline results must map filenames to finding lists")
            continue
        for index, finding in enumerate(findings):
            label = f"{filename}[{index}]"
            if not isinstance(finding, dict):
                errors.append(f"{label} is not an object")
                continue
            raw_keys = sorted(_RAW_SECRET_KEYS.intersection(finding))
            if raw_keys:
                errors.append(f"{label} contains raw secret field(s): {', '.join(raw_keys)}")
            hashed = finding.get("hashed_secret")
            if not isinstance(hashed, str) or _HASH_RE.fullmatch(hashed) is None:
                errors.append(f"{label} missing 40-character hashed_secret")
            if finding.get("filename") != filename:
                errors.append(f"{label} filename does not match its results key")
    return errors


def _run_detect_secrets(root: Path, baseline: Path, files: list[str]) -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "detect_secrets.pre_commit_hook",
            "--baseline",
            str(baseline),
            *files,
        ],
        cwd=root,
    )
    return result.returncode


def _redact_baseline_hashes(value: object) -> object:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, child in value.items():
            if key == "hashed_secret":
                out["baseline_hash"] = "redacted"
            elif key == "type":
                out["baseline_type"] = "redacted"
            else:
                out[key] = _redact_baseline_hashes(child)
        return out
    if isinstance(value, list):
        return [_redact_baseline_hashes(child) for child in value]
    return value


def _scan_sanitized_baseline(root: Path, baseline: Path) -> int:
    data = json.loads(baseline.read_text(encoding="utf-8"))
    sanitized = _redact_baseline_hashes(data)
    body = json.dumps(sanitized, indent=2, sort_keys=True) + "\n"
    with tempfile.TemporaryDirectory(prefix="ac-copilot-baseline-scan-") as tmp_dir:
        scan_path = Path(tmp_dir) / ".secrets.baseline"
        scan_path.write_text(body, encoding="utf-8")
        return _run_detect_secrets(root, baseline, [str(scan_path)])


def main() -> int:
    root = _repo_root()
    files = _tracked_files(root)
    baseline = root / ".secrets.baseline"
    baseline_errors = _audit_baseline(baseline)
    if baseline_errors:
        for error in baseline_errors:
            print(f"policy_tracked_files: {error}", file=sys.stderr)
        return 2
    baseline_scan = _scan_sanitized_baseline(root, baseline)
    if baseline_scan != 0:
        return baseline_scan
    if not files:
        return 0
    try:
        batches = _batches(files, max_chars=_file_arg_budget(baseline))
    except ValueError as exc:
        print(f"policy_tracked_files: {exc}", file=sys.stderr)
        return 2
    for batch in batches:
        scan_result = _run_detect_secrets(root, baseline, batch)
        if scan_result != 0:
            return scan_result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
