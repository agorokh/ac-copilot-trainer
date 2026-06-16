"""CLI entrypoint for ``python -m tools.import_motec``."""

from __future__ import annotations

import sys

from . import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
