"""Tests for the voice-coach timing-report harness (issue #368 AC a / e / h)."""

from __future__ import annotations

from _voice_support import build_manifest

from tools.ai_sidecar.voice.config import Verbosity, VoiceConfig
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.timing_report import _synthetic_observer, build_timing_report


def _report(verbosity: Verbosity):
    manifest = build_manifest()
    return build_timing_report(
        _synthetic_observer(),
        Resolver(manifest),
        config=VoiceConfig(verbosity=verbosity),
        manifest=manifest,
        bank_dir=None,
        backend="synthetic",
    )


def test_scenario_covers_corners_and_speaks_cues() -> None:
    # AC h: the injected scenario exercises corners that actually have usable cues (not vacuous).
    rep = _report(Verbosity.NORMAL)
    assert rep.covered_corners >= 1
    assert rep.assertions["covered_corners_at_least_one"] is True
    assert rep.assertions["cues_spoken"] >= 1


def test_anticipatory_cue_onset_is_before_its_mark() -> None:
    # AC a: an anticipatory cue fires, and every anticipatory cue's onset leads the brake-point mark
    # (a reactive release/verdict legitimately fires past the mark and is exempt).
    rep = _report(Verbosity.NORMAL)
    assert rep.assertions["anticipatory_cue_fired"] is True
    assert rep.assertions["anticipatory_onset_before_mark"] is True
    antic = [c for c in rep.cues if c.anticipatory]
    assert antic and all(c.t_dispatch_ms <= c.t_mark_ms for c in antic)


def test_tone_register_escalates_with_situation() -> None:
    # The headline: a hot approach yields a firm/critical brake cue (not a flat calm one).
    rep = _report(Verbosity.NORMAL)
    spoken_brake = [c for c in rep.cues if c.kind == "late_brake" and c.spoken]
    assert spoken_brake
    assert any(c.register in ("firm", "critical") for c in spoken_brake)


def test_low_verbosity_speaks_no_info() -> None:
    # AC e: no post-fact info narration is spoken under LOW verbosity.
    rep = _report(Verbosity.LOW)
    assert rep.assertions["no_info_spoken_in_low_verbosity"] is True
    assert all(not (c.spoken and c.urgency == "info") for c in rep.cues)


def test_report_serializes_to_json() -> None:
    rep = _report(Verbosity.NORMAL)
    text = rep.to_json()
    assert '"assertions"' in text and '"cues"' in text
