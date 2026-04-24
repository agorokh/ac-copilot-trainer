"""GitHub client unit tests (no network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tools.process_miner.github_client import DEFAULT_TIMEOUT_S, GitHubClient


def test_make_request_uses_timeout() -> None:
    with patch("tools.process_miner.github_client.GitHubClient.__init__", return_value=None):
        client = GitHubClient.__new__(GitHubClient)  # type: ignore[misc]
        client.base_url = "https://api.github.com"
        client.session = MagicMock()
        client.rate_limit_remaining = 5000
        client.rate_limit_reset = 0
        client._check_rate_limit = MagicMock()

        mock_response = MagicMock()
        mock_response.headers = {}
        mock_response.json.return_value = {"default_branch": "main"}
        mock_response.raise_for_status = MagicMock()
        client.session.get.return_value = mock_response

        GitHubClient._make_request(client, "/repos/o/r")  # type: ignore[arg-type]

        client.session.get.assert_called_once()
        _args, kwargs = client.session.get.call_args
        assert kwargs.get("timeout") == DEFAULT_TIMEOUT_S


def test_make_paginated_request_respects_max_pages() -> None:
    with patch("tools.process_miner.github_client.GitHubClient.__init__", return_value=None):
        client = GitHubClient.__new__(GitHubClient)  # type: ignore[misc]
        client.base_url = "https://api.github.com"
        client.session = MagicMock()
        client.rate_limit_remaining = 5000
        client.rate_limit_reset = 0
        client._check_rate_limit = MagicMock()

        page = {"n": 0}

        def _fake_request(_endpoint: str, params: dict | None = None) -> list[dict[str, str]]:
            page["n"] += 1
            return [{"id": f"{page['n']}-{i}"} for i in range(100)]

        client._make_request = MagicMock(side_effect=_fake_request)

        out = GitHubClient._make_paginated_request(client, "/x", max_pages=2)  # type: ignore[arg-type]
        assert len(out) == 200
        assert client._make_request.call_count == 2


def test_get_branch_tip_one_request() -> None:
    with patch("tools.process_miner.github_client.GitHubClient.__init__", return_value=None):
        client = GitHubClient.__new__(GitHubClient)  # type: ignore[misc]
        client.base_url = "https://api.github.com"
        client.session = MagicMock()
        client.rate_limit_remaining = 5000
        client.rate_limit_reset = 0
        client._check_rate_limit = MagicMock()

        client._make_request = MagicMock(
            return_value={
                "name": "main",
                "commit": {
                    "sha": "abccommit",
                    "commit": {"tree": {"sha": "treesha42"}},
                },
            }
        )

        tip, tree = GitHubClient.get_branch_tip(client, "o", "r", "main")  # type: ignore[arg-type]
        assert tip == "abccommit"
        assert tree == "treesha42"
        client._make_request.assert_called_once_with("/repos/o/r/branches/main")
