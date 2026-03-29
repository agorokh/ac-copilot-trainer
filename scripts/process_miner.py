#!/usr/bin/env python3
"""Wrapper for `tools.process_miner.run` (repo root must be cwd or package installed)."""

from __future__ import annotations

import sys

from tools.process_miner.run import main

if __name__ == "__main__":
    sys.exit(main())
