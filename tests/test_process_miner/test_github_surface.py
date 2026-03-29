"""Exercise ``GitHubClient`` public methods with mocked ``_make_request``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tools.process_miner.github_client import GitHubClient


def _bare_client() -> GitHubClient:
    with patch.object(GitHubClient, "__init__", lambda self, token=None: None):
        c = GitHubClient.__new__(GitHubClient)
    c.base_url = "https://api.github.com"
    c.session = MagicMock()
    c.rate_limit_remaining = 5000
    c.rate_limit_reset = 0
    c._check_rate_limit = MagicMock()
    import requests as requests_mod

    c._requests = requests_mod
    return c


def test_get_default_branch() -> None:
    c = _bare_client()
    c._make_request = MagicMock(return_value={"default_branch": "dev"})
    assert GitHubClient.get_default_branch(c, "o", "r") == "dev"


def test_get_pr_files_delegates() -> None:
    c = _bare_client()
    c._make_paginated_request = MagicMock(return_value=[{"filename": "a.py"}])
    out = GitHubClient.get_pr_files(c, "o", "r", 1)
    assert out == [{"filename": "a.py"}]
    c._make_paginated_request.assert_called_once()


def test_get_pr_check_runs() -> None:
    c = _bare_client()

    def fake_make(endpoint: str, params=None):
        if endpoint.endswith("/pulls/9"):
            return {"head": {"sha": "abc"}}
        if "/commits/abc/check-runs" in endpoint:
            return {"check_runs": [{"name": "ci", "conclusion": "success", "status": "completed"}]}
        raise AssertionError(endpoint)

    c._make_request = MagicMock(side_effect=fake_make)
    data = GitHubClient.get_pr_check_runs(c, "o", "r", 9)
    assert "check_runs" in data


def test_get_pr_check_runs_skips_pr_fetch_when_summary_given() -> None:
    c = _bare_client()
    c._make_request = MagicMock(return_value={"check_runs": []})
    summary = {"head": {"sha": "abc123"}}
    GitHubClient.get_pr_check_runs(c, "o", "r", 9, pr_summary=summary)
    c._make_request.assert_called_once()
    assert c._make_request.call_args[0][0] == "/repos/o/r/commits/abc123/check-runs"


def test_get_linked_issues_filters_prs() -> None:
    c = _bare_client()

    def fake_make(endpoint: str, params=None):
        if endpoint.endswith("/pulls/2"):
            return {"title": "x", "body": "closes #3"}
        if endpoint.endswith("/issues/3"):
            return {"number": 3, "title": "issue", "pull_request": None}
        raise AssertionError(endpoint)

    c._make_request = MagicMock(side_effect=fake_make)
    issues = GitHubClient.get_linked_issues(c, "o", "r", 2)
    assert len(issues) == 1


def test_get_linked_issues_skips_pr_fetch_when_summary_given() -> None:
    c = _bare_client()

    def fake_make(endpoint: str, params=None):
        if endpoint.endswith("/issues/3"):
            return {"number": 3, "title": "issue", "pull_request": None}
        raise AssertionError(endpoint)

    c._make_request = MagicMock(side_effect=fake_make)
    summary = {"title": "x", "body": "closes #3"}
    issues = GitHubClient.get_linked_issues(c, "o", "r", 2, pr_summary=summary)
    assert len(issues) == 1
