"""Phase 1 model training data export (issue #26)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.model_training import data_pipeline, dataset_stats, format_cpt, format_dpo, format_sft
from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment
from tools.repo_knowledge.ingest import ingest_analysis


def _minimal_result() -> AnalysisResult:
    """Build a tiny :class:`AnalysisResult` suitable for knowledge DB ingest tests."""
    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="add types please",
                author="r",
                created_at=datetime.now(UTC),
                path="src/x.py",
                line=1,
                pr_number=1,
                is_inline=True,
            )
        ],
        issue_comments=[],
    )
    cluster = CommentCluster(
        cluster_id=0,
        title="types / hints",
        count=3,
        comments=pr.review_comments * 3,
        affected_files=["src/x.py"],
        severity="maintainability",
        preventability="typecheck",
        representative_examples=["add types please"],
    )
    return AnalysisResult(
        prs=[pr],
        clusters=[cluster],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 1},
    )


def test_run_pipeline_writes_sft_jsonl(tmp_path: Path) -> None:
    """End-to-end export produces SFT JSONL with expected assistant content."""
    db = tmp_path / "k.db"
    out = tmp_path / "training"
    ingest_analysis(_minimal_result(), "o/r", db)
    pairs, decisions = data_pipeline.run_pipeline(db, out)
    assert pairs.exists()
    assert decisions.exists()
    lines = pairs.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert "messages" in first
    assert first["messages"][2]["role"] == "assistant"
    assert "add types please" in first["messages"][2]["content"]
    assert first["metadata"]["source"] == "pattern_evidence"


def test_sft_record_shape() -> None:
    """``evidence_row_to_sft_record`` embeds path and comment in messages."""
    row = {
        "id": 1,
        "pattern_id": 2,
        "pr_number": 9,
        "comment_body": "nit: naming",
        "file_path": "a.py",
        "line_number": 4,
        "pattern_text": "style",
    }
    rec = format_sft.evidence_row_to_sft_record(row)
    assert rec["metadata"]["pr_number"] == 9
    assert "a.py" in rec["messages"][1]["content"]
    assert rec["messages"][2]["content"] == "nit: naming"


def test_dataset_stats_jsonl(tmp_path: Path) -> None:
    """``jsonl_stats`` and ``summarize_dir`` reflect exported training files."""
    db = tmp_path / "k.db"
    out = tmp_path / "training"
    ingest_analysis(_minimal_result(), "o/r", db)
    data_pipeline.run_pipeline(db, out)
    st = dataset_stats.jsonl_stats(out / "sft_pairs.jsonl")
    assert st["records_with_messages"] == 3
    assert st["parse_errors"] == 0
    rows = dataset_stats.summarize_dir(out)
    assert len(rows) == 2


def test_dataset_stats_main_jsonl(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI ``--jsonl`` prints a single stats object as JSON."""
    p = tmp_path / "x.jsonl"
    p.write_text(
        json.dumps({"messages": [{"role": "user", "content": "hi"}]}) + "\n",
        encoding="utf-8",
    )
    assert dataset_stats.main(["--jsonl", str(p)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["records_with_messages"] == 1


def test_dataset_stats_main_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI ``--dir`` prints a JSON list of per-file stats."""
    (tmp_path / "a.jsonl").write_text("{}\n", encoding="utf-8")
    assert dataset_stats.main(["--dir", str(tmp_path)]) == 0
    loaded = json.loads(capsys.readouterr().out)
    assert isinstance(loaded, list)
    assert loaded[0]["valid_json_objects"] == 1


def test_dataset_stats_non_dict_jsonl_line(tmp_path: Path) -> None:
    """Parsed JSON arrays count as ``non_dict_json_lines``, not parse errors."""
    p = tmp_path / "m.jsonl"
    p.write_text("[1, 2, 3]\n", encoding="utf-8")
    st = dataset_stats.jsonl_stats(p)
    assert st["parse_errors"] == 0
    assert st["non_dict_json_lines"] == 1
    assert st["valid_json_objects"] == 0


def test_format_dpo_stub() -> None:
    """DPO helpers remain stubs in Phase 1."""
    with pytest.raises(NotImplementedError, match="DPO"):
        format_dpo.iter_dpo_records(None)
    with pytest.raises(NotImplementedError, match="DPO"):
        format_dpo.main()


def test_format_cpt_stub() -> None:
    """CPT helpers remain stubs in Phase 1."""
    with pytest.raises(NotImplementedError, match="CPT"):
        format_cpt.iter_cpt_documents(None)
    with pytest.raises(NotImplementedError, match="CPT"):
        format_cpt.main()


def test_data_pipeline_cli_main(tmp_path: Path) -> None:
    """``data_pipeline.main`` writes JSONL when source DB exists."""
    db = tmp_path / "k.db"
    out = tmp_path / "training"
    ingest_analysis(_minimal_result(), "o/r", db)
    code = data_pipeline.main(["--source", str(db), "--output", str(out)])
    assert code == 0
    assert (out / "sft_pairs.jsonl").exists()


def test_run_pipeline_missing_source_raises(tmp_path: Path) -> None:
    """Missing DB path raises before creating output directory."""
    missing = tmp_path / "missing.db"
    out = tmp_path / "out"
    with pytest.raises(FileNotFoundError, match="Source database not found"):
        data_pipeline.run_pipeline(missing, out)
    assert not out.exists()


def test_data_pipeline_cli_missing_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI exits 2 and does not create ``--output`` when ``--source`` is missing."""
    out = tmp_path / "out"
    code = data_pipeline.main(["--source", str(tmp_path / "nope.db"), "--output", str(out)])
    assert code == 2
    assert "Source database not found" in capsys.readouterr().err
    assert not out.exists()
