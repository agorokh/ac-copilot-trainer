"""Source-structure (architectural) guards for the lap-archive pump/flush wiring.

These are pure ``read_text()`` + ``re`` assertions over ``ac_copilot_trainer.lua`` —
they do NOT need the lupa Lua runtime, so (unlike the behavioral tests in
``test_lap_archive_async.py``) they must run even on a box without lupa installed.
Keeping them in their own module avoids the module-level ``importorskip("lupa")``
silently disabling the regression net for the archive wiring (#305 review finding).

If the lap boundary, WS pump, or session-end branch is refactored, update the
anchors here so the guard stays meaningful rather than deleting it.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
ENTRY = REPO / "src" / "ac_copilot_trainer" / "ac_copilot_trainer.lua"


def test_session_end_flushes_pending_lap_archive() -> None:
    """#305: the main-menu (session-end) branch of script.update must drain pending
    archive jobs before its early return, so the last lap driven is never abandoned as
    a partial .tmp. The drain must run BEFORE the session-end work (writeSessionEnd /
    resetRuntimeAfterLeavingTrack), which is what gives it a queue to drain."""
    src = ENTRY.read_text(encoding="utf-8")

    # The synchronous drain helper exists and operates on the pending-job queue.
    flush_def = re.search(r"local function flushPendingLapArchiveJobs.*?\nend\n", src, flags=re.S)
    assert flush_def is not None, "flushPendingLapArchiveJobs helper missing"
    assert "pendingLapArchiveJobs" in flush_def.group(0)

    # Pin the exact update() session-end branch via a marker unique to it
    # (sessionJournal.writeSessionEnd is only called there), then take the LAST
    # `if sim.isInMainMenu then` before that marker — that is the branch start. This
    # captures the precise branch body with no fixed-width window to grow brittle.
    anchor = src.index("sessionJournal.writeSessionEnd")
    menu_kw = src.rindex("if sim.isInMainMenu then", 0, anchor)
    branch_body = src[menu_kw:anchor]
    assert "flushPendingLapArchiveJobs(" in branch_body, (
        "session-end branch must drain pending lap-archive jobs before its session-end "
        "work (issue #305)"
    )


def test_lap_boundary_queues_archive_instead_of_sync_write() -> None:
    # This is an intentional source-structure regression test: if the lap
    # boundary or WS pump sections are refactored, update these regex anchors
    # with the implementation so the architectural guard remains meaningful.
    src = ENTRY.read_text(encoding="utf-8")
    match = re.search(
        r"-- Issue #77 Part C / #246: archive this lap.*?state\.lapInvalidatedThisLap = false",
        src,
        flags=re.S,
    )
    assert match is not None
    block = match.group(0)
    assert "queueLapArchiveJob(archiveOpts" in block
    assert "lapArchive.write" not in block
    assert "lapArchive.buildRecord" not in block

    ws_match = re.search(
        r"wsBridge\.tick\(ch\.simSeconds\(sim\)\).*?-- Issue #180 Part D step 2",
        src,
        flags=re.S,
    )
    assert ws_match is not None
    ws_block = ws_match.group(0)
    assert ws_block.index("wsBridge.pollInbound(8)") < ws_block.index("pumpLapArchiveJobs()")
    assert ws_block.index("pumpLapArchiveJobs()") < ws_block.index("pumpLapArchiveNotifications()")
    assert "pendingLapArchiveRecordPaths" in src


def test_archive_write_notification_sends_brain_activation_lap_payload() -> None:
    """#277: the live brain needs the finalized archive path, which exists only after
    the async archive job completes. The queue notification must attach that path to a
    follow-up lap_complete payload and include the prior best archive as reference when
    available, without turning the archive write back into synchronous lap-boundary I/O."""
    src = ENTRY.read_text(encoding="utf-8")

    pump = re.search(
        r"local function pumpLapArchiveJobs.*?\nlocal function flushPendingLapArchiveJobs",
        src,
        flags=re.S,
    )
    assert pump is not None
    pump_body = pump.group(0)
    assert "payload.archivePath = pathOrErr" in pump_body
    assert "payload.referenceArchivePath = notify.referenceArchivePath" in pump_body
    assert "bestLapArchivePath = pathOrErr" in pump_body

    archive_block = re.search(
        r"-- Issue #77 Part C / #246: archive this lap.*?state\.lapInvalidatedThisLap = false",
        src,
        flags=re.S,
    )
    assert archive_block is not None
    block = archive_block.group(0)
    assert "local referenceArchivePathForBrain = bestLapArchivePath" in src
    assert "archiveLapPayload.brainOnly = true" in block
    assert "referenceArchivePath = referenceArchivePathForBrain" in block
