"""Tests for scripts/ci_policy.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ci_policy_mod():
    import importlib.util

    path = REPO_ROOT / "scripts" / "ci_policy.py"
    spec = importlib.util.spec_from_file_location("ci_policy_test", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "branch",
    [
        "feat/issue-1-thing",
        "fix/foo",
        "chore/issue-42-ci",
        "docs/readme",
        "dependabot/pip/foo",
        "cursor/feat_issue-1_x",
        "renovate/configure",
    ],
)
def test_validate_branch_accepts_allowed(ci_policy_mod, branch: str) -> None:
    ci_policy_mod.validate_branch(branch)


@pytest.mark.parametrize(
    ("branch", "match"),
    [
        ("main", "must not be 'main'"),
        ("wrong-branch", "must start with one of"),
        ("feature/foo", "must start with one of"),
        ("", "must not be empty"),
    ],
)
def test_validate_branch_rejects(ci_policy_mod, branch: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ci_policy_mod.validate_branch(branch)


@pytest.mark.parametrize(
    "title",
    [
        "feat: add thing",
        "fix(scope): handle it",
        "chore!: breaking change",
        "docs: update README",
        "ci: tweak workflow",
    ],
)
def test_validate_pr_title_accepts(ci_policy_mod, title: str) -> None:
    ci_policy_mod.validate_pr_title(title)


@pytest.mark.parametrize(
    ("title", "match"),
    [
        ("", "must not be empty"),
        ("   ", "must not be empty"),
        ("Add thing", "must follow conventional commits"),
        ("FEAT: lower", "must follow conventional commits"),
        ("feat - no colon", "must follow conventional commits"),
        ("feat: ", "must follow conventional commits"),
    ],
)
def test_validate_pr_title_rejects(ci_policy_mod, title: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ci_policy_mod.validate_pr_title(title)


def test_main_github_event_workflow_dispatch_skips_with_notice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    ci_policy_mod,
) -> None:
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"inputs": {}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert ci_policy_mod.main() == 0
    err = capsys.readouterr().err
    assert "workflow_dispatch" in err
    assert "skipping" in err


def test_main_push_to_main_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {"ref": "refs/heads/main"}
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert ci_policy_mod.main() == 0


def test_main_push_invalid_branch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {"ref": "refs/heads/wrong-branch"}
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert ci_policy_mod.main() == 1


def test_main_push_allowed_branch_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {"ref": "refs/heads/chore/issue-42-ci"}
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert ci_policy_mod.main() == 0


def test_main_push_tag_ref_skips_branch_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    ci_policy_mod,
) -> None:
    ev = {"ref": "refs/tags/v1.0.0"}
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    assert ci_policy_mod.main() == 0
    assert "non-branch push ref" in capsys.readouterr().err


def test_main_pull_request_valid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {
        "pull_request": {
            "title": "chore: do something",
            "head": {"ref": "chore/issue-99-x"},
        }
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 0


def test_main_pull_request_renovate_validates_title_like_other_bots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    """Renovate uses allowed branch prefix; title must still be conventional (unlike Dependabot)."""
    ev = {
        "pull_request": {
            "title": "chore(deps): update lodash to v4.17.21",
            "head": {"ref": "renovate/lodash-4.x"},
        }
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 0


def test_main_pull_request_renovate_bad_title_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {
        "pull_request": {
            "title": "Update lodash",
            "head": {"ref": "renovate/lodash-4.x"},
        }
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 1


def test_main_pull_request_skips_dependabot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {
        "pull_request": {
            "title": "Bump foo from 1 to 2",
            "head": {"ref": "dependabot/pip/foo-abc"},
        }
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 0


def test_main_github_event_path_invalid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    p = tmp_path / "event.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 1


def test_main_github_event_path_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    p = tmp_path / "nonexistent.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 1


def test_main_pull_request_bad_title(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ci_policy_mod
) -> None:
    ev = {
        "pull_request": {
            "title": "not conventional",
            "head": {"ref": "feat/ok"},
        }
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert ci_policy_mod.main() == 1


def test_main_local_main_branch(monkeypatch: pytest.MonkeyPatch, ci_policy_mod) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setattr(ci_policy_mod, "_current_git_branch", lambda: "main")
    assert ci_policy_mod.main() == 0


def test_main_local_feature_branch_ok(monkeypatch: pytest.MonkeyPatch, ci_policy_mod) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setattr(ci_policy_mod, "_current_git_branch", lambda: "chore/issue-42-ci")
    assert ci_policy_mod.main() == 0


def test_main_local_invalid_branch(monkeypatch: pytest.MonkeyPatch, ci_policy_mod) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setattr(ci_policy_mod, "_current_git_branch", lambda: "invalid-branch")
    assert ci_policy_mod.main() == 1
