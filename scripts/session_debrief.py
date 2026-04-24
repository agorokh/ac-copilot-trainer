#!/usr/bin/env python3
"""Append one JSONL record for optional session debrief analytics (Stop hook).

Reads optional JSON from stdin (hook payload). Merges ``SESSION_DEBRIEF_*`` env vars when set:
``SESSION_DEBRIEF_FILES`` (JSON array), ``SESSION_DEBRIEF_CI``, ``SESSION_DEBRIEF_MISTAKES``,
``SESSION_DEBRIEF_PATTERNS`` (JSON array or plain string).

Each line is JSON with ``schema_version`` (see ``tools.process_miner.session_debrief_schema``).

Duplicate stdin payloads (e.g. hook retries) are skipped via ``hook_payload_hash``.

Always exits 0 so hooks never fail the session.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _schema_version() -> int:
    """Resolve schema version without failing the hook if ``tools`` is unavailable."""
    try:
        from tools.process_miner.session_debrief_schema import (  # noqa: E402
            SESSION_DEBRIEF_SCHEMA_VERSION,
        )

        return int(SESSION_DEBRIEF_SCHEMA_VERSION)
    except Exception:
        return 1


def _repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return _REPO_ROOT


def _load_env_json(name: str) -> object | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _read_stdin_safely() -> str:
    if sys.stdin.isatty():
        return ""
    try:
        return sys.stdin.read()
    except OSError:
        return ""


def _merge_session_debrief_env(record: dict[str, object]) -> None:
    for key in ("SESSION_DEBRIEF_CI", "SESSION_DEBRIEF_MISTAKES"):
        val = os.environ.get(key)
        if val:
            record[key.lower()] = val
    fj = _load_env_json("SESSION_DEBRIEF_FILES")
    if fj is not None:
        record["session_debrief_files"] = fj
    pj = _load_env_json("SESSION_DEBRIEF_PATTERNS")
    if pj is not None:
        record["session_debrief_patterns"] = pj


def _stdin_hash_and_hook(raw_stdin: str, record: dict[str, object]) -> str | None:
    if not raw_stdin.strip():
        return None
    stdin_hash = hashlib.sha256(raw_stdin.encode("utf-8", errors="replace")).hexdigest()
    record["hook_payload_hash"] = stdin_hash
    try:
        parsed = json.loads(raw_stdin)
    except json.JSONDecodeError:
        return stdin_hash
    if not isinstance(parsed, dict):
        return stdin_hash
    safe_hook: dict[str, object] = {}
    for k in ("event", "tool_name", "matcher"):
        if k in parsed:
            safe_hook[k] = parsed[k]
    if safe_hook:
        record["hook"] = safe_hook
    return stdin_hash


def _jsonl_file_contains_hash(path: Path, h: str) -> bool:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if h in line:
                    return True
    except OSError:
        return False
    return False


def main() -> int:
    raw_stdin = _read_stdin_safely()
    out_dir = _repo_root() / ".cache" / "session_debriefs"
    record: dict[str, object] = {
        "schema_version": _schema_version(),
        "ts": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    _merge_session_debrief_env(record)
    stdin_hash = _stdin_hash_and_hook(raw_stdin, record)

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        path = out_dir / f"debrief-{day}.jsonl"
        if stdin_hash and path.is_file() and _jsonl_file_contains_hash(path, stdin_hash):
            return 0
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
