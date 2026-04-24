"""CLI for tools.model_training.train (#26 Phase 2 scaffold)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _training_stack_imports_cleanly() -> bool:
    """Match CLI behavior: both packages must import, not merely be discoverable."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


def test_train_module_help_exits_zero() -> None:
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "tools.model_training.train", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "dry-run" in proc.stdout.lower()


def test_train_dry_run_ok(tmp_path: Path) -> None:
    cfg = tmp_path / "sft_config.yaml"
    cfg.write_text("version: 1\n", encoding="utf-8")
    data = tmp_path / "sft_pairs.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "tools.model_training.train",
            "--config",
            str(cfg),
            "--data",
            str(data),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Dry run OK" in proc.stdout


def test_train_missing_data_exits_one(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("x: 1\n", encoding="utf-8")
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "tools.model_training.train",
            "--config",
            str(cfg),
            "--data",
            str(tmp_path / "nope.jsonl"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1


def test_train_non_dry_run_depends_on_training_stack(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text("x: 1\n", encoding="utf-8")
    data = tmp_path / "d.jsonl"
    data.write_text("{}\n", encoding="utf-8")
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "tools.model_training.train",
            "--config",
            str(cfg),
            "--data",
            str(data),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    has_training_stack = _training_stack_imports_cleanly()
    if has_training_stack:
        assert proc.returncode == 1
        assert "not implemented" in proc.stderr.lower()
    else:
        assert proc.returncode == 2
        assert "training" in proc.stderr.lower()
