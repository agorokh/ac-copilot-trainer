"""Explicit-file offline importer: python -m tools.moza_ingest --help."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.moza_ingest.normalize import normalize_view
from tools.moza_ingest.reader import MozaImportError, read_selected_json, write_once_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a selected MOZA view for quarantined inspection."
    )
    parser.add_argument(
        "--cache", type=Path, required=True, help="One tracecore.view.v1 JSON file."
    )
    parser.add_argument(
        "--evaluation", type=Path, help="Optional selected training-evaluation snapshot v1."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output file; existing files are never replaced.",
    )
    args = parser.parse_args(argv)
    try:
        cache = read_selected_json(args.cache)
        evaluation = read_selected_json(args.evaluation) if args.evaluation is not None else None
        record = normalize_view(
            cache.payload,
            source=cache.receipt,
            evaluation=evaluation.payload if evaluation else None,
            evaluation_source=evaluation.receipt if evaluation else None,
        )
        inputs = [args.cache] + ([args.evaluation] if args.evaluation is not None else [])
        write_once_json(args.output, record, inputs=inputs)
    except MozaImportError as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}))
        return 2
    print(
        json.dumps(
            {
                "status": record["import_status"],
                "source_sha256": cache.receipt["sha256"],
                "production_eligible": False,
                "reasons": record["qualification"]["reasons"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
