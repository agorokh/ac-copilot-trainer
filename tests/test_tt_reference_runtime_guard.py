"""Runtime guard for Track Titan reference archives (issue #353 M-TT2)."""

from __future__ import annotations

from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar.realtime_observer import build_observer_from_reference


def test_partial_tt_reference_archive_is_not_installed_as_live_observer() -> None:
    archive = _corner_archive()
    archive["generator"] = {
        "tt_reference": {
            "format": "track_titan_reference_v1",
            "partial": True,
            "coverage": 0.094,
        }
    }

    assert build_observer_from_reference(archive) is None


def test_non_dict_reference_archive_is_not_installed_as_live_observer() -> None:
    assert build_observer_from_reference(None) is None  # type: ignore[arg-type]
