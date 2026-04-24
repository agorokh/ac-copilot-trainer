"""Tests for vault audit / health scoring (#73)."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.process_miner.schemas import CommentCluster, PRData, PRFile, ReviewComment
from tools.process_miner.vault_audit import (
    VaultAuditResult,
    collect_vault_audit,
    extract_relates_to,
    parse_simple_frontmatter,
    render_vault_health_markdown,
)


def test_parse_simple_frontmatter_type_status() -> None:
    text = """---
type: decision
status: active
---
# Title
body
"""
    meta, body = parse_simple_frontmatter(text)
    assert meta["type"] == "decision"
    assert meta["status"] == "active"
    assert body.startswith("# Title")


def test_extract_relates_to_list() -> None:
    text = """---
type: handoff
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - 00_Graph_Schema.md
---
# X
"""
    rel = extract_relates_to(text)
    assert "AcCopilotTrainer/00_System/Current Focus.md" in rel
    assert "00_Graph_Schema.md" in rel


def test_render_vault_health_markdown_includes_score() -> None:
    audit = VaultAuditResult(
        repo="o/r",
        vault_exists=True,
        tree_truncated=False,
        nodes=[],
        health_score=42,
        freshness_score=0.5,
        depth_score=0.5,
        frontmatter_score=0.5,
        connectivity_score=0.5,
        coverage_score=0.5,
        coverage_gaps=["gap a"],
        broken_links=[],
        broken_links_total=0,
        save_compliant_prs=2,
        save_total_prs=4,
        save_rate=0.5,
        handoff_last_updated=datetime(2026, 1, 2, tzinfo=UTC),
        last_pr_merged_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    md = "\n".join(render_vault_health_markdown(audit))
    assert "42/100" in md
    assert "gap a" in md
    assert "2/4" in md


def test_collect_vault_audit_mocked_client() -> None:
    """Smoke: mocked GitHub responses produce a bounded audit."""

    class MC:
        def get_branch_tip(self, owner: str, repo: str, branch: str) -> tuple[str, str]:
            return ("tipsha", "troot")

        def get_recursive_tree(self, owner: str, repo: str, tree_sha: str):
            return (
                [
                    {
                        "path": "docs/01_Vault/AcCopilotTrainer/x.md",
                        "type": "blob",
                        "sha": "abc",
                    }
                ],
                False,
            )

        def get_contents_text(self, owner: str, repo: str, path: str, *, ref: str) -> str:
            return """---
type: note
status: active
---
hello
"""

        def get_latest_commit_for_path(self, owner: str, repo: str, path: str, *, ref: str):
            return {
                "commit": {
                    "committer": {"date": "2026-01-15T12:00:00Z"},
                }
            }

        def list_commits_for_path(self, *args: object, **kwargs: object) -> list[dict]:
            return []

    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=datetime(2026, 1, 10, tzinfo=UTC),
        body="",
        merge_commit_sha="abc123",
        files=[
            PRFile(
                path="docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md",
                additions=1,
                deletions=0,
            )
        ],
    )
    cluster = CommentCluster(
        cluster_id=1,
        title="xss in form",
        count=2,
        comments=[
            ReviewComment(
                id="1",
                body="security issue",
                author="u",
                author_type="human",
                pr_number=1,
            )
        ],
        affected_files=["a.py"],
        severity="security",
        preventability="guideline",
    )
    audit = collect_vault_audit(
        MC(),  # type: ignore[arg-type]
        "o",
        "r",
        branch="main",
        prs=[pr],
        clusters=[cluster],
        max_md_files=10,
    )
    assert audit.vault_exists
    assert len(audit.nodes) == 1
    assert audit.save_compliant_prs == 1
    assert audit.save_total_prs == 1
    assert audit.coverage_gaps


def test_broken_relates_to_single_segment_target() -> None:
    """Missing single-segment relates_to targets (no '/') are flagged as broken."""

    class MC:
        def get_branch_tip(self, owner: str, repo: str, branch: str) -> tuple[str, str]:
            return ("tipsha", "troot")

        def get_recursive_tree(self, owner: str, repo: str, tree_sha: str):
            return (
                [
                    {
                        "path": "docs/01_Vault/AcCopilotTrainer/x.md",
                        "type": "blob",
                        "sha": "abc",
                    }
                ],
                False,
            )

        def get_contents_text(self, owner: str, repo: str, path: str, *, ref: str) -> str:
            return """---
type: note
status: active
relates_to:
  - 00_Graph_Schema.md
---
body
"""

        def get_latest_commit_for_path(self, owner: str, repo: str, path: str, *, ref: str):
            return None

        def list_commits_for_path(self, *args: object, **kwargs: object) -> list[dict]:
            return []

    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=None,
        body="",
    )
    audit = collect_vault_audit(
        MC(),  # type: ignore[arg-type]
        "o",
        "r",
        branch="main",
        prs=[pr],
        clusters=[],
        max_md_files=10,
    )
    assert any("00_Graph_Schema.md" in b for b in audit.broken_links)


def test_save_24h_commit_after_merge_counts_when_pr_files_miss_session_paths() -> None:
    """SAVE uses commits API when the merge commit's PR file list omits session paths."""

    class MC:
        def get_branch_tip(self, owner: str, repo: str, branch: str) -> tuple[str, str]:
            return ("tipsha", "troot")

        def get_recursive_tree(self, owner: str, repo: str, tree_sha: str):
            return (
                [
                    {
                        "path": "docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md",
                        "type": "blob",
                        "sha": "abc",
                    }
                ],
                False,
            )

        def get_contents_text(self, owner: str, repo: str, path: str, *, ref: str) -> str:
            return "---\ntype: note\nstatus: active\n---\n"

        def get_latest_commit_for_path(self, owner: str, repo: str, path: str, *, ref: str):
            return {
                "commit": {
                    "committer": {"date": "2026-01-15T12:00:00Z"},
                }
            }

        def list_commits_for_path(self, *args: object, **kwargs: object) -> list[dict]:
            return [
                {
                    "commit": {
                        "committer": {"date": "2026-01-05T10:00:00Z"},
                    }
                }
            ]

    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        body="",
        merge_commit_sha="abc123",
        files=[PRFile(path="README.md", additions=1, deletions=0)],
    )
    audit = collect_vault_audit(
        MC(),  # type: ignore[arg-type]
        "o",
        "r",
        branch="main",
        prs=[pr],
        clusters=[],
        max_md_files=10,
    )
    assert audit.save_compliant_prs == 1
    assert audit.save_total_prs == 1


def test_save_session_paths_match_case_insensitively() -> None:
    """SAVE 24h path queries use the same case rules as marker prioritization."""

    class MC:
        def get_branch_tip(self, owner: str, repo: str, branch: str) -> tuple[str, str]:
            return ("tipsha", "troot")

        def get_recursive_tree(self, owner: str, repo: str, tree_sha: str):
            return (
                [
                    {
                        "path": "docs/01_Vault/AcCopilotTrainer/00_System/next session handoff.md",
                        "type": "blob",
                        "sha": "abc",
                    }
                ],
                False,
            )

        def get_contents_text(self, owner: str, repo: str, path: str, *, ref: str) -> str:
            return "---\ntype: note\nstatus: active\n---\n"

        def get_latest_commit_for_path(self, owner: str, repo: str, path: str, *, ref: str):
            return {
                "commit": {
                    "committer": {"date": "2026-01-15T12:00:00Z"},
                }
            }

        def list_commits_for_path(self, *args: object, **kwargs: object) -> list[dict]:
            path = kwargs.get("path") or (args[2] if len(args) > 2 else "")
            assert "next session handoff" in str(path).lower()
            return [
                {
                    "commit": {
                        "committer": {"date": "2026-01-05T10:00:00Z"},
                    }
                }
            ]

    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC),
        body="",
        merge_commit_sha="abc123",
        files=[PRFile(path="README.md", additions=1, deletions=0)],
    )
    audit = collect_vault_audit(
        MC(),  # type: ignore[arg-type]
        "o",
        "r",
        branch="main",
        prs=[pr],
        clusters=[],
        max_md_files=10,
    )
    assert audit.save_compliant_prs == 1


def test_session_marker_paths_included_before_md_cap_truncates_rest() -> None:
    """Session marker vault files are scanned before applying ``max_md_files`` truncation."""

    class MC:
        def get_branch_tip(self, owner: str, repo: str, branch: str) -> tuple[str, str]:
            return ("tip", "root")

        def get_recursive_tree(self, owner: str, repo: str, tree_sha: str):
            handoff = "docs/01_Vault/AcCopilotTrainer/zz_Last/Next Session Handoff.md"
            noise = [f"docs/01_Vault/AcCopilotTrainer/p{i:03d}.md" for i in range(50)]
            entries = [{"path": p, "type": "blob", "sha": "a"} for p in [*noise, handoff]]
            return (entries, False)

        def get_contents_text(self, owner: str, repo: str, path: str, *, ref: str) -> str:
            return "---\ntype: note\nstatus: active\n---\n"

        def get_latest_commit_for_path(self, owner: str, repo: str, path: str, *, ref: str):
            return None

        def list_commits_for_path(self, *args: object, **kwargs: object) -> list[dict]:
            return []

    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        merged_at=None,
        body="",
    )
    audit = collect_vault_audit(
        MC(),  # type: ignore[arg-type]
        "o",
        "r",
        branch="main",
        prs=[pr],
        clusters=[],
        max_md_files=5,
    )
    paths = {n.path for n in audit.nodes}
    assert any("Next Session Handoff.md" in p for p in paths)
    assert len(paths) == 5


def test_vault_node_frontmatter_ok_requires_type_and_status() -> None:
    meta, _ = parse_simple_frontmatter(
        "---\ntype: x\n---\n",
    )
    assert "status" not in meta
