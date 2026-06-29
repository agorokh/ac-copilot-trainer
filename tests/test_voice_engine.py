"""Tests for the top-level VoiceCoach seam (tools.ai_sidecar.voice.engine).

Covers the asserted advisory-emit -> dispatch latency (the issue #340 latency criterion, measured on
the real worker thread), and graceful degradation when the bank cannot be trusted.
"""

from __future__ import annotations

import json
import time

from _voice_support import make_advisory

from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.engine import VoiceCoach
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME
from tools.ai_sidecar.voice.playback import RecordingPlayback


def _baked(tmp_path):
    bake_bank(tmp_path, ToneBackend())
    return tmp_path


def test_coach_speaks_advisory_and_meets_latency_budget(tmp_path) -> None:
    pb = RecordingPlayback()
    coach = VoiceCoach.from_bank(_baked(tmp_path), VoiceConfig(), playback=pb)
    assert coach.enabled
    coach.start()
    try:
        t0 = time.perf_counter()
        coach.subscribe(make_advisory(kind="late_brake", urgency="act", corner=2))
        deadline = t0 + 2.0
        while not pb.played and time.perf_counter() < deadline:
            time.sleep(0.002)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        coach.stop()
    assert pb.played, "advisory was never dispatched to playback"
    # act cues are terse/corner-less; a firm late_brake resolves to the generic firm clip.
    assert pb.played[-1].clip_id == "late_brake.act.firm.generic"
    # advisory-emit -> first-sample dispatch budget (target <= ~150 ms end-to-end). The
    # clip-playback
    # component is the pre-warmed audio stream, measured on-rig in the deferred live verification.
    assert elapsed_ms < 150.0, f"dispatch latency {elapsed_ms:.1f} ms exceeded 150 ms"


def test_disabled_when_manifest_missing(tmp_path) -> None:
    coach = VoiceCoach.from_bank(tmp_path, VoiceConfig(), playback=RecordingPlayback())
    assert not coach.enabled
    assert "manifest" in coach.disabled_reason.lower()
    # subscribe must be a safe no-op (never crash) when disabled
    coach.subscribe(make_advisory())
    coach.start()
    coach.stop()


def test_disabled_on_vocabulary_drift(tmp_path) -> None:
    _baked(tmp_path)
    mfp = tmp_path / MANIFEST_FILENAME
    data = json.loads(mfp.read_text())
    data["vocabulary_hash"] = "deadbeef" * 8  # wording changed but bank not re-baked
    mfp.write_text(json.dumps(data))
    pb = RecordingPlayback()
    coach = VoiceCoach.from_bank(tmp_path, VoiceConfig(), playback=pb)
    assert not coach.enabled
    coach.subscribe(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert pb.played == []  # never plays a possibly-wrong clip


def test_disabled_coach_factory() -> None:
    coach = VoiceCoach.disabled("test reason")
    assert not coach.enabled
    assert coach.disabled_reason == "test reason"
    coach.subscribe(make_advisory())  # no-op, no crash
