"""Coaching lakehouse (EPIC #344 / #345).

Turns the per-lap JSON archive corpus (`journal/laps/lap_*.json`, the immutable system of
record) into a queryable **DuckDB** star schema so the coach can ask whole-data-plane
questions — trends and dependencies across car x track x corner x condition x setup that no
single lap can show (e.g. *"does +1deg front wing improve mid-corner rotation at Spa T1 across
all my laps and conditions?"*).

The DuckDB lake is a **derived, disposable** view rebuilt idempotently from the JSON corpus —
the JSON is never mutated (data-immutability invariant). See
:mod:`tools.coaching_lake.build_analytics`.
"""

from __future__ import annotations

from tools.coaching_lake.build_analytics import (
    LakeSummary,
    build_lake,
    list_reports,
    run_query,
    run_report,
)

__all__ = [
    "LakeSummary",
    "build_lake",
    "list_reports",
    "run_query",
    "run_report",
]
