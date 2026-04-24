"""Tests for ``tools.pr_pain`` pure functions (no GitHub access)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.pr_pain import file_issue, pain_score

# ---------------------------------------------------------------------------
# pain_score helpers
# ---------------------------------------------------------------------------


def test_is_bot_detects_known_logins() -> None:
    assert pain_score._is_bot("coderabbitai", None) is True
    assert pain_score._is_bot("dependabot", "User") is True
    assert pain_score._is_bot("renovate", None) is True


def test_is_bot_detects_bot_suffix() -> None:
    assert pain_score._is_bot("anything[bot]", None) is True
    assert pain_score._is_bot("foo", "Bot") is True


def test_is_bot_humans_pass() -> None:
    assert pain_score._is_bot("arseny", "User") is False
    assert pain_score._is_bot("", None) is False
    assert pain_score._is_bot(None, None) is False


def test_top_dirs_orders_by_frequency_then_truncates() -> None:
    paths = [
        "scripts/a.sh",
        "scripts/b.sh",
        "scripts/c.sh",
        "docs/x.md",
        "docs/y.md",
        "tools/z.py",
        ".github/w.yml",
    ]
    assert pain_score._top_dirs(paths, top_n=2) == ["scripts", "docs"]
    assert pain_score._top_dirs(paths, top_n=10) == ["scripts", "docs", "tools", ".github"]


def test_top_dirs_handles_root_files() -> None:
    assert pain_score._top_dirs(["README.md"]) == ["README.md"]
    assert pain_score._top_dirs([]) == []


def test_fingerprint_is_stable_and_order_invariant() -> None:
    a = pain_score._fingerprint(["scripts", "docs", "tools"])
    b = pain_score._fingerprint(["tools", "scripts", "docs"])
    assert a == b
    assert len(a) == 12
    assert all(c in "0123456789abcdef" for c in a)


def test_fingerprint_distinguishes_different_dirs() -> None:
    a = pain_score._fingerprint(["scripts", "docs"])
    b = pain_score._fingerprint(["scripts", "tests"])
    assert a != b


def test_fingerprint_handles_empty() -> None:
    fp = pain_score._fingerprint([])
    assert len(fp) == 12


def test_parse_iso_handles_z_suffix() -> None:
    ts = pain_score._parse_iso("2026-04-21T05:00:37Z")
    assert ts is not None
    assert ts.year == 2026 and ts.hour == 5


def test_parse_iso_returns_none_for_empty() -> None:
    assert pain_score._parse_iso(None) is None
    assert pain_score._parse_iso("") is None


def test_fix_commit_regex_matches_expected_prefixes() -> None:
    rx = pain_score._FIX_COMMIT_RE
    assert rx.match("fix: typo")
    assert rx.match("fix(parser): bug")
    assert rx.match("chore: address review feedback")
    assert rx.match("chore(review): polish")
    assert not rx.match("feat: new thing")
    assert not rx.match("docs: clarify")
    assert not rx.match("chore(deps): bump")  # non-review chore stays out


def test_thresholds_are_ordered() -> None:
    assert pain_score.THRESHOLD_HIGH > pain_score.THRESHOLD_MEDIUM > 0


# ---------------------------------------------------------------------------
# file_issue helpers
# ---------------------------------------------------------------------------


def _sample_score(level: str = "high", score: float = 30.5) -> dict:
    return {
        "score": score,
        "level": level,
        "fingerprint": "abc123def456",  # pragma: allowlist secret
        "breakdown": {
            "commits_after_first_review": 10,
            "fix_commits": 2,
            "human_review_comments": 15,
            "bot_review_comments": 50,
            "ci_red_runs": 3,
            "days_open_after_first_ready_for_review": 4.5,
        },
        "inputs": {
            "title": "demo PR",
            "changed_top_dirs": ["scripts", "docs", "tools"],
            "repo": "agorokh/template-repo",
            "pr": 99,
        },
    }


def test_issue_title_includes_fingerprint_and_cluster() -> None:
    fp = "abc123def456"  # pragma: allowlist secret
    title = file_issue.issue_title(fp, ["scripts", "docs", "tools"])
    assert f"[fp:{fp}]" in title
    assert "scripts/docs" in title  # only top-2 dirs


def test_issue_title_handles_empty_dirs() -> None:
    fp = "deadbeef0000"  # pragma: allowlist secret
    title = file_issue.issue_title(fp, [])
    assert f"[fp:{fp}]" in title
    assert "unknown" in title


def test_issue_body_contains_required_markers() -> None:
    body = file_issue.issue_body(_sample_score(), "agorokh/template-repo", 99)
    assert "<!-- pr_pain_fingerprint: abc123def456 -->" in body  # noqa: E501  # pragma: allowlist secret
    assert "agorokh/template-repo#99" in body
    assert "**Pain score:** **30.5** (high)" in body
    assert "## Linked PRs" in body
    assert "## Breakdown" in body
    # Breakdown table renders with weights and contributions.
    assert "| `commits_after_first_review` | 10 | 1.0 | 10.0 |" in body
    assert "| `bot_review_comments` | 50 | 0.1 | 5.0 |" in body


def test_append_pr_to_body_inserts_new_link() -> None:
    body = file_issue.issue_body(_sample_score(), "agorokh/template-repo", 99)
    new = file_issue.append_pr_to_body(body, "agorokh/agent-factory", 12, 17.0, "medium")
    assert "agent-factory#12" in new
    assert "score 17.0 (medium)" in new
    # Original entry is preserved.
    assert "agorokh/template-repo#99" in new
    # Critically: the regex must match the issue_body() output, so we get
    # exactly ONE Linked PRs section (not two) — guards against the
    # heading-then-blank-line regex bug flagged on initial review.
    assert new.count("## Linked PRs") == 1


def test_append_pr_to_body_is_idempotent() -> None:
    body = file_issue.issue_body(_sample_score(), "agorokh/template-repo", 99)
    once = file_issue.append_pr_to_body(body, "agorokh/agent-factory", 12, 17.0, "medium")
    twice = file_issue.append_pr_to_body(once, "agorokh/agent-factory", 12, 99.0, "high")
    assert once == twice  # second call is a no-op for the same PR


def test_append_pr_creates_section_when_missing() -> None:
    body = "Some unrelated body without the heading."
    new = file_issue.append_pr_to_body(body, "agorokh/foo", 5, 12.0, "medium")
    assert "## Linked PRs" in new
    assert "agorokh/foo#5" in new


def test_append_pr_handles_heading_with_zero_bullets() -> None:
    """If a maintainer manually edits the body to keep the `## Linked PRs`
    heading but remove all bullets, the regex must still match — otherwise
    we'd fall through and append a SECOND `## Linked PRs` section."""
    body = "Some intro\n\n## Linked PRs\n\nNo bullets remain.\n"
    new = file_issue.append_pr_to_body(body, "agorokh/foo", 5, 12.0, "medium")
    assert new.count("## Linked PRs") == 1
    assert "agorokh/foo#5" in new


def test_file_or_update_issue_noop_for_low_level(monkeypatch: pytest.MonkeyPatch) -> None:
    score = _sample_score(level="low", score=3.0)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not call gh for level=low")

    monkeypatch.setattr(file_issue, "find_existing_issue", boom)
    result = file_issue.file_or_update_issue(
        score=score,
        source_repo="agorokh/template-repo",
        source_pr=99,
        target_repo="agorokh/template-repo",
        dry_run=True,
    )
    assert result == {"action": "noop", "reason": "level=low"}


def test_file_or_update_issue_dry_run_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_issue, "find_existing_issue", lambda *a, **k: None)
    # Also mock `find_closed_related_issues` — it's called BEFORE the
    # `dry_run` branch on the create path (so we render the "Related
    # closed issues" preview correctly). Without this mock the test
    # would shell out to a real `gh` and either crash on
    # `FileNotFoundError` (gh missing — not RuntimeError, escapes the
    # except handler) or hit the live GitHub API (flaky, requires auth).
    monkeypatch.setattr(file_issue, "find_closed_related_issues", lambda *a, **k: [])
    result = file_issue.file_or_update_issue(
        score=_sample_score(),
        source_repo="agorokh/template-repo",
        source_pr=99,
        target_repo="agorokh/template-repo",
        dry_run=True,
    )
    assert result["action"] == "would-create"
    assert "[fp:abc123def456]" in result["title"]  # pragma: allowlist secret
    assert "process-learning" in result["labels"]
    assert "pain:high" in result["labels"]
    assert "from:template-repo" in result["labels"]


def test_file_or_update_issue_dry_run_append(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_body = file_issue.issue_body(_sample_score(), "agorokh/template-repo", 99)
    monkeypatch.setattr(
        file_issue,
        "find_existing_issue",
        lambda *a, **k: {"number": 7, "html_url": "https://x/7", "body": existing_body},
    )
    result = file_issue.file_or_update_issue(
        score=_sample_score(score=22.0, level="medium"),
        source_repo="agorokh/agent-factory",
        source_pr=11,
        target_repo="agorokh/template-repo",
        dry_run=True,
    )
    assert result["action"] == "would-append"
    assert result["number"] == 7
    assert "agent-factory#11" in result["comment_preview"]
    # New PR is from a different repo at a higher level — labels we'd
    # apply on append must include the cross-repo `from:` label and the
    # current `pain:<level>`, so dedup'd issues don't keep stale labels
    # from the first PR.
    assert "from:agent-factory" in result["labels_to_add"]
    assert "pain:medium" in result["labels_to_add"]


def test_file_or_update_issue_dry_run_already_linked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run preview must reflect the live behavior — when the PR is
    already linked in the existing body, return `would-already-link` (not
    `would-append`) so operators see what the live run will actually do."""
    existing_body = file_issue.issue_body(_sample_score(), "agorokh/template-repo", 99)
    # Pre-link PR #11 by appending it once.
    existing_body = file_issue.append_pr_to_body(
        existing_body, "agorokh/agent-factory", 11, 22.0, "medium"
    )
    monkeypatch.setattr(
        file_issue,
        "find_existing_issue",
        lambda *a, **k: {"number": 7, "html_url": "https://x/7", "body": existing_body},
    )
    result = file_issue.file_or_update_issue(
        score=_sample_score(score=22.0, level="medium"),
        source_repo="agorokh/agent-factory",
        source_pr=11,
        target_repo="agorokh/template-repo",
        dry_run=True,
    )
    assert result["action"] == "would-already-link"
    assert result["number"] == 7


def test_append_pr_to_body_handles_backslash_in_existing_bullets() -> None:
    """`re.sub` interprets `\\1` etc. as backreferences in plain-string
    replacements — pre-existing bullet text containing `\\1` would either
    raise `re.error` or silently corrupt output. The lambda-replacement
    form must keep backslash content intact."""
    body = (
        "intro\n\n## Linked PRs\n\n"
        "- [agorokh/old#1](https://x) — score 5.0 (low) \\1 \\2 backslash\n"
    )
    new = file_issue.append_pr_to_body(body, "agorokh/foo", 5, 12.0, "medium")
    assert new.count("## Linked PRs") == 1
    assert "\\1 \\2 backslash" in new
    assert "agorokh/foo#5" in new


def test_metric_weights_single_source_of_truth() -> None:
    # file_issue's body must use the same weights as pain_score; importing
    # the constant from one place is the contract — re-asserted here so any
    # future drift is caught loudly.
    assert file_issue.METRIC_WEIGHTS is pain_score.METRIC_WEIGHTS
    assert pain_score.METRIC_WEIGHTS["ci_red_runs"] == 2.0


def test_fetch_paginated_handles_brackets_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: previous impl used text.replace('][', ',') which corrupts
    string values containing ']['. The --slurp flow must handle them cleanly."""

    class _R:
        returncode = 0
        # Two pages, each containing a body string with `][` inside.
        stdout = json.dumps(
            [
                [{"id": 1, "body": "before ][ after"}, {"id": 2, "body": "ok"}],
                [{"id": 3, "body": "more ]["}],
            ]
        )
        stderr = ""

    monkeypatch.setattr(pain_score.subprocess, "run", lambda *a, **k: _R())
    out = pain_score._fetch_paginated("/repos/x/y/pulls/1/comments", "gh")
    assert [item["id"] for item in out] == [1, 2, 3]
    assert out[0]["body"] == "before ][ after"  # not corrupted


def test_fetch_workflow_runs_url_encodes_branch_and_flattens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Branch names with `/` (`feat/foo`) must round-trip; pages flatten."""
    captured: dict[str, list[str]] = {"args": []}

    class _R:
        returncode = 0
        stdout = json.dumps(
            [
                {"workflow_runs": [{"conclusion": "failure"}, {"conclusion": "success"}]},
                {"workflow_runs": [{"conclusion": "cancelled"}]},
            ]
        )
        stderr = ""

    def fake_run(args: list[str], *_a: object, **_k: object) -> _R:
        captured["args"] = args
        return _R()

    monkeypatch.setattr(pain_score.subprocess, "run", fake_run)
    runs = pain_score._fetch_workflow_runs("agorokh/template-repo", "feat/pr-pain", "gh")
    assert len(runs) == 3
    # `/` must be percent-encoded so `branch=` parses correctly server-side.
    joined = " ".join(captured["args"])
    assert "branch=feat%2Fpr-pain" in joined
    assert "--paginate" in captured["args"]
    assert "--slurp" in captured["args"]


def test_compute_pain_score_end_to_end_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock the entire `gh`-fetching layer and verify scoring + fingerprint."""
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    monkeypatch.setattr(
        pain_score,
        "_fetch_pr",
        lambda repo, pr, gh: {
            "title": "demo",
            "headRefName": "feat/x",
            "createdAt": "2026-04-10T00:00:00Z",
            "mergedAt": "2026-04-15T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        pain_score,
        "_fetch_commits",
        lambda *_a, **_k: [
            {
                "commit": {
                    "message": "feat: initial",
                    "committer": {"date": "2026-04-11T00:00:00Z"},
                }
            },
            {
                "commit": {
                    "message": "fix: review nit",
                    "committer": {"date": "2026-04-13T00:00:00Z"},
                }
            },
            {
                "commit": {
                    "message": "chore: address review",
                    "committer": {"date": "2026-04-14T00:00:00Z"},
                }
            },
        ],
    )
    monkeypatch.setattr(
        pain_score,
        "_fetch_reviews",
        lambda *_a, **_k: [
            {
                "submitted_at": "2026-04-12T00:00:00Z",
                "user": {"login": "human", "type": "User"},
                "body": "lgtm",
            },
        ],
    )
    monkeypatch.setattr(
        pain_score,
        "_fetch_review_comments",
        lambda *_a, **_k: [
            {"user": {"login": "human", "type": "User"}},
            {"user": {"login": "coderabbitai", "type": "Bot"}},
            {"user": {"login": "copilot[bot]", "type": "Bot"}},
        ],
    )
    monkeypatch.setattr(
        pain_score,
        "_fetch_issue_comments",
        lambda *_a, **_k: [{"user": {"login": "human", "type": "User"}}],
    )
    monkeypatch.setattr(
        pain_score,
        "_fetch_changed_files",
        lambda *_a, **_k: ["scripts/a.sh", "scripts/b.sh", "docs/x.md", "tools/y.py"],
    )
    monkeypatch.setattr(
        pain_score,
        "_fetch_workflow_runs",
        lambda *_a, **_k: [
            {"conclusion": "failure"},
            {"conclusion": "success"},
            {"conclusion": "timed_out"},
        ],
    )

    result = pain_score.compute_pain_score("agorokh/template-repo", 42)
    assert result.level in {"low", "medium", "high"}
    # commits_after_first_review=2, fix_commits=2,
    # human_comments=3 (1 review-comment + 1 issue-comment + 1 review body),
    # bot_comments=2, ci_red=2, days_after=3
    # = 2 + 1.0 + 0.9 + 0.2 + 4.0 + 3.0 = 11.1
    assert result.score == pytest.approx(11.1, abs=0.01)
    assert result.level == "low"
    assert result.breakdown["fix_commits"] == 2
    assert result.breakdown["ci_red_runs"] == 2
    assert result.breakdown["human_review_comments"] == 3
    assert result.breakdown["bot_review_comments"] == 2
    assert result.fingerprint == pain_score._fingerprint(["scripts", "docs", "tools"])


def test_compute_pain_score_excludes_pre_pr_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs created before the PR opened (long-lived branch reuse, pre-PR
    experimentation) must not count toward this PR's CI red runs."""
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    monkeypatch.setattr(
        pain_score,
        "_fetch_pr",
        lambda *a, **k: {
            "headRefName": "x",
            "createdAt": "2026-04-15T00:00:00Z",
            "mergedAt": "2026-04-20T00:00:00Z",
        },
    )
    for fn in (
        "_fetch_commits",
        "_fetch_reviews",
        "_fetch_review_comments",
        "_fetch_issue_comments",
    ):
        monkeypatch.setattr(pain_score, fn, lambda *a, _r=fn, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_changed_files", lambda *a, **k: ["src/a.py"])
    monkeypatch.setattr(
        pain_score,
        "_fetch_workflow_runs",
        lambda *a, **k: [
            {"conclusion": "failure", "created_at": "2026-04-10T00:00:00Z"},  # pre-PR
            {"conclusion": "failure", "created_at": "2026-04-12T00:00:00Z"},  # pre-PR
            {"conclusion": "failure", "created_at": "2026-04-16T00:00:00Z"},  # in-PR
        ],
    )
    result = pain_score.compute_pain_score("a/b", 1)
    assert result.breakdown["ci_red_runs"] == 1


def test_compute_pain_score_excludes_cancelled_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cancelled` must NOT count: cancel-in-progress on every push would
    otherwise inflate pain on any normal force-push / rebase workflow."""
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    monkeypatch.setattr(
        pain_score,
        "_fetch_pr",
        lambda *a, **k: {
            "headRefName": "x",
            "createdAt": "2026-04-10T00:00:00Z",
            "mergedAt": "2026-04-20T00:00:00Z",
        },
    )
    monkeypatch.setattr(pain_score, "_fetch_commits", lambda *a, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_reviews", lambda *a, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_review_comments", lambda *a, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_issue_comments", lambda *a, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_changed_files", lambda *a, **k: ["src/a.py"])
    monkeypatch.setattr(
        pain_score,
        "_fetch_workflow_runs",
        lambda *a, **k: [
            {"conclusion": "cancelled"},
            {"conclusion": "cancelled"},
            {"conclusion": "cancelled"},
            {"conclusion": "failure"},
        ],
    )
    result = pain_score.compute_pain_score("a/b", 1)
    assert result.breakdown["ci_red_runs"] == 1, "cancels must not count, only failure remains"


def test_fetch_commits_warns_on_rest_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When `_fetch_commits` returns ≥ 250 commits, GitHub silently
    truncated the result — score will undercount, so warn loud on stderr
    so operators (and the workflow log) see the cap was hit."""
    fake = [{"commit": {"message": "x"}}] * 250
    monkeypatch.setattr(pain_score, "_fetch_paginated", lambda *a, **k: fake)
    out = pain_score._fetch_commits("a/b", 1, "gh")
    err = capsys.readouterr().err
    assert len(out) == 250
    assert "250-commit REST cap" in err
    assert "a/b#1" in err


def test_fetch_commits_no_warning_below_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        pain_score, "_fetch_paginated", lambda *a, **k: [{"commit": {"message": "x"}}] * 10
    )
    pain_score._fetch_commits("a/b", 1, "gh")
    assert "REST cap" not in capsys.readouterr().err


def test_compute_pain_score_rejects_unmerged_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pain scoring is post-merge only; an unmerged PR (mergedAt is None)
    must be rejected up-front so workflow_dispatch / CLI cannot file
    process-learning issues mid-flight."""
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    monkeypatch.setattr(
        pain_score,
        "_fetch_pr",
        lambda *a, **k: {
            "headRefName": "x",
            "createdAt": "2026-04-15T00:00:00Z",
            "mergedAt": None,
        },
    )
    with pytest.raises(RuntimeError, match="not merged"):
        pain_score.compute_pain_score("a/b", 1)


def test_compute_pain_score_excludes_post_merge_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs created AFTER the PR merged must not count: the branch may be
    reused, kept receiving pushes, or refer to a totally unrelated PR
    bearing the same head ref."""
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    monkeypatch.setattr(
        pain_score,
        "_fetch_pr",
        lambda *a, **k: {
            "headRefName": "x",
            "createdAt": "2026-04-10T00:00:00Z",
            "mergedAt": "2026-04-15T00:00:00Z",
        },
    )
    for fn in (
        "_fetch_commits",
        "_fetch_reviews",
        "_fetch_review_comments",
        "_fetch_issue_comments",
    ):
        monkeypatch.setattr(pain_score, fn, lambda *a, _r=fn, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_changed_files", lambda *a, **k: ["src/a.py"])
    monkeypatch.setattr(
        pain_score,
        "_fetch_workflow_runs",
        lambda *a, **k: [
            {"conclusion": "failure", "created_at": "2026-04-12T00:00:00Z"},  # in-window
            {"conclusion": "failure", "created_at": "2026-04-16T00:00:00Z"},  # post-merge
            {"conclusion": "failure", "created_at": "2026-04-20T00:00:00Z"},  # post-merge
        ],
    )
    result = pain_score.compute_pain_score("a/b", 1)
    assert result.breakdown["ci_red_runs"] == 1


def test_compute_pain_score_first_review_ignores_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bot reviews must NOT mark `first_review_at` — otherwise an auto-bot
    posting first inflates `commits_after_first_review` (every commit
    becomes "after") and `days_open_after_first_ready_for_review` (PR
    appears to have lingered post-bot for the entire window)."""
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    monkeypatch.setattr(
        pain_score,
        "_fetch_pr",
        lambda *a, **k: {
            "headRefName": "x",
            "createdAt": "2026-04-10T00:00:00Z",
            "mergedAt": "2026-04-20T00:00:00Z",
        },
    )
    # Bot reviews first by 8 days; one human review on day-of-merge.
    monkeypatch.setattr(
        pain_score,
        "_fetch_reviews",
        lambda *a, **k: [
            {
                "submitted_at": "2026-04-12T00:00:00Z",
                "user": {"login": "coderabbitai", "type": "Bot"},
            },
            {
                "submitted_at": "2026-04-19T00:00:00Z",
                "user": {"login": "alice", "type": "User"},
            },
        ],
    )
    # Two commits — one before any review, one between bot and human.
    monkeypatch.setattr(
        pain_score,
        "_fetch_commits",
        lambda *a, **k: [
            {"commit": {"message": "feat: initial", "committer": {"date": "2026-04-11T00:00:00Z"}}},
            {"commit": {"message": "wip", "committer": {"date": "2026-04-15T00:00:00Z"}}},
        ],
    )
    monkeypatch.setattr(pain_score, "_fetch_review_comments", lambda *a, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_issue_comments", lambda *a, **k: [])
    monkeypatch.setattr(pain_score, "_fetch_changed_files", lambda *a, **k: ["src/a.py"])
    monkeypatch.setattr(pain_score, "_fetch_workflow_runs", lambda *a, **k: [])

    result = pain_score.compute_pain_score("a/b", 1)
    # First HUMAN review is 2026-04-19, so neither commit (2026-04-11
    # and 2026-04-15) qualifies as "after first review".
    assert result.breakdown["commits_after_first_review"] == 0
    # Days from first-human-review (04-19) to merge (04-20) = 1.0d, NOT
    # the 8d we'd see if the bot review counted.
    assert result.breakdown["days_open_after_first_ready_for_review"] == 1.0
    # And the inputs reflect the human boundary.
    assert result.inputs["first_review_at"] == "2026-04-19T00:00:00+00:00"


def test_compute_pain_score_raises_when_gh_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: None)
    with pytest.raises(RuntimeError, match="not found"):
        pain_score.compute_pain_score("a/b", 1)


def test_main_pain_score_outputs_human_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(pain_score.shutil, "which", lambda _b: "/usr/bin/gh")
    fake = pain_score.PainScore(
        score=5.0,
        level="low",
        breakdown={"commits_after_first_review": 5.0},
        fingerprint="ffffffffffff",  # pragma: allowlist secret
        inputs={"changed_top_dirs": ["scripts"]},
    )
    monkeypatch.setattr(pain_score, "compute_pain_score", lambda *a, **k: fake)
    rc = pain_score.main(["--repo", "a/b", "--pr", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "5.0" in out and "low" in out and "ffffffffffff" in out  # pragma: allowlist secret


def test_file_or_update_issue_rejects_missing_keys() -> None:
    with pytest.raises(ValueError, match="missing required keys"):
        file_issue.file_or_update_issue(
            score={"level": "high"},  # missing fingerprint, score, breakdown, inputs
            source_repo="a/b",
            source_pr=1,
            target_repo="a/b",
            dry_run=True,
        )


def test_file_or_update_issue_rejects_missing_score_field() -> None:
    """Regression: `score['score']` is read in `issue_body` and the comment
    text — a missing `score` key must fail validation up-front, not crash
    later with a bare KeyError."""
    bad = _sample_score()
    bad.pop("score")
    with pytest.raises(ValueError, match="missing required keys.*score"):
        file_issue.file_or_update_issue(
            score=bad,
            source_repo="a/b",
            source_pr=1,
            target_repo="a/b",
            dry_run=True,
        )


def test_file_or_update_issue_created_returns_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: `created` action's docstring promises `number`, and
    sibling actions (`appended`, `already-linked`) return it. Keep parity."""
    monkeypatch.setattr(file_issue, "find_existing_issue", lambda *a, **k: None)
    monkeypatch.setattr(file_issue, "find_closed_related_issues", lambda *a, **k: [])

    def fake_create(args: list[str], gh: str, body_input: str | None = None) -> str:
        return "https://github.com/agorokh/template-repo/issues/4242\n"

    monkeypatch.setattr(file_issue, "_gh_run", fake_create)
    monkeypatch.setattr(file_issue.shutil, "which", lambda _b: "/usr/bin/gh")
    result = file_issue.file_or_update_issue(
        score=_sample_score(),
        source_repo="agorokh/template-repo",
        source_pr=1,
        target_repo="agorokh/template-repo",
        dry_run=False,
    )
    assert result == {
        "action": "created",
        "url": "https://github.com/agorokh/template-repo/issues/4242",
        "number": 4242,
    }


def test_file_or_update_issue_created_raises_on_unparseable_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (Qodo): if `gh issue create` ever returns a URL we can't
    parse the issue number out of, we MUST raise — silently returning
    `number: None` would break the documented contract that `appended` /
    `already-linked` consumers rely on, and the repo policy is `prefer
    explicit errors over silent fallbacks`."""
    monkeypatch.setattr(file_issue, "find_existing_issue", lambda *a, **k: None)
    monkeypatch.setattr(file_issue, "find_closed_related_issues", lambda *a, **k: [])
    monkeypatch.setattr(file_issue.shutil, "which", lambda _b: "/usr/bin/gh")

    def fake_create_bad_url(args: list[str], gh: str, body_input: str | None = None) -> str:
        return "https://github.com/agorokh/template-repo/discussions/4242\n"

    monkeypatch.setattr(file_issue, "_gh_run", fake_create_bad_url)
    with pytest.raises(RuntimeError, match="parseable issue number"):
        file_issue.file_or_update_issue(
            score=_sample_score(),
            source_repo="agorokh/template-repo",
            source_pr=1,
            target_repo="agorokh/template-repo",
            dry_run=False,
        )


def test_file_or_update_issue_warns_when_full_body_refetch_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression (Qodo): a refetch failure (`gh issue view`) MUST emit a
    visible stderr warning. We still skip the body edit (under-linking is
    safer than clobbering with the truncated Search-API copy), but the
    operator has to be told `Linked PRs` won't be updated this run —
    silent fallbacks are forbidden by repo policy."""
    monkeypatch.setattr(
        file_issue,
        "find_existing_issue",
        lambda *a, **k: {
            "number": 99,
            "html_url": "https://github.com/agorokh/template-repo/issues/99",
            "body": "stub body without bullet marker",
        },
    )
    monkeypatch.setattr(file_issue.shutil, "which", lambda _b: "/usr/bin/gh")

    def fake_gh_json(args: list[str], gh: str) -> Any:
        # Refetch the full body — fail loudly so the production code's
        # `except RuntimeError` branch fires.
        raise RuntimeError("gh failed (1): network down")

    monkeypatch.setattr(file_issue, "gh_json", fake_gh_json)

    edit_calls: list[list[str]] = []
    comment_calls: list[str] = []

    def fake_run(args: list[str], gh: str, *, body_input: str | None = None) -> str:
        edit_calls.append(args)
        if "comment" in args and body_input is not None:
            comment_calls.append(body_input)
        return ""

    monkeypatch.setattr(file_issue, "_gh_run", fake_run)

    result = file_issue.file_or_update_issue(
        score=_sample_score(),
        source_repo="agorokh/template-repo",
        source_pr=1,
        target_repo="agorokh/template-repo",
        dry_run=False,
    )
    err = capsys.readouterr().err
    assert "warning: failed to refetch full body" in err
    assert "agorokh/template-repo#99" in err
    assert result["action"] == "appended"
    # Body edit MUST be skipped — `gh issue edit ... --body-file -` should
    # never run, only the label-edit + comment paths. (`gh issue comment
    # --body-file -` is fine and expected.)
    assert not any("edit" in args and "--body-file" in args for args in edit_calls), (
        "body edit must be skipped on refetch failure"
    )
    # Label edit + new comment still happen.
    assert any("--add-label" in args for args in edit_calls)
    assert len(comment_calls) == 1


def test_load_extra_bots_merges_yaml_into_known_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression (Gemini): the bot allowlist must be extensible without a
    code change. Drop a YAML with `extra_bot_logins: [...]` and confirm
    `_is_bot` picks it up after we reset the lazy cache."""
    cfg = tmp_path / "pr-pain-config.yml"
    cfg.write_text("extra_bot_logins:\n  - exotic-review-bot\n  - another-bot\n")
    monkeypatch.setattr(pain_score, "_DEFAULT_PAIN_CONFIG", str(cfg))
    monkeypatch.setattr(pain_score, "_known_bots_cache", None)
    extras = pain_score._load_extra_bots(str(cfg))
    assert "exotic-review-bot" in extras
    assert pain_score._is_bot("exotic-review-bot", "User") is True
    # Built-ins still detected.
    assert pain_score._is_bot("coderabbitai", None) is True
    # Unknown logins still treated as human.
    assert pain_score._is_bot("regular-human", "User") is False


def test_load_extra_bots_handles_missing_or_malformed_config(
    tmp_path: Path,
) -> None:
    """Regression: missing file → empty set, malformed YAML → empty set,
    extras-missing-key → empty set. None of these may raise, since
    `_is_bot` is on the hot path of every comment in `compute_pain_score`."""
    missing = tmp_path / "absent.yml"
    assert pain_score._load_extra_bots(str(missing)) == frozenset()

    malformed = tmp_path / "broken.yml"
    malformed.write_text("not: [valid: yaml")
    assert pain_score._load_extra_bots(str(malformed)) == frozenset()

    no_key = tmp_path / "ok.yml"
    no_key.write_text("enabled_repos: [a/b]\n")
    assert pain_score._load_extra_bots(str(no_key)) == frozenset()

    wrong_type = tmp_path / "wrong.yml"
    wrong_type.write_text("extra_bot_logins: not-a-list\n")
    assert pain_score._load_extra_bots(str(wrong_type)) == frozenset()


def test_explain_gh_failure_reframes_slurp_errors() -> None:
    """Regression (Gemini): when the local `gh` is too old for `--paginate
    --slurp`, the cryptic 'unknown flag' must be re-framed into a clear
    'needs gh >= 2.28' message — operators hit this on local CLI usage,
    not just in CI where the workflow has its own version guard."""
    msg = pain_score._explain_gh_failure("unknown flag --slurp", "/repos/a/b/pulls/1/commits")
    assert "gh` >= 2.28" in msg
    assert "/repos/a/b/pulls/1/commits" in msg
    msg2 = pain_score._explain_gh_failure("--paginate is invalid", "actions/runs")
    assert "gh` >= 2.28" in msg2
    # Unrelated stderr is left as-is (re-framing only fires on flag errors).
    msg3 = pain_score._explain_gh_failure("404 Not Found", "/repos/a/b/pulls/99")
    assert "gh` >=" not in msg3
    assert "404 Not Found" in msg3


def test_find_closed_related_issues_sorts_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (Gemini): closed `[fp:<hex>]` peers must surface in
    the new-issue body so historical context isn't lost. Sort by
    `closed_at` descending so the most recent close shows first."""

    def fake_gh_json(args: list[str], gh: str) -> Any:
        return {
            "items": [
                {
                    "number": 1,
                    "title": "old",
                    "html_url": "u1",
                    "closed_at": "2025-01-01T00:00:00Z",
                },
                {
                    "number": 3,
                    "title": "newer",
                    "html_url": "u3",
                    "closed_at": "2026-03-15T00:00:00Z",
                },
                {
                    "number": 2,
                    "title": "middle",
                    "html_url": "u2",
                    "closed_at": "2025-06-10T00:00:00Z",
                },
            ]
        }

    monkeypatch.setattr(file_issue, "gh_json", fake_gh_json)
    out = file_issue.find_closed_related_issues(
        "agorokh/template-repo",
        "deadbeef0000",  # pragma: allowlist secret
        "gh",
        limit=2,
    )
    assert [it["number"] for it in out] == [3, 2]


def test_issue_body_renders_related_closed_section() -> None:
    """The new 'Related closed issues' section must appear above the
    horizontal rule, link the closed peers, and include a YYYY-MM-DD
    closed-on date for context."""
    body = file_issue.issue_body(
        score=_sample_score(),
        source_repo="agorokh/template-repo",
        source_pr=99,
        closed_related=[
            {
                "number": 42,
                "title": "Old pain pattern",
                "html_url": "https://github.com/agorokh/template-repo/issues/42",
                "closed_at": "2025-12-01T10:00:00Z",
            }
        ],
    )
    assert "## Related closed issues" in body
    assert "[#42](https://github.com/agorokh/template-repo/issues/42)" in body
    assert "closed 2025-12-01" in body
    # No section when nothing to link.
    body_empty = file_issue.issue_body(
        score=_sample_score(), source_repo="a/b", source_pr=1, closed_related=[]
    )
    assert "## Related closed issues" not in body_empty


def test_file_or_update_issue_create_path_links_closed_related(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: when no OPEN issue matches but a CLOSED one does, the
    `created` path includes the closed peers in the body without
    reopening them."""
    monkeypatch.setattr(file_issue, "find_existing_issue", lambda *a, **k: None)
    monkeypatch.setattr(
        file_issue,
        "find_closed_related_issues",
        lambda *a, **k: [
            {
                "number": 7,
                "title": "Prior closed pain",
                "html_url": "https://github.com/agorokh/template-repo/issues/7",
                "closed_at": "2025-05-05T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(file_issue.shutil, "which", lambda _b: "/usr/bin/gh")

    captured_body: dict[str, str] = {}

    def fake_create(args: list[str], gh: str, body_input: str | None = None) -> str:
        captured_body["body"] = body_input or ""
        return "https://github.com/agorokh/template-repo/issues/4242\n"

    monkeypatch.setattr(file_issue, "_gh_run", fake_create)
    result = file_issue.file_or_update_issue(
        score=_sample_score(),
        source_repo="agorokh/template-repo",
        source_pr=99,
        target_repo="agorokh/template-repo",
        dry_run=False,
    )
    assert result["action"] == "created"
    assert result["number"] == 4242
    assert "## Related closed issues" in captured_body["body"]
    assert "#7" in captured_body["body"]


def test_issue_body_renders_breakdown_in_metric_weights_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (Qodo round-12 — Determinism): callers may build the
    `breakdown` dict in any key order (e.g., a hand-edited score JSON or
    a future-version producer). The rendered body MUST iterate
    `METRIC_WEIGHTS` first so two scorers producing the same numbers
    cannot diverge on whitespace alone, breaking dedup or polluting the
    issue history with phantom edits."""
    score = _sample_score()
    score["breakdown"] = {
        "ci_red_runs": 1,
        "commits_after_first_review": 5,
        "human_review_comments": 3,
    }
    body = file_issue.issue_body(
        score, source_repo="agorokh/template-repo", source_pr=1, closed_related=[]
    )
    pos_commits = body.index("`commits_after_first_review`")
    pos_human = body.index("`human_review_comments`")
    pos_ci = body.index("`ci_red_runs`")
    expected_order = [body.index(f"`{m}`") for m in pain_score.METRIC_WEIGHTS if f"`{m}`" in body]
    assert expected_order == sorted(expected_order), (
        "breakdown rows are not in METRIC_WEIGHTS order — Qodo round-12 finding"
    )
    assert pos_commits < pos_human < pos_ci


def test_issue_body_marks_unknown_metrics_explicitly() -> None:
    """Regression (Qodo round-12): unknown metrics in `breakdown` (e.g.,
    a future scorer adds `ci_flake_rate`) must NOT be silently dropped
    AND must NOT be silently mixed into the weighted total — render them
    after the known set with a literal `(unknown)` weight column so an
    operator can spot drift."""
    score = _sample_score()
    score["breakdown"]["future_metric_xyz"] = 99
    body = file_issue.issue_body(score, source_repo="a/b", source_pr=1, closed_related=[])
    assert "`future_metric_xyz`" in body
    assert "(unknown)" in body


def test_append_pr_to_body_handles_bullet_without_trailing_newline() -> None:
    """Regression (Qodo round-12): the prior regex required `- .+\\n`
    (bullets terminated by newline). A body whose last bullet has no
    trailing newline (manual edit, or a producer that strips them) would
    fall through and append a duplicate `## Linked PRs` heading. The new
    line-based parser tolerates either."""
    body = (
        "Some preamble.\n\n"
        "## Linked PRs\n\n"
        "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)"
    )
    out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
    assert out.count("## Linked PRs") == 1
    assert "[a/b#2]" in out


def test_append_pr_to_body_handles_section_followed_by_other_heading() -> None:
    """Regression (Qodo round-12): the new line-based parser must scan
    only WITHIN the `## Linked PRs` section — it must not eat content
    belonging to a later heading (`---` separator, `## Footnote`, etc.)
    nor insert the new bullet outside the section.
    """
    body = (
        "## Linked PRs\n\n"
        "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)\n\n"
        "## Footnote\n\n"
        "Auto-filed by tools/pr_pain.\n"
    )
    out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
    assert out.count("## Linked PRs") == 1
    assert out.count("## Footnote") == 1
    new_bullet_pos = out.index("[a/b#2]")
    footnote_pos = out.index("## Footnote")
    assert new_bullet_pos < footnote_pos, "new bullet leaked past the section boundary"


def test_append_pr_to_body_inserts_inside_section_not_past_footer() -> None:
    """Regression (Cursor Bugbot round-13): the line-based parser
    introduced in round-13 only recognized ATX headings as section
    boundaries, but the canonical ``issue_body`` output uses a ``---``
    thematic break + a ``<!-- pr_pain_fingerprint:... -->`` marker
    comment between ``## Linked PRs`` and EOF. Without those as
    boundaries, the new bullet gets appended at the very end of the body
    — AFTER the marker comment — instead of inside the Linked PRs
    section. The bullet would still be linkable (``[a/b#N]`` substring
    match works on idempotency) but the rendered issue is broken.
    """
    score: dict[str, Any] = {
        "level": "medium",
        "score": 14.0,
        "fingerprint": "a" * 12,  # pragma: allowlist secret
        "breakdown": {"commits_after_first_review": 5},
        "inputs": {"repo": "a/b", "pr": 1, "changed_top_dirs": ["scripts"], "title": "x"},
    }
    body = file_issue.issue_body(score, "a/b", 1, closed_related=[])
    out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
    bullet_pos = out.index("[a/b#2]")
    marker_pos = out.index("pr_pain_fingerprint")
    thematic_pos = out.index("\n---\n")
    assert bullet_pos < thematic_pos, (
        "new bullet leaked past the `---` thematic break — "
        "Cursor Bugbot round-13 regression resurfaced"
    )
    assert bullet_pos < marker_pos, "new bullet leaked past the fingerprint marker"
    assert out.count("## Linked PRs") == 1


def test_append_pr_to_body_handles_spaced_thematic_breaks() -> None:
    """Regression (Qodo round-15 #1): CommonMark §4.1 thematic breaks
    allow optional spaces between the chars (``- - -``, ``* * *``,
    ``___``). The original boundary check only matched compact runs
    (``---``), so a body using ``- - -`` would let the new bullet leak
    past the section into the footer."""
    for sep in ("- - -", "* * *", "_  _ _"):
        body = (
            "## Linked PRs\n\n"
            "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)\n\n"
            f"{sep}\n\n"
            "Footer line\n"
        )
        out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
        assert out.index("[a/b#2]") < out.index("Footer line"), (
            f"bullet leaked past spaced thematic break {sep!r}"
        )
        assert out.count("## Linked PRs") == 1


def test_append_pr_to_body_handles_setext_underline_inside_section() -> None:
    """Regression (Qodo round-15 #3): a setext underline (``---``/``===``
    directly under non-blank text) turns the line above into an H2/H1.
    If a manually-edited body has ``Some Heading\\n---\\n`` between
    the ``## Linked PRs`` heading and EOF, the parser must recognize
    that as the start of a new section and insert the bullet BEFORE the
    new heading line — not after the underline."""
    body = (
        "## Linked PRs\n\n"
        "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)\n\n"
        "Manually Added Section\n"
        "---\n\n"
        "Notes about the PR cluster.\n"
    )
    out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
    bullet_pos = out.index("[a/b#2]")
    new_heading_pos = out.index("Manually Added Section")
    assert bullet_pos < new_heading_pos, "bullet leaked past setext-underline-induced heading"
    assert out.count("Manually Added Section") == 1


def test_append_pr_to_body_treats_starred_thematic_break_without_blank_as_boundary() -> None:
    """Regression (Cursor Bugbot post-9620014 #1): ``***`` and ``___`` are
    *unambiguously* thematic breaks per CommonMark §4.1 — they have no
    setext-underline interpretation, so the ``prev_blank`` gating that
    ``---`` needs (to disambiguate from a setext H2) does not apply.

    The pre-fix code gated ALL break characters on ``prev_blank``, so a
    ``***``/``___`` directly under non-blank text was misclassified as
    non-boundary and the new bullet leaked past it."""
    for break_chars in ("***", "___", "* * *", "_ _ _"):
        body = (
            "## Linked PRs\n\n"
            "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)\n"
            f"Some text without blank line gap\n{break_chars}\n\n"
            "Footer content past the break.\n"
        )
        out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
        assert out.index("[a/b#2]") < out.index(break_chars), (
            f"bullet leaked past unambiguous thematic break {break_chars!r}"
        )


def test_append_pr_to_body_does_not_treat_gapped_setext_as_heading() -> None:
    """Regression (Cursor Bugbot post-9620014 #2): a setext underline
    requires the IMMEDIATELY preceding line to be non-blank. The pre-fix
    code tracked ``prev_nonblank`` (the most-recent non-blank line ever
    seen), so ``Foo\\n\\n===`` — a stray ``===`` line with a blank-line
    gap from any prose — was falsely classified as a setext H1
    underline and the bullet was inserted ABOVE the (non-existent)
    heading rather than at the proper end of the section."""
    body = (
        "## Linked PRs\n\n"
        "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)\n\n"
        "Some prose paragraph.\n\n"
        "===\n\n"
        "## Real Next Section\n"
    )
    out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
    bullet_pos = out.index("[a/b#2]")
    next_heading_pos = out.index("## Real Next Section")
    equals_pos = out.index("===")
    assert bullet_pos < next_heading_pos, "bullet leaked past real next heading"
    assert bullet_pos > out.index("[a/b#1]"), "bullet inserted before existing bullet"
    # The gapped ``===`` should NOT have been treated as a setext heading
    # — so it remains in the body, untouched, in the section that follows.
    assert equals_pos < next_heading_pos


def test_append_pr_to_body_handles_marker_only_footer() -> None:
    """Regression: the marker comment alone (no `---` thematic break,
    no `_Auto-filed_` footer line) must still be treated as a section
    boundary — operators may strip the prose footer over time."""
    body = (
        "## Linked PRs\n\n"
        "- [a/b#1](https://github.com/a/b/pull/1) — score 5.0 (medium)\n\n"
        "<!-- pr_pain_fingerprint: aaaaaaaaaaaa -->\n"  # pragma: allowlist secret
    )
    out = file_issue.append_pr_to_body(body, "a/b", 2, 6.0, "medium")
    assert out.index("[a/b#2]") < out.index("pr_pain_fingerprint")
    assert out.count("## Linked PRs") == 1


def test_run_gh_reframes_timeout_into_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (Qodo round-12 — Process/Timeouts): a hung `gh` call
    must surface as a clear `RuntimeError` mentioning the operation +
    the override knob, NOT a raw `subprocess.TimeoutExpired` that bubbles
    up to the workflow as a stack trace with no actionable hint."""
    import subprocess as _sp

    def fake_run(*_a: Any, **_kw: Any) -> Any:
        raise _sp.TimeoutExpired(cmd=["gh", "api", "test"], timeout=1.0)

    monkeypatch.setattr(pain_score.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError) as exc_info:
        pain_score._run_gh(["gh", "api", "test"], timeout=1.0, op="actions/runs")
    msg = str(exc_info.value)
    assert "timed out" in msg
    assert "actions/runs" in msg
    assert "PR_PAIN_GH_TIMEOUT_S" in msg or "PR_PAIN_GH_PAGINATED_TIMEOUT_S" in msg


def test_gh_json_passes_timeout_to_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: every `gh_json` call must enforce a timeout — if the
    plumbing skips the kwarg, `_run_gh` becomes a no-op safety net.
    """
    seen: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        seen["timeout"] = kwargs.get("timeout")

        class Result:
            returncode = 0
            stdout = '{"ok": true}'
            stderr = ""

        return Result()

    monkeypatch.setattr(pain_score.subprocess, "run", fake_run)
    pain_score.gh_json(["api", "user"], "/usr/bin/gh")
    assert isinstance(seen["timeout"], (int, float))
    assert seen["timeout"] > 0


def test_file_or_update_issue_dry_run_create_shape_matches_docstring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression (Qodo): the docstring promises the `would-create` shape
    is `{action, title, labels, body_preview, closed_related_count}`. A
    drift between docstring and code (caller expecting `body` and
    silently getting `body_preview`) would show up as a `KeyError` deep
    in the operator's preview script — better to lock the contract here.
    """
    monkeypatch.setattr(file_issue, "find_existing_issue", lambda *a, **k: None)
    monkeypatch.setattr(file_issue, "find_closed_related_issues", lambda *a, **k: [])
    monkeypatch.setattr(file_issue.shutil, "which", lambda _b: "/usr/bin/gh")
    result = file_issue.file_or_update_issue(
        score=_sample_score(),
        source_repo="agorokh/template-repo",
        source_pr=42,
        target_repo="agorokh/template-repo",
        dry_run=True,
    )
    assert result["action"] == "would-create"
    expected_keys = {"action", "title", "labels", "body_preview", "closed_related_count"}
    assert set(result.keys()) == expected_keys, (
        f"would-create shape drifted from docstring: missing="
        f"{expected_keys - set(result.keys())}, extra="
        f"{set(result.keys()) - expected_keys}"
    )
    assert isinstance(result["body_preview"], str)
    assert len(result["body_preview"]) <= 500
    assert isinstance(result["closed_related_count"], int)


def test_file_or_update_issue_rejects_non_mapping_inputs() -> None:
    with pytest.raises(ValueError, match="inputs"):
        file_issue.file_or_update_issue(
            score={
                "level": "high",
                "score": 30.0,
                "fingerprint": "x" * 12,  # pragma: allowlist secret
                "breakdown": {},
                "inputs": "not a dict",
            },
            source_repo="a/b",
            source_pr=1,
            target_repo="a/b",
            dry_run=True,
        )


def test_main_rejects_malformed_score(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"score": 30, "inputs": {"repo": "a/b", "pr": 1}}))
    monkeypatch.setattr(file_issue.shutil, "which", lambda _b: "/usr/bin/gh")
    rc = file_issue.main(["--score-file", str(bad), "--target-repo", "a/b", "--dry-run"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "malformed" in err


def test_main_reads_score_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    score_file = tmp_path / "pain.json"
    score_file.write_text(json.dumps(_sample_score()))
    monkeypatch.setattr(file_issue.shutil, "which", lambda _bin: "/usr/bin/gh")
    monkeypatch.setattr(file_issue, "find_existing_issue", lambda *a, **k: None)
    monkeypatch.setattr(file_issue, "find_closed_related_issues", lambda *a, **k: [])
    rc = file_issue.main(
        [
            "--score-file",
            str(score_file),
            "--target-repo",
            "agorokh/template-repo",
            "--dry-run",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "would-create"
