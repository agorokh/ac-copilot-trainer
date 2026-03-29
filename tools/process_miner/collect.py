"""Data collection pipeline for PRs, comments, and CI status."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.github_client import GitHubClient
from tools.process_miner.schemas import (
    CIStatus,
    LinkedIssue,
    PRData,
    PRFile,
    ReviewComment,
)


def parse_datetime(s: str | None) -> datetime | None:
    """Parse ISO datetime string (UTC if Z suffix)."""
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def collect_pr_data(
    client: GitHubClient,
    owner: str,
    repo: str,
    since: datetime,
    max_prs: int = 50,
    cache_dir: Path | None = None,
    *,
    max_pages: int = 20,
) -> list[PRData]:
    """Collect PR data from GitHub."""
    base_branch = client.get_default_branch(owner, repo)
    print(f"Using base branch: {base_branch}")

    print(f"Fetching merged PRs since {since.isoformat()}...")
    prs_raw = client.get_merged_prs(
        owner, repo, since, max_prs, base_branch=base_branch, max_pages=max_pages
    )
    print(f"Found {len(prs_raw)} merged PRs")

    pr_data_list: list[PRData] = []

    for i, pr_raw in enumerate(prs_raw, 1):
        pr_number = int(pr_raw["number"])
        print(f"  [{i}/{len(prs_raw)}] Processing PR #{pr_number}: {pr_raw['title'][:50]}...")

        files_raw = client.get_pr_files(owner, repo, pr_number, max_pages=max_pages)
        files = [
            PRFile(
                path=str(f["filename"]),
                additions=int(f.get("additions", 0)),
                deletions=int(f.get("deletions", 0)),
            )
            for f in files_raw
        ]

        review_comments_raw = client.get_pr_review_comments(
            owner, repo, pr_number, max_pages=max_pages
        )
        review_comments = [
            ReviewComment(
                id=str(c["id"]),
                body=c.get("body", "") or "",
                author=c["user"]["login"] if c.get("user") else "unknown",
                created_at=parse_datetime(c.get("created_at")) or datetime.now(UTC),
                path=c.get("path"),
                line=c.get("line"),
                pr_number=pr_number,
                is_inline=True,
            )
            for c in review_comments_raw
        ]

        reviews_raw = client.get_pr_reviews(owner, repo, pr_number, max_pages=max_pages)
        for review in reviews_raw:
            if review.get("body"):
                review_comments.append(
                    ReviewComment(
                        id=f"review_{review['id']}",
                        body=str(review["body"]),
                        author=review["user"]["login"] if review.get("user") else "unknown",
                        created_at=parse_datetime(
                            review.get("submitted_at") or review.get("created_at")
                        )
                        or datetime.now(UTC),
                        pr_number=pr_number,
                        is_inline=False,
                    )
                )

        issue_comments_raw = client.get_pr_issue_comments(
            owner, repo, pr_number, max_pages=max_pages
        )
        issue_comments = [
            ReviewComment(
                id=str(c["id"]),
                body=c.get("body", "") or "",
                author=c["user"]["login"] if c.get("user") else "unknown",
                created_at=parse_datetime(c.get("created_at")) or datetime.now(UTC),
                pr_number=pr_number,
                is_inline=False,
            )
            for c in issue_comments_raw
        ]

        ci_status: CIStatus | None = None
        try:
            check_runs = client.get_pr_check_runs(owner, repo, pr_number, pr_summary=pr_raw)
            if check_runs and "check_runs" in check_runs:
                runs = check_runs["check_runs"]
                if runs:
                    # GitHub check-run conclusions include success, failure, neutral, cancelled,
                    # skipped, timed_out, action_required, stale (REST Check Run API).
                    conclusions = [r.get("conclusion") for r in runs if r.get("conclusion")]
                    statuses = [r.get("status") for r in runs if r.get("status")]

                    conclusion = "success"
                    if any(c in conclusions for c in ("failure", "timed_out", "action_required")):
                        conclusion = "failure"
                    elif "cancelled" in conclusions:
                        conclusion = "cancelled"
                    elif "pending" in statuses or "in_progress" in statuses:
                        conclusion = "pending"
                    elif "stale" in conclusions:
                        conclusion = "pending"

                    ci_status = CIStatus(
                        conclusion=conclusion,
                        status=statuses[0] if statuses else "completed",
                        jobs=[
                            {"name": r.get("name"), "conclusion": r.get("conclusion")} for r in runs
                        ],
                    )
        except Exception as e:
            import requests

            if isinstance(e, requests.RequestException):
                print(f"    Warning: Could not fetch CI status: {e}")
            else:
                raise

        linked_issues_raw = client.get_linked_issues(owner, repo, pr_number, pr_summary=pr_raw)
        linked_issues = [
            LinkedIssue(
                number=int(issue["number"]),
                title=str(issue.get("title", "")),
                state=str(issue.get("state", "open")),
            )
            for issue in linked_issues_raw
        ]

        created = parse_datetime(pr_raw.get("created_at"))
        merged = parse_datetime(pr_raw.get("merged_at"))

        pr_data = PRData(
            number=pr_number,
            title=str(pr_raw["title"]),
            author=pr_raw["user"]["login"] if pr_raw.get("user") else "unknown",
            created_at=created or datetime.now(UTC),
            merged_at=merged,
            body=pr_raw.get("body", "") or "",
            files=files,
            review_comments=review_comments,
            issue_comments=issue_comments,
            ci_status=ci_status,
            linked_issues=linked_issues,
        )

        pr_data_list.append(pr_data)

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{since.date()}_{owner}_{repo}_raw.json"

        cache_data = {
            "prs": [
                {
                    "number": pr.number,
                    "title": pr.title,
                    "author": pr.author,
                    "created_at": pr.created_at.isoformat() if pr.created_at else None,
                    "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                    "body": pr.body,
                    "files": [
                        {"path": f.path, "additions": f.additions, "deletions": f.deletions}
                        for f in pr.files
                    ],
                    "review_comments": [
                        {
                            "id": c.id,
                            "body": c.body,
                            "author": c.author,
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                            "path": c.path,
                            "line": c.line,
                            "pr_number": c.pr_number,
                            "is_inline": c.is_inline,
                        }
                        for c in pr.review_comments
                    ],
                    "issue_comments": [
                        {
                            "id": c.id,
                            "body": c.body,
                            "author": c.author,
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                            "pr_number": c.pr_number,
                        }
                        for c in pr.issue_comments
                    ],
                    "ci_status": {
                        "conclusion": pr.ci_status.conclusion,
                        "status": pr.ci_status.status,
                        "jobs": pr.ci_status.jobs,
                    }
                    if pr.ci_status
                    else None,
                    "linked_issues": [
                        {"number": li.number, "title": li.title, "state": li.state}
                        for li in pr.linked_issues
                    ],
                }
                for pr in pr_data_list
            ],
        }

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        print(f"Cached raw data to {cache_file}")

    return pr_data_list
