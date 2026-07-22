"""Regression coverage for the retired process-miner AGENTS.md writer."""

from __future__ import annotations

from pathlib import Path

from tools.process_miner.aggregate import AggregateResult
from tools.process_miner.emit import emit_cross_repo_learned

_REPO_ROOT = Path(__file__).resolve().parents[2]
_START = "<!-- process-miner:learned:start -->"
_END = "<!-- process-miner:learned:end -->"
_EXPECTED_BLOCK = (
    f"{_START}\n"
    "- Learned rules live in `.claude/rules/learned/` "
    "(mirrored in `.cursor/rules/learned/`); this block is no longer auto-updated.\n"
    f"{_END}"
)


def test_repo_agents_learned_block_is_static_pointer() -> None:
    text = (_REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    block = text[text.index(_START) : text.index(_END) + len(_END)]

    assert block == _EXPECTED_BLOCK


def test_miner_sources_have_no_agents_writer_plumbing() -> None:
    surfaces = [
        _REPO_ROOT / "tools/process_miner/emit.py",
        _REPO_ROOT / "tools/process_miner/run.py",
        _REPO_ROOT / "scripts/cross_repo_aggregate.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in surfaces)

    for retired in (
        "agents_md_path",
        "_merge_agents_learned_paths",
        "written_paths_out",
        "--agents-md",
        "--no-agents-md",
        "MINING_NO_AGENTS_MD",
    ):
        assert retired not in combined


def test_cross_repo_emitter_never_requires_agents_path(tmp_path: Path) -> None:
    summary, n_written = emit_cross_repo_learned(AggregateResult(), tmp_path)

    assert summary == "emit_cross_repo: no qualifying clusters"
    assert n_written == 0
