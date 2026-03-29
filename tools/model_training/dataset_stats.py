"""Lightweight JSONL training set statistics (stdlib only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def jsonl_stats(path: Path) -> dict[str, Any]:
    """Count lines and SFT-shaped records (must have non-empty ``messages`` list).

    ``parse_errors`` counts only :class:`json.JSONDecodeError`. Lines that parse as
    JSON but are not JSON objects are counted in ``non_dict_json_lines``.
    """
    lines_total = 0
    non_empty_lines = 0
    valid_json = 0
    with_messages = 0
    parse_errors = 0
    non_dict_json_lines = 0

    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            lines_total += 1
            line = raw_line.strip()
            if not line:
                continue
            non_empty_lines += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if not isinstance(obj, dict):
                non_dict_json_lines += 1
                continue
            valid_json += 1
            msgs = obj.get("messages")
            if isinstance(msgs, list) and len(msgs) > 0:
                with_messages += 1

    return {
        "path": str(path),
        "lines_total": lines_total,
        "non_empty_lines": non_empty_lines,
        "valid_json_objects": valid_json,
        "records_with_messages": with_messages,
        "parse_errors": parse_errors,
        "non_dict_json_lines": non_dict_json_lines,
    }


def summarize_dir(output_dir: Path, *, glob: str = "*.jsonl") -> list[dict[str, Any]]:
    """Run :func:`jsonl_stats` on each matching file under ``output_dir``."""
    if not output_dir.is_dir():
        return []
    return [jsonl_stats(p) for p in sorted(output_dir.glob(glob)) if p.is_file()]


def main(argv: list[str] | None = None) -> int:
    """Print JSON stats for a single ``--jsonl`` file or every ``*.jsonl`` under ``--dir``."""
    parser = argparse.ArgumentParser(description="Report basic stats on SFT JSONL files.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--jsonl",
        type=Path,
        help="Single JSONL file to analyze",
    )
    group.add_argument(
        "--dir",
        type=Path,
        help="Directory of JSONL files (default glob *.jsonl)",
    )
    args = parser.parse_args(argv)
    if args.jsonl is not None:
        print(json.dumps(jsonl_stats(args.jsonl), indent=2))
        return 0
    assert args.dir is not None
    rows = summarize_dir(args.dir)
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
