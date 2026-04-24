"""Tests for scripts/merge_settings.py hook merge semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def merge_mod():
    import importlib.util

    path = REPO_ROOT / "scripts" / "merge_settings.py"
    spec = importlib.util.spec_from_file_location("merge_settings_test", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_merge_empty_local_equals_base(merge_mod) -> None:
    base = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo a"}]}]}}
    assert merge_mod.merge_settings_dict(base, {}) == base


def test_merge_local_appends_command_hook(merge_mod) -> None:
    base = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo a"}]}],
        }
    }
    local = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo b"}]}],
        }
    }
    out = merge_mod.merge_settings_dict(base, local)
    hooks = out["hooks"]["Stop"][0]["hooks"]
    assert len(hooks) == 2
    assert hooks[0]["command"] == "echo a"
    assert hooks[1]["command"] == "echo b"


def test_merge_local_overrides_same_fingerprint(merge_mod) -> None:
    base = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo a"}]}],
        }
    }
    local = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo a", "timeout": 999}]}],
        }
    }
    out = merge_mod.merge_settings_dict(base, local)
    hooks = out["hooks"]["Stop"][0]["hooks"]
    assert len(hooks) == 1
    assert hooks[0]["command"] == "echo a"
    assert hooks[0]["timeout"] == 999


def test_merge_dedupes_duplicate_commands(merge_mod) -> None:
    base = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo dup"}]}],
        }
    }
    local = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo dup"}]}],
        }
    }
    out = merge_mod.merge_settings_dict(base, local)
    hooks = out["hooks"]["Stop"][0]["hooks"]
    assert len(hooks) == 1


def test_merge_preserves_two_pretooluse_blocks_same_matcher(merge_mod) -> None:
    base = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [{"type": "prompt", "prompt": "first"}],
                },
                {
                    "matcher": "Edit|Write",
                    "hooks": [{"type": "prompt", "prompt": "second"}],
                },
            ],
        }
    }
    out = merge_mod.merge_settings_dict(base, {})
    assert len(out["hooks"]["PreToolUse"]) == 2
    assert out["hooks"]["PreToolUse"][0]["hooks"][0]["prompt"] == "first"
    assert out["hooks"]["PreToolUse"][1]["hooks"][0]["prompt"] == "second"


def test_merge_idempotent_on_repo_base(merge_mod) -> None:
    base_path = REPO_ROOT / ".claude" / "settings.base.json"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    once = merge_mod.merge_settings_dict(base, {})
    twice = merge_mod.merge_settings_dict(once, {})
    assert once == twice


def test_template_merge_no_local_matches_committed_settings(merge_mod) -> None:
    base = json.loads((REPO_ROOT / ".claude" / "settings.base.json").read_text(encoding="utf-8"))
    expected = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert merge_mod.merge_settings_dict(base, {}) == expected


def test_duplicate_base_fingerprint_local_override_targets_first(merge_mod) -> None:
    """Copilot: first index wins in index_by_fp so local replaces the kept duplicate."""
    base = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": "echo dup"},
                        {"type": "command", "command": "echo dup"},
                    ]
                }
            ],
        }
    }
    local = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": "echo dup", "timeout": 1},
                    ]
                }
            ],
        }
    }
    out = merge_mod.merge_settings_dict(base, local)
    hooks = out["hooks"]["Stop"][0]["hooks"]
    assert len(hooks) == 1
    assert hooks[0]["command"] == "echo dup"
    assert hooks[0]["timeout"] == 1


def test_local_matcher_must_match_base(merge_mod) -> None:
    base = {"hooks": {"SessionStart": [{"matcher": "*", "hooks": []}]}}
    local = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [{"type": "command", "command": "x"}],
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="matcher mismatch"):
        merge_mod.merge_settings_dict(base, local)


def test_local_matcher_on_base_without_matcher_raises(merge_mod) -> None:
    base = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "a"}]}]}}
    local = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "b"}],
                }
            ],
        }
    }
    with pytest.raises(ValueError, match="matcher in local but base has none"):
        merge_mod.merge_settings_dict(base, local)
