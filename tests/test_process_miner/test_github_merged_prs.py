"""``get_merged_prs`` pagination behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from tools.process_miner.github_client import GitHubClient


def test_get_merged_prs_pages_until_short_page() -> None:
    merged_pr = {
        "number": 1,
        "title": "t",
        "user": {"login": "u"},
        "body": "",
        "created_at": "2026-01-01T00:00:00Z",
        "merged_at": "2026-01-10T00:00:00Z",
    }

    with patch.object(GitHubClient, "__init__", lambda self, token=None: None):
        c = GitHubClient.__new__(GitHubClient)
    c.base_url = "https://api.github.com"
    c.session = MagicMock()
    c.rate_limit_remaining = 5000
    c.rate_limit_reset = 0
    c._check_rate_limit = MagicMock()
    import requests as requests_mod

    c._requests = requests_mod

    calls = {"n": 0}

    def fake_make(endpoint: str, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [merged_pr] * 100
        return [merged_pr]

    c._make_request = MagicMock(side_effect=fake_make)

    since = datetime(2026, 1, 1, tzinfo=UTC)
    prs = GitHubClient.get_merged_prs(c, "o", "r", since, max_prs=200, max_pages=5)
    assert len(prs) >= 100
    assert c._make_request.call_count == 2
