"""Data schemas for process miner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PRFile:
    """File changed in a PR."""

    path: str
    additions: int
    deletions: int


@dataclass
class ReviewComment:
    """Review comment (inline or general)."""

    id: str
    body: str
    author: str
    created_at: datetime | None = None  # May be None if not available
    path: str | None = None  # File path for inline comments
    line: int | None = None  # Line number for inline comments
    pr_number: int | None = None
    is_inline: bool = False


@dataclass
class CIStatus:
    """CI status snapshot."""

    conclusion: str  # success, failure, cancelled, etc.
    status: str  # completed, in_progress, queued
    jobs: list[dict[str, Any]] = field(default_factory=list)  # Job details if available


@dataclass
class LinkedIssue:
    """Linked issue from PR."""

    number: int
    title: str
    state: str


@dataclass
class PRData:
    """Complete PR data."""

    number: int
    title: str
    author: str
    created_at: datetime
    merged_at: datetime | None
    body: str
    files: list[PRFile] = field(default_factory=list)
    review_comments: list[ReviewComment] = field(default_factory=list)
    issue_comments: list[ReviewComment] = field(default_factory=list)
    ci_status: CIStatus | None = None
    linked_issues: list[LinkedIssue] = field(default_factory=list)


@dataclass
class CommentCluster:
    """Cluster of similar comments."""

    cluster_id: int
    title: str
    count: int
    comments: list[ReviewComment]
    affected_files: list[str]  # Top 5 file paths
    severity: str  # bug, reliability, security, perf, maintainability, nit
    preventability: str  # automation, guideline, agent_rule, architecture
    representative_examples: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Complete analysis result."""

    prs: list[PRData]
    clusters: list[CommentCluster]
    ci_failures: list[dict[str, Any]]
    churned_files: list[dict[str, Any]]  # Files with most comments
    stats: dict[str, Any]
