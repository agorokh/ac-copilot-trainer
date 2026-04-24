"""session_debrief hook script."""

from __future__ import annotations

import importlib.util
import json
import sys
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = REPO_ROOT / "scripts" / "session_debrief.py"
    spec = importlib.util.spec_from_file_location("_session_debrief_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def debrief_mod():
    return _load()


def test_session_debrief_skips_duplicate_stdin_payload(
    tmp_path: Path, debrief_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    payload = json.dumps({"event": "Stop", "tool_name": "x", "extra": "ignored"})
    debrief_dir = tmp_path / ".cache" / "session_debriefs"
    debrief_dir.mkdir(parents=True)

    monkeypatch.setattr(sys, "stdin", StringIO(payload))
    assert debrief_mod.main() == 0
    files = list(debrief_dir.glob("debrief-*.jsonl"))
    assert len(files) == 1
    debrief_path = files[0]
    lines = debrief_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row.get("schema_version") == 1
    assert row["hook"] == {"event": "Stop", "tool_name": "x"}
    assert "hook_payload_hash" in row

    monkeypatch.setattr(sys, "stdin", StringIO(payload))
    assert debrief_mod.main() == 0
    lines2 = debrief_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines2) == 1


def test_session_debrief_skips_duplicate_when_hash_not_in_file_tail(
    tmp_path: Path, debrief_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deduplication must scan the whole JSONL file, not only a trailing window."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    payload = json.dumps({"event": "Stop", "tool_name": "tail-test"})
    debrief_dir = tmp_path / ".cache" / "session_debriefs"
    debrief_dir.mkdir(parents=True)

    monkeypatch.setattr(sys, "stdin", StringIO(payload))
    assert debrief_mod.main() == 0
    files = list(debrief_dir.glob("debrief-*.jsonl"))
    assert len(files) == 1
    debrief_path = files[0]
    first = debrief_path.read_text(encoding="utf-8")
    row = json.loads(first.strip().splitlines()[0])
    digest = row["hook_payload_hash"]
    assert isinstance(digest, str)
    # Push the original record out of any fixed tail window (e.g. 200k chars).
    filler = ("0" * 120 + "\n") * 2500
    debrief_path.write_text(first.rstrip("\n") + "\n" + filler, encoding="utf-8")

    monkeypatch.setattr(sys, "stdin", StringIO(payload))
    assert debrief_mod.main() == 0
    lines = debrief_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 + 2500
