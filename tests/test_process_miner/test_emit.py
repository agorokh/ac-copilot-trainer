"""Tests for deterministic rule emission."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.emit import _paths_to_globs, _rule_fingerprint, emit_learned_artifacts
from tools.process_miner.schemas import AnalysisResult, CommentCluster, ReviewComment


def _cluster(count: int = 3) -> CommentCluster:
    comments = [
        ReviewComment(
            id=str(i),
            body="Please add type hints to this public API surface for clarity.",
            author="reviewer",
            created_at=datetime.now(UTC),
            path="src/project_template/__init__.py",
            line=10 + i,
            pr_number=100 + i,
            is_inline=True,
        )
        for i in range(count)
    ]
    return CommentCluster(
        cluster_id=0,
        title="type / hints / annotation",
        count=count,
        comments=comments,
        affected_files=["src/project_template/__init__.py"],
        severity="maintainability",
        preventability="typecheck",
        representative_examples=[c.body for c in comments[:3]],
    )


def test_paths_to_globs_posix_and_segments() -> None:
    assert _paths_to_globs(["Makefile"]) == ["**/Makefile"]
    assert _paths_to_globs(["src/pkg/mod.py"]) == ["src/**/*"]
    assert _paths_to_globs(["src/a.py", "Makefile"]) == ["src/**/*", "**/Makefile"]


def test_rule_fingerprint_stable() -> None:
    c1 = _cluster()
    c2 = _cluster()
    assert _rule_fingerprint(c1) == _rule_fingerprint(c2)


def test_emit_writes_and_skips_duplicates(tmp_path: Path) -> None:
    result = AnalysisResult(
        prs=[],
        clusters=[_cluster(3)],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )

    summary = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        agents_md_path=None,
    )
    assert "wrote 1 rule pair" in summary

    mdc = next((tmp_path / ".cursor/rules/learned").glob("*.mdc"))
    mdc_fm = mdc.read_text(encoding="utf-8").split("---", 2)[1]
    assert "globs:" in mdc_fm
    assert "paths:" not in mdc_fm

    md = next((tmp_path / ".claude/rules/learned").glob("*.md"))
    md_fm = md.read_text(encoding="utf-8").split("---", 2)[1]
    assert "paths:" in md_fm
    assert "globs:" not in md_fm

    summary2 = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        agents_md_path=None,
    )
    assert "skipped" in summary2
    assert "duplicates" in summary2
