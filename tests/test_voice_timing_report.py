"""Tests for the voice-coach timing-report harness (issue #368 AC a / e / h)."""

from __future__ import annotations

from _voice_support import build_manifest, make_advisory

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


def test_same_frame_advisories_are_arbitrated_as_one_batch() -> None:
    # qodo review #371: the report must mirror production scheduling by submitting every advisory from
    # one telemetry frame before calling process_pending(). Sequential processing can briefly speak a
    # lower-rank cue that the real batch winner would suppress.
    obs = _synthetic_observer()
    emitted = False

    def observe(_frame: dict[str, object]):
        nonlocal emitted
        if emitted:
            return []
        emitted = True
        return [
            make_advisory(kind="apex_deficit", urgency="info", register="calm", corner=0),
            make_advisory(kind="late_brake", urgency="act", register="firm", corner=0),
        ]

    obs.observe = observe  # type: ignore[method-assign]
    rep = build_timing_report(
        obs,
        Resolver(build_manifest()),
        config=VoiceConfig(verbosity=Verbosity.NORMAL),
        manifest=build_manifest(),
        bank_dir=None,
        backend="synthetic",
    )
    spoken = [c for c in rep.cues if c.spoken]
    assert [c.kind for c in spoken] == ["late_brake"]
    assert any(c.kind == "apex_deficit" and not c.spoken for c in rep.cues)


def test_cues_spoken_is_a_gating_boolean() -> None:
    # codex review #371: a non-vacuous proof must dispatch a cue (unless muted). OFF = no cues but
    # still non-vacuous; an audible run that suppressed everything would fail the boolean assertion.
    off = _report(Verbosity.OFF)
    assert off.assertions["cues_spoken"] == 0
    assert off.assertions["cues_spoken_when_audible"] is True  # mute by design
    normal = _report(Verbosity.NORMAL)
    assert normal.assertions["cues_spoken"] >= 1
    assert normal.assertions["cues_spoken_when_audible"] is True


def test_main_rejects_an_invalid_bank(tmp_path) -> None:
    # codex review #371: --bank must validate before reporting, so a stale bank (which the real
    # coach would disable) cannot produce a green timing report.
    import json

    import pytest

    from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
    from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME
    from tools.ai_sidecar.voice.timing_report import main

    bake_bank(tmp_path, ToneBackend())
    mfp = tmp_path / MANIFEST_FILENAME
    data = json.loads(mfp.read_text())
    data["vocabulary_hash"] = "deadbeef" * 8  # wording drift → the real coach would disable
    mfp.write_text(json.dumps(data))
    with pytest.raises(SystemExit):
        main(["--bank", str(tmp_path)])
