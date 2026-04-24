"""SFT training entry scaffold for Tier 3 (#26 Phase 2).

Heavy dependencies (torch, transformers, …) are optional — install ``pip install -e ".[training]"``.
``make ci-fast`` never imports them; use ``--dry-run`` to validate paths without ML stack.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _require_training_extras() -> None:
    """Raise SystemExit if optional ML stack is missing."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as exc:
        print(
            "Training dependencies are unavailable or failed to import.\n"
            'Install/repair with:\n  pip install -e ".[training]"',
            file=sys.stderr,
        )
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Local reviewer SFT training scaffold (#26). "
            "Full Unsloth/TRL wiring is org-specific; --dry-run validates inputs only."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Training YAML (e.g. tools/model_training/config/sft_config.yaml)",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="SFT JSONL produced by data_pipeline (e.g. .cache/training_data/sft_pairs.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/reviewer-v1"),
        help="Directory for checkpoints (created when training is implemented)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify config/data paths only; do not import torch or train",
    )
    args = parser.parse_args(argv)

    if not args.config.is_file():
        print(f"Config not found: {args.config}", file=sys.stderr)
        return 1
    if not args.data.is_file():
        print(f"Data file not found: {args.data}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run OK:")
        print(f"  config: {args.config.resolve()}")
        print(f"  data:   {args.data.resolve()}")
        print(f"  output: {args.output.resolve()}")
        print("Next: install .[training] and implement TRL/Unsloth loop per vault ADR.")
        return 0

    _require_training_extras()
    print(
        "Training loop is not implemented in the template repository.\n"
        "Wire TRL SFTTrainer / Unsloth using --config and --data; see:\n"
        "  docs/01_Vault/AcCopilotTrainer/01_Decisions/local-reviewer-model.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
