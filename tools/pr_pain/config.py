"""Read the PR pain workflow config without a runtime PyYAML dependency."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIST_KEYS = frozenset({"enabled_repos", "dry_run_repos", "extra_bot_logins"})
PainConfig = dict[str, frozenset[str]]


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _parse_inline_list(raw_value: str, *, line_no: int) -> list[str]:
    value = raw_value.strip()
    if value == "[]":
        return []
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError(f"line {line_no}: expected an inline list like [item] or a block list")
    body = value[1:-1].strip()
    if not body:
        return []
    return [item for item in (_clean_scalar(part) for part in body.split(",")) if item]


def parse_pain_config(text: str) -> PainConfig:
    """Parse the simple top-level list schema used by pr-pain-config.yml.

    This deliberately supports only the config shape owned by the workflow:
    top-level list keys with either ``key: []`` / ``key: [a, b]`` or block list
    values. Unknown keys are ignored so future config can be added safely.
    """
    parsed: dict[str, list[str]] = {key: [] for key in _LIST_KEYS}
    current_key: str | None = None

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line)
        if not line.strip():
            continue

        if line[0].isspace():
            if current_key is None:
                continue
            item = line.strip()
            if not item.startswith("-"):
                raise ValueError(f"line {line_no}: expected '- value' list item")
            value = _clean_scalar(item[1:])
            if value:
                parsed[current_key].append(value)
            continue

        if ":" not in line:
            raise ValueError(f"line {line_no}: expected 'key: value'")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if key not in _LIST_KEYS:
            current_key = None
            continue
        if raw_value:
            parsed[key] = _parse_inline_list(raw_value, line_no=line_no)
            current_key = None
        else:
            parsed[key] = []
            current_key = key

    return {key: frozenset(values) for key, values in parsed.items()}


def load_pain_config(config_path: str | Path = ".github/pr-pain-config.yml") -> PainConfig:
    path = Path(config_path)
    if not path.is_file():
        return {key: frozenset() for key in _LIST_KEYS}
    return parse_pain_config(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit GitHub Actions outputs for PR pain allowlist state."
    )
    parser.add_argument("--config", default=".github/pr-pain-config.yml")
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)

    try:
        config = load_pain_config(args.config)
    except ValueError as exc:
        print(f"::error::Invalid PR pain config: {exc}", file=sys.stderr)
        return 1

    print(f"enabled={'true' if args.repo in config['enabled_repos'] else 'false'}")
    print(f"dry_run={'true' if args.repo in config['dry_run_repos'] else 'false'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via workflow.
    raise SystemExit(main())
