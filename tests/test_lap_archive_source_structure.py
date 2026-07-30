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
    menu_prefix = branch_body.split("if state.wasDriving then", maxsplit=1)[0]
    # #627/#466: menu polling must not depend on a post-session review already being queued.
    # A fresh launch needs this same bridge to receive session.start and leave the pre-drive menu.
    assert "pendingSessionReview ~= nil and wsBridge" not in menu_prefix
    assert "if wsBridge then" in menu_prefix
    assert "wsBridge.startSidecarIfNeeded(appDir, dt)" in menu_prefix
    assert "wsBridge.tick(ch.simSeconds(sim), dt)" in menu_prefix
    assert "wsBridge.pollInbound(8)" in menu_prefix
    assert menu_prefix.index("wsBridge.tick(ch.simSeconds(sim), dt)") < menu_prefix.index(
        "pumpSessionReviewRequest()"
    )
    assert "flushPendingLapArchiveJobs(" in branch_body, (
        "session-end branch must drain pending lap-archive jobs before its session-end "
        "work (issue #305)"
    )
    assert "wsBridge.sendSessionReviewGenerate" in src, (
        "session-end branch must ask the sidecar to generate the post-session review "
        "after the lap archives are final"
    )
    assert "not state.sessionReviewRequested" in branch_body
    assert "queueSessionReviewRequest(persistence.lapArchiveDir(), SESSION_UUID)" in branch_body
    assert "pumpSessionReviewRequest()" in branch_body
    assert branch_body.index("pumpLapArchiveNotifications()") < branch_body.index(
        "queueSessionReviewRequest"
    )
    assert "pendingSessionReview" in src
    assert "pendingSessionReview.sessionUuid == sessionUuid" in src
    assert "pendingSessionReview = nil" in src
    assert "pending.retryFrames = 60" in src
    assert "state.sessionReviewRetryFrames = pending.retryFrames" in src
    assert src.index("reviewOk and reviewSentOrErr == true") < src.index(
        "state.sessionReviewRequested = true"
    )


def test_session_review_bridge_uses_generic_local_path_gate() -> None:
    """#404: report generation carries local archive paths but is not setup-experiment logic."""
    bridge = (REPO / "src" / "ac_copilot_trainer" / "modules" / "ws_bridge.lua").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"function M\.sendSessionReviewGenerate.*?\nend\n",
        bridge,
        flags=re.S,
    )
    assert match is not None
    body = match.group(0)
    assert "localPathFramesAllowed()" in body
    assert "setupExperimentPathFramesAllowed" not in body
    assert "reference_source" in body
    assert "reference_file" in body


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

    drive_start = src.index("lastDriveCar = car")
    marker = src.index("-- Issue #180 Part D step 2", drive_start)
    ws_block = src[drive_start:marker]
    assert "wsBridge.tick(ch.simSeconds(sim), dt)" in ws_block
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


def test_deferred_archive_payload_copies_full_lap_complete_payload() -> None:
    """#321 regression: the deferred archive-backed lap_complete must be a copy of the FULL
    live ``lapPayload`` (protocol/event/lap/lapTimeMs), not a bare ``{brainOnly=true}`` table.

    In Lua 5.1 a ``local`` declared inside the ``if lastMs > 0`` block is out of scope by the
    archive block below, so ``shallowCopy(lapPayload)`` there would copy ``nil`` and silently
    strip the base fields — leaving the sidecar's ``event == "lap_complete"`` gate unable to
    fire the brain follow-up (the whole point of #321). The fix hoists ``lapPayload`` to an
    outer-scope bare ``local``; this guard pins that shape so the bug cannot regress.
    """
    src = ENTRY.read_text(encoding="utf-8")

    # Exactly one declaration, and it is a bare *hoisted* local — NOT `local lapPayload = {`,
    # which would scope it inside the lap-boundary block and break the deferred copy.
    decls = re.findall(r"\blocal lapPayload\b", src)
    assert len(decls) == 1, "expected exactly one lapPayload local declaration"
    assert re.search(r"\n[ \t]*local lapPayload[ \t]*\n", src) is not None, (
        "lapPayload must be hoisted as a bare `local lapPayload` declaration above the "
        "`if lastMs > 0` block (Lua block scope; #321)"
    )
    assert "local lapPayload = {" not in src, (
        "lapPayload must not be re-declared inside the lap-boundary block — the deferred "
        "archive copy would then see nil and drop the base lap_complete fields (#321)"
    )

    # The populated table is assigned to the hoisted local and carries the base lap_complete fields.
    populated = re.search(r"\n[ \t]*lapPayload = \{(.*?)\n[ \t]*\}", src, flags=re.S)
    assert populated is not None, "could not find the `lapPayload = { ... }` assignment"
    payload_literal = populated.group(1)
    for field in ('event = "lap_complete"', "lap = state.lapsCompleted", "lapTimeMs = lastMs"):
        assert field in payload_literal, f"base lap_complete field missing from lapPayload: {field}"

    # The deferred archive payload is a copy of that full payload (inheriting the base fields),
    # then adds the brain-only marker — it must not be built from scratch.
    archive_block = re.search(
        r"-- Issue #77 Part C / #246: archive this lap.*?state\.lapInvalidatedThisLap = false",
        src,
        flags=re.S,
    )
    assert archive_block is not None
    block = archive_block.group(0)
    assert "local archiveLapPayload = shallowCopy(lapPayload)" in block, (
        "deferred archive payload must shallowCopy the full lapPayload so it keeps the base "
        "lap_complete fields (#321)"
    )
