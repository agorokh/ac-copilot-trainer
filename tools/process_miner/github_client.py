"""GitHub API client for fetching PR data."""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# All HTTP calls use this timeout (seconds) to avoid hanging workers.
DEFAULT_TIMEOUT_S = 30


class GitHubClient:
    """GitHub API client with rate limiting.

    **API strategy (REST vs GraphQL):** This client uses the REST API with one
    request per resource (PR list, files, comments, checks, linked issues). A
    GraphQL batch could reduce round-trips but adds query complexity and
    pagination coupling; we keep REST for clarity and document the trade-off
    here. Revisit if rate limits or latency become a bottleneck.
    """

    def __init__(self, token: str | None = None) -> None:
        """Initialize client with token."""
        import requests as requests_mod

        self._requests = requests_mod
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GITHUB_TOKEN environment variable or token argument required")
        self.base_url = "https://api.github.com"
        self.session = requests_mod.Session()
        self.session.headers.update(
            {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        self.rate_limit_remaining = 5000
        self.rate_limit_reset = 0

    def get_default_branch(self, owner: str, repo: str) -> str:
        """Get the default branch for the repository."""
        repo_data = self._make_request(f"/repos/{owner}/{repo}")
        return str(repo_data.get("default_branch", "main"))

    def _check_rate_limit(self) -> None:
        """Check and wait for rate limit if needed."""
        if self.rate_limit_remaining < 10:
            reset_time = self.rate_limit_reset
            if reset_time > time.time():
                wait_seconds = reset_time - time.time() + 1
                print(f"Rate limit low, waiting {wait_seconds:.0f} seconds...")
                time.sleep(wait_seconds)

    def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """Make a GitHub API request with rate limiting."""
        self._check_rate_limit()
        url = f"{self.base_url}{endpoint}"
        response = self.session.get(url, params=params, timeout=DEFAULT_TIMEOUT_S)

        if "X-RateLimit-Remaining" in response.headers:
            self.rate_limit_remaining = int(response.headers["X-RateLimit-Remaining"])
        if "X-RateLimit-Reset" in response.headers:
            self.rate_limit_reset = int(response.headers["X-RateLimit-Reset"])

        response.raise_for_status()
        return response.json()

    def _make_paginated_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Make paginated request, collecting pages up to ``max_pages``."""
        all_items: list[dict[str, Any]] = []
        page = 1
        per_page = 100

        req_params: dict[str, Any] = {**(params or {})}
        req_params["per_page"] = per_page

        while page <= max_pages:
            req_params["page"] = page
            data = self._make_request(endpoint, req_params)
            if not data:
                break
            if not isinstance(data, list):
                break
            all_items.extend(data)
            if len(data) < per_page:
                break
            page += 1

        return all_items

    def get_merged_prs(
        self,
        owner: str,
        repo: str,
        since: datetime,
        max_prs: int = 50,
        base_branch: str = "main",
        *,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Get merged PRs since a date (merged_at >= since, timezone-aware)."""
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)

        endpoint = f"/repos/{owner}/{repo}/pulls"
        params: dict[str, Any] = {
            "state": "closed",
            "sort": "updated",
            "direction": "desc",
            "base": base_branch,
        }

        prs: list[dict[str, Any]] = []
        page = 1
        per_page = 100

        while len(prs) < max_prs and page <= max_pages:
            params["page"] = page
            params["per_page"] = per_page
            data = self._make_request(endpoint, params)

            if not data:
                break

            for pr in data:
                merged_at_raw = pr.get("merged_at")
                if merged_at_raw:
                    merged_at = datetime.fromisoformat(str(merged_at_raw).replace("Z", "+00:00"))
                    if merged_at >= since:
                        prs.append(pr)

            if len(data) < per_page:
                break
            page += 1

        return prs[:max_prs]

    def get_pr_files(
        self, owner: str, repo: str, pr_number: int, *, max_pages: int = 20
    ) -> list[dict[str, Any]]:
        """Get files changed in a PR."""
        endpoint = f"/repos/{owner}/{repo}/pulls/{pr_number}/files"
        return self._make_paginated_request(endpoint, max_pages=max_pages)

    def get_pr_reviews(
        self, owner: str, repo: str, pr_number: int, *, max_pages: int = 20
    ) -> list[dict[str, Any]]:
        """Get review comments for a PR."""
        endpoint = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        return self._make_paginated_request(endpoint, max_pages=max_pages)

    def get_pr_review_comments(
        self, owner: str, repo: str, pr_number: int, *, max_pages: int = 20
    ) -> list[dict[str, Any]]:
        """Get inline review comments for a PR."""
        endpoint = f"/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        return self._make_paginated_request(endpoint, max_pages=max_pages)

    def get_pr_issue_comments(
        self, owner: str, repo: str, pr_number: int, *, max_pages: int = 20
    ) -> list[dict[str, Any]]:
        """Get issue comments on a PR."""
        endpoint = f"/repos/{owner}/{repo}/issues/{pr_number}/comments"
        return self._make_paginated_request(endpoint, max_pages=max_pages)

    def get_pr_check_runs(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        pr_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get CI check runs for a PR.

        If ``pr_summary`` is the PR object already returned by the pulls list API,
        ``head.sha`` is read from it and the extra ``GET .../pulls/{n}`` call is skipped.
        """
        if pr_summary is not None:
            head_sha = pr_summary["head"]["sha"]
        else:
            pr_data = self._make_request(f"/repos/{owner}/{repo}/pulls/{pr_number}")
            head_sha = pr_data["head"]["sha"]

        endpoint = f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs"
        return self._make_request(endpoint)

    def get_linked_issues(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        pr_summary: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract linked issues from PR body/title.

        Pass ``pr_summary`` from the pulls list response to avoid re-fetching the PR.
        """
        if pr_summary is not None:
            body = pr_summary.get("body", "") or ""
            title = pr_summary.get("title", "") or ""
        else:
            pr_data = self._make_request(f"/repos/{owner}/{repo}/pulls/{pr_number}")
            body = pr_data.get("body", "") or ""
            title = pr_data.get("title", "") or ""
        text = f"{title} {body}"

        issue_numbers = set(re.findall(r"#(\d+)", text))

        issues: list[dict[str, Any]] = []
        for issue_num in sorted(issue_numbers, key=int):
            try:
                issue = self._make_request(f"/repos/{owner}/{repo}/issues/{issue_num}")
                if issue.get("pull_request") is None:
                    issues.append(issue)
            except self._requests.HTTPError:
                continue

        return issues
