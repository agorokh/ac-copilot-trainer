"""CLI entrypoint for ``python -m tools.tt_ingest`` (issue #353)."""

from __future__ import annotations

import sys

from tools.tt_ingest.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
