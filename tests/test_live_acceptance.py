"""Synthetic/offline harness tests. These are never receipts of live acoustic success."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from tools.ai_sidecar.voice import audible_latency as al  # noqa: E402
from tools.ai_sidecar.voice import live_acceptance as live  # noqa: E402
from tools.ai_sidecar.voice import vocabulary  # noqa: E402
from tools.ai_sidecar.voice.manifest import MANIFEST_VERSION, ClipEntry, Manifest  # noqa: E402
from tools.ai_sidecar.voice.playback import Bank  # noqa: E402

RATE = 48000
# The phrase lag and the final segment's lag each sit on a correlation peak a few samples wide,
# and platform FFT rounding can move either argmax. 0.2 ms is still two orders of magnitude
# below the live timing uncertainty (about 26 ms on the rig).
COMPLETION_TOLERANCE_SAMPLES = int(0.0002 * RATE)


def voice_signal():
    rng = np.random.default_rng(815)
    signal = rng.normal(0, 0.12, int(RATE * 0.4))
    signal = np.convolve(signal, np.ones(5) / 5, mode="same")
    return signal


def callback_evidence(*, frames=RATE * 10, period=1000 / RATE, buffer_frames=480, start=100000.25):
    # A QueryPerformanceCounter-backed monotonic clock stamps sub-millisecond values.
    return dict(
        frames=frames,
        samplerate=RATE,
        statuses=[],
        callback_stamps=[
            dict(
                sample=sample,
                frames=min(buffer_frames, frames - sample),
                mono_ms=start + sample * period,
                wall_ms=start + sample * period,
                adc_time=(start + sample * period - 10) / 1000,
            )
            for sample in range(0, frames, buffer_frames)
        ],
    )


def test_exact_device_refuses_ambiguity_and_ignores_numeric_indices():
    apis = [{"name": "Windows WASAPI"}, {"name": "MME"}]
    devices = [
        dict(name="Mic", hostapi=1, max_input_channels=1),
        dict(name="Mic", hostapi=0, max_input_channels=1),
    ]
    assert live.exact_device(devices, apis, "Mic", "Windows WASAPI", "input") == 1
    with pytest.raises(ValueError, match="found 2"):
        live.exact_device(devices + devices[1:], apis, "Mic", "Windows WASAPI", "input")


@pytest.mark.parametrize("cut", [None, 0.2])
def test_whole_phrase_required_after_successful_onset_match(cut):
    signal = voice_signal()
    recording = np.zeros(RATE * 5)
    played = signal if cut is None else signal[: int(RATE * cut)]
    recording[RATE : RATE + len(played)] = played
    bank = Bank(samplerate=RATE, clips={"brake": signal}, channels=1)
    clock = al.ClockMap(0, 100000, 1000 / RATE, anchors_used=2)
    result = live.match_audio(
        recording, RATE, clock, [dict(seq=1, clip_id="brake", t_mono_ms=100800)], bank
    )[0]
    assert result["matched"]
    assert result["latency_ms"] == pytest.approx(200, abs=2)
    assert result["complete"] is (cut is None)
    assert (result["completion_ms"] is not None) is (cut is None)


def test_silence_cannot_match_a_dispatched_phrase():
    bank = Bank(samplerate=RATE, clips={"brake": voice_signal()}, channels=1)
    result = live.match_audio(
        np.zeros(RATE * 4),
        RATE,
        al.ClockMap(0, 100000, 1000 / RATE, anchors_used=2),
        [dict(seq=1, clip_id="brake", t_mono_ms=100800)],
        bank,
    )[0]
    assert not result["matched"]
    assert not result["complete"]


def test_one_sound_cannot_satisfy_two_different_dispatches():
    signal = voice_signal()
    recording = np.zeros(RATE * 5)
    recording[RATE : RATE + len(signal)] = signal
    bank = Bank(samplerate=RATE, clips={"one": signal, "two": signal}, channels=1)
    dispatches = [
        dict(seq=1, clip_id="one", t_mono_ms=100800),
        dict(seq=2, clip_id="two", t_mono_ms=100850),
    ]
    results = live.match_audio(
        recording, RATE, al.ClockMap(0, 100000, 1000 / RATE, anchors_used=2), dispatches, bank
    )
    assert results[0]["complete"]
    assert not results[1]["complete"]
    assert results[1]["reason"] == "acoustic_onset_already_assigned_to_another_dispatch"


def test_brake_event_is_global_run_with_preceding_off_sample():
    def tick(i, brake, lap=2):
        return dict(
            mono_ms=1000 + i * 50,
            frame=dict(
                seq=i, payload=dict(lap=lap, brake=brake, spline=0.1 + i * 0.001, speed_kmh=150)
            ),
        )

    rows = [tick(i, b) for i, b in enumerate([0.8, 0.8, 0.8, 0, 0.06, 0.4, 0.6, 0.3, 0, 0.8, 0])]
    events = live.brake_events(rows)
    assert len(events) == 1  # beginning mid-braking and one-sample spike are not invented onsets
    assert events[0]["onset_ms"] == 1200
    assert events[0]["earliest_ms"] == 1150
    assert events[0]["samples"] == 4


@pytest.fixture
def single_phrase_completeness(monkeypatch):
    """Single-phrase synthetic bundles test timing/target logic, not completeness.

    The reverb-aware rule needs >= 5 other phrases for its room response and fails closed on
    these bundles by design; the dedicated multi-phrase tests below cover it. Here the dry-rule
    result stands in, so these tests keep exercising the logic they were written for.
    """

    def stand_in(recording, rate, cues, bank, exclusions, *, seed, nulls=None):
        return [
            dict(
                criterion="test_stand_in_dry_rule",
                evaluated=True,
                complete=bool(cue.get("complete")),
                speech_start_sample=cue["onset_sample"] if cue.get("complete") else None,
                completion_sample=(
                    cue["onset_sample"] + cue["template_samples"] if cue.get("complete") else None
                ),
                reason=None if cue.get("complete") else cue.get("reason"),
                segments=[],
            )
            for cue in cues
        ]

    monkeypatch.setattr(live, "reverb_aware_completeness", stand_in)


def room_phrase(seed, seconds=0.6):
    """A voice-like clip: band-limited noise shaped into three syllables."""
    rng = np.random.default_rng(seed)
    n = int(RATE * seconds)
    carrier = np.convolve(rng.normal(0, 1, n), np.ones(6) / 6, mode="same")
    envelope = np.zeros(n)
    for start, end in ((0.02, 0.22), (0.27, 0.42), (0.46, 0.58)):
        a, b = int(start * RATE), int(end * RATE)
        envelope[a:b] = np.hanning(b - a)
    return 0.3 * carrier * envelope


def synthetic_room(phrases=8, *, truncate=None, gap_s=4.0, noise=0.01, seed=7):
    """Play clips through a reverberant room into a noisy mic; return audio, cues and bank."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(0.25 * RATE)) / RATE
    response = rng.normal(0, 1, len(t)) * np.exp(-t / 0.05)
    response[0] = 6.0
    response /= np.sqrt(np.sum(response**2))
    clips = {f"clip{i}": room_phrase(100 + i) for i in range(phrases)}
    total = int(RATE * (gap_s * phrases + 30))
    audio = noise * rng.normal(0, 1, total)
    cues, exclusions = [], []
    for i, (clip_id, clip) in enumerate(clips.items()):
        onset = int(RATE * (20 + gap_s * i))
        played = clip.copy()
        if truncate is not None and truncate[0] == i:
            played[int(truncate[1] * len(played)) :] = 0.0
        acoustic = np.convolve(played, response)
        audio[onset : onset + len(acoustic)] += acoustic
        cues.append(
            dict(
                clip_id=clip_id,
                matched=True,
                onset_sample=onset,
                template_effective_samplerate=RATE,
                template_samples=len(clip),
                complete=True,
            )
        )
        exclusions.append((onset - RATE, onset + 3 * RATE))
    bank = Bank(samplerate=RATE, clips=clips, channels=1)
    return audio, cues, bank, exclusions


def test_reverb_aware_completeness_accepts_reverberant_complete_phrases():
    audio, cues, bank, exclusions = synthetic_room()
    results = live.reverb_aware_completeness(audio, RATE, cues, bank, exclusions, seed=1, nulls=120)
    assert [r["complete"] for r in results] == [True] * len(cues)
    for cue, result in zip(cues, results, strict=True):
        assert len(result["segments"]) == live.COMPLETENESS_SEGMENTS
        assert result["room_model_z"] >= live.COMPLETENESS_MIN_Z
        # Completion is the measured end of the last speech energy (the clip ends in 20 ms of
        # silence), not onset + nominal clip length.
        clip = bank.get(cue["clip_id"])
        speech_end = cue["onset_sample"] + int(np.flatnonzero(np.abs(clip) > 0)[-1]) + 1
        assert abs(result["completion_sample"] - speech_end) <= COMPLETION_TOLERANCE_SAMPLES


def test_reverb_aware_completeness_realigns_a_displaced_matched_filter_onset():
    # |correlation| onsets can land on a neighbouring reverberant lobe (run 05 of #815).
    audio, cues, bank, exclusions = synthetic_room()
    shift = int(0.004 * RATE)
    true_onset = cues[2]["onset_sample"]
    cues[2] = dict(cues[2], onset_sample=true_onset + shift)
    results = live.reverb_aware_completeness(audio, RATE, cues, bank, exclusions, seed=1, nulls=120)
    assert [r["complete"] for r in results] == [True] * len(cues)
    assert abs(results[2]["alignment_lag_ms"] * RATE / 1000 + shift) <= 1
    clip = bank.get(cues[2]["clip_id"])
    speech_end = true_onset + int(np.flatnonzero(np.abs(clip) > 0)[-1]) + 1
    assert abs(results[2]["completion_sample"] - speech_end) <= COMPLETION_TOLERANCE_SAMPLES


def evaluation(complete, start=None, end=None, reason=None):
    return dict(
        criterion="reverb_aware_new_content_segments",
        evaluated=True,
        complete=complete,
        speech_start_sample=start,
        completion_sample=end,
        reason=reason,
        segments=[],
    )


def test_completeness_verdict_replaces_the_dry_rule_reason_both_ways():
    cues = [
        dict(matched=True, complete=False, reason="truncated_or_masked_phrase"),
        dict(matched=True, complete=True, reason=None),
        dict(matched=False, complete=False, reason="acoustic_onset_already_assigned_to_another"),
    ]
    live.apply_completeness(
        cues,
        [
            evaluation(True, 1000, 2000),
            evaluation(False, reason="segment_not_significant"),
            evaluation(False, reason="phrase_not_located"),
        ],
        lambda sample: sample / 10,
    )
    assert [c["complete"] for c in cues] == [True, False, False]
    assert [c["dry_blocks_complete"] for c in cues] == [False, True, False]
    assert [c["reason"] for c in cues] == [
        None,
        "segment_not_significant",
        "acoustic_onset_already_assigned_to_another",  # the locating failure stays specific
    ]
    assert [c["completion_ms"] for c in cues] == [200, None, None]


def test_reverb_complete_phrases_still_cannot_share_one_acoustic_interval():
    # A suffix clip dispatched over the full clip: the dry rule never recorded the full clip's
    # interval (reverb failed its quiet blocks), yet both pass the reverb-aware test.
    cues = [dict(matched=True, complete=False, reason="truncated_or_masked_phrase") for _ in "ab"]
    live.apply_completeness(
        cues, [evaluation(True, 1000, 2000), evaluation(True, 1480, 2000)], lambda s: s
    )
    assert cues[0]["complete"] and cues[0]["completion_ms"] == 2000
    assert not cues[1]["complete"]
    assert cues[1]["reason"] == "acoustic_interval_already_assigned"
    assert cues[1]["completion_ms"] is None


def test_reverb_aware_completeness_rejects_a_phrase_cut_before_its_last_syllable():
    audio, cues, bank, exclusions = synthetic_room(truncate=(3, 0.75))
    results = live.reverb_aware_completeness(audio, RATE, cues, bank, exclusions, seed=1, nulls=120)
    cut = results[3]
    assert not cut["complete"]
    assert cut["reason"] == "segment_not_significant"
    assert cut["completion_sample"] is None
    assert not cut["segments"][-1]["present"]
    assert all(r["complete"] for i, r in enumerate(results) if i != 3)


def test_reverb_aware_completeness_fails_closed_without_enough_other_phrases():
    audio, cues, bank, exclusions = synthetic_room(phrases=5)
    results = live.reverb_aware_completeness(audio, RATE, cues, bank, exclusions, seed=1, nulls=50)
    assert all(not r["complete"] for r in results)
    assert {r["reason"] for r in results} == {"room_model_unqualified:too_few_other_phrases"}


def test_reverb_aware_completeness_fails_closed_without_cue_free_null_material():
    audio, cues, bank, exclusions = synthetic_room()
    everything = [(0, len(audio))]
    results = live.reverb_aware_completeness(audio, RATE, cues, bank, everything, seed=1, nulls=50)
    assert {r["reason"] for r in results} == {"null_material_insufficient"}
    assert not any(r["complete"] for r in results)


def test_reverb_aware_completeness_never_passes_an_unplayed_phrase():
    audio, cues, bank, exclusions = synthetic_room()
    silent = room_phrase(999)
    bank.clips["never_played"] = silent
    ghost = dict(cues[0], clip_id="never_played", onset_sample=int(RATE * 8))  # cue-free span
    results = live.reverb_aware_completeness(
        audio,
        RATE,
        [*cues, ghost],
        bank,
        [*exclusions, (int(RATE * 7), int(RATE * 11))],
        seed=1,
        nulls=120,
    )
    assert not results[-1]["complete"]
    assert results[-1]["reason"] in {
        "room_model_unqualified:no_better_than_null",
        "segment_not_significant",
    }


def build_bundle(tmp_path):
    """Synthetic bytes deliberately stamped synthetic, never windows_live."""
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    reference = json.loads(
        (Path(__file__).parent / "fixtures" / "magione_gt3r_reference.json").read_bytes()
    )
    reference.update(
        source="in_game", session_uuid="synthetic-reference", lap_uuid="synthetic-reference"
    )
    reference["car"]["id"] = "test-car"
    reference["track"].update(id="test-track", layout=None)
    reference["lap"].update(lap_n=1, complete=True)
    reference_path, ledger_path = tmp_path / "reference.json", tmp_path / "attributions.json"
    live.write_json(reference_path, reference)
    live.write_json(ledger_path, {"schema_version": 1, "entries": []})
    mark = 0.6438819816816334  # Actual synthetic fixture corner 3, not its PRIME emission point.
    signal = voice_signal()
    live.write_wav(bank_dir / "brake.wav", signal, RATE)
    entry = ClipEntry(
        "brake",
        "brake.wav",
        "late_brake",
        "act",
        "critical",
        None,
        "Brake!",
        live.sha(bank_dir / "brake.wav"),
    )
    manifest = Manifest(
        MANIFEST_VERSION,
        RATE,
        "test+" + vocabulary.EXPECTED_SIGNATURE_SUFFIX,
        vocabulary.vocabulary_hash(),
        {"brake": entry},
    )
    live.write_json(bank_dir / "manifest.json", manifest.to_dict())
    recording = np.zeros(RATE * 10)
    chirp = al.make_chirp(RATE, np)
    recording[RATE // 2 : RATE // 2 + len(chirp)] = chirp
    recording[RATE * 9 : RATE * 9 + len(chirp)] = chirp
    recording[RATE * 2 : RATE * 2 + len(signal)] = signal
    live.write_wav(tmp_path / "microphone.wav", recording, RATE)
    live.write_wav(tmp_path / "loopback.wav", recording[:, None], RATE)
    session = dict(session_uuid="synthetic-session", car_id="test-car", track_id="test-track")
    ticks, wire, taps = [], [], []
    for i in range(160):
        t = 100600 + i * 50
        frame = dict(
            v=1,
            type="telemetry_tick",
            seq=i + 1,
            payload=dict(
                lap=2,
                speed_kmh=150,
                spline=mark + (i - 88) * 0.001,
                brake=0.8 if 88 <= i <= 94 else 0,
            ),
        )
        row = dict(wall_ms=t, mono_ms=t, session=session, frame=frame)
        ticks.append(row)
        wire.append(row)
        taps.append(
            dict(
                kind="producer_tick_ingress",
                wall_ms=t,
                mono_ms=t,
                frame=frame,
                tap_run_id="synthetic-tap",
            )
        )
    dispatch = dict(
        seq=1,
        clip_id="brake",
        kind="late_brake",
        urgency="act",
        register="critical",
        corner=None,
        text="Brake!",
        duration_ms=400,
        t_wall_ms=101800,
        t_mono_ms=101800,
        audio_routing="authoritative_pc",
    )
    advisory = dict(
        kind="late_brake",
        urgency="act",
        register="critical",
        corner=3,
        spline=mark,
        message="Brake",
        detail={"anticipatory": True, "brake_point_spline": mark},
    )
    wire.append(
        dict(
            wall_ms=101801,
            mono_ms=101801,
            session=session,
            frame=dict(type="state.snapshot", topic="coaching.voice", payload=dispatch),
        )
    )
    wire.sort(key=lambda row: row["wall_ms"])
    tap_start = dict(kind="tap_start", tap_run_id="synthetic-tap", wall_ms=99000, pid=123)
    taps.insert(0, tap_start)
    taps.append(
        dict(
            kind="advisory_submitted",
            tap_run_id="synthetic-tap",
            wall_ms=101800,
            token="unique-advisory",
            advisory=advisory,
            producer_tick=dict(frame=ticks[24]["frame"], wall_ms=101800, mono_ms=101800),
        )
    )
    taps.append(
        dict(
            kind="resolver_manifest",
            tap_run_id="synthetic-tap",
            wall_ms=99500,
            canonical_sha256=hashlib.sha256(
                json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
    )
    taps.append(
        dict(
            kind="playback_endpoint",
            backend="RtMixerPlayback",
            tap_run_id="synthetic-tap",
            wall_ms=99500,
            details=dict(device_name="Test speaker", host_api="Windows WASAPI"),
        )
    )
    taps.append(
        dict(
            kind="voice_dispatch",
            tap_run_id="synthetic-tap",
            wall_ms=101800,
            exact_object_identity=True,
            dispatch=dispatch,
            correlation=dict(
                token="unique-advisory",
                advisory=advisory,
                producer_tick=dict(frame=ticks[24]["frame"], wall_ms=101800, mono_ms=101800),
            ),
        )
    )
    taps.append(
        dict(
            kind="tap_end",
            tap_run_id="synthetic-tap",
            wall_ms=111000,
            dropped=0,
            writer_error=None,
            source_hashes_unchanged=True,
        )
    )
    tap_path = tmp_path / "tap.jsonl"
    for row in taps:
        row.setdefault("mono_ms", row["wall_ms"])
    for path, rows in ((tmp_path / "wire.jsonl", wire), (tap_path, taps)):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    config = dict(
        bank_dir=str(bank_dir),
        instrument_tap=str(tap_path),
        car_id="test-car",
        track_id="test-track",
        track_length_m=7000,
        reference_archive=str(reference_path),
        attribution_ledger=str(ledger_path),
        microphone={"analysis_channel": 0},
        output_device="Test speaker",
        output_host_api="Windows WASAPI",
    )
    process = dict(pid=123, tap_run_id="synthetic-tap", create_time=12, port=8765)
    capture = dict(
        kind="synthetic_offline_test",
        capture_code_sha256=live.sha(live.__file__),
        capture_code_unchanged=True,
        started_wall_ms=100000,
        started_mono_ms=100000,
        finished_wall_ms=110000,
        finished_mono_ms=110000,
        run_id="synthetic-run",
        config=config,
        recording_complete=True,
        input_hashes_before={
            str(path.resolve()): live.sha(path)
            for path in (bank_dir / "brake.wav", reference_path, ledger_path)
        },
        sidecar_before=process,
        sidecar_after=process,
        chirps=[
            dict(label="start", t_wall_ms=100500, t_dac_wall_ms=100500, output_latency_ms=0),
            dict(label="end", t_wall_ms=109000, t_dac_wall_ms=109000, output_latency_ms=0),
        ],
        microphone=dict(sha256=live.sha(tmp_path / "microphone.wav"), **callback_evidence()),
        loopback=dict(
            sha256=live.sha(tmp_path / "loopback.wav"),
            channels=1,
            statuses=[],
            warnings=[],
            warning_capture_complete=True,
        ),
        wire_sha256=live.sha(tmp_path / "wire.jsonl"),
        reference_qualification=dict(authority="legacy_unknown", allowed=True),
    )
    capture["input_hashes_after"] = capture["input_hashes_before"]
    live.write_json(tmp_path / "capture.json", capture)
    return capture, taps


def test_full_math_pipeline_retains_synthetic_label_and_never_claims_live_pass(
    tmp_path, single_phrase_completeness
):
    build_bundle(tmp_path)
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert report["failed_gates"] == ["actual_capture_kind"]
    assert report["engineering_acceptance"] == "NO_GO"
    assert report["cues"][0]["corner"] == 3  # generic act dispatch had corner=None
    assert report["cues"][0]["minimum_completion_lead_ms"] > 1200
    assert report["timely_brake_coverage"] == 1
    assert report["human_live_qualification"].startswith("NOT_ESTABLISHED")


def test_explicit_cancellation_fails_even_if_waveform_was_captured(tmp_path):
    capture, taps = build_bundle(tmp_path)
    taps.insert(
        -1,
        dict(
            kind="playback_cancel",
            tap_run_id="synthetic-tap",
            wall_ms=102100,
            token="unique-advisory",
        ),
    )
    Path(capture["config"]["instrument_tap"]).write_text(
        "".join(json.dumps(row) + "\n" for row in taps)
    )
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["no_canceled_phrases"]
    assert report["cues"][0]["cancellations"]


def test_ambiguous_exact_object_dispatch_is_not_guessed(tmp_path):
    capture, taps = build_bundle(tmp_path)
    taps.insert(-1, next(row for row in taps if row["kind"] == "voice_dispatch"))
    Path(capture["config"]["instrument_tap"]).write_text(
        "".join(json.dumps(row) + "\n" for row in taps)
    )
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["all_cues_exactly_correlated"]
    assert "minimum_completion_lead_ms" not in report["cues"][0]


def test_input_hash_drift_cannot_pass(tmp_path):
    capture, _ = build_bundle(tmp_path)
    Path(capture["config"]["bank_dir"], "brake.wav").write_bytes(b"changed")
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["inputs_still_unchanged"]
    assert not report["gates"]["all_phrases_captured_complete"]


def test_read_jsonl_refuses_partial_tap(tmp_path):
    path = tmp_path / "partial.jsonl"
    path.write_text('{"kind":')
    with pytest.raises(json.JSONDecodeError):
        live.read_jsonl(path)


def test_existing_outputs_are_not_overwritten(tmp_path):
    path = tmp_path / "receipt.json"
    live.write_json(path, {"original": True})
    with pytest.raises(FileExistsError):
        live.write_json(path, {"replacement": True})
    assert json.loads(path.read_text()) == {"original": True}


def recording_config():
    return dict(
        bank_dir="bank",
        reference_archive="reference",
        attribution_ledger="ledger",
        car_id="car",
        track_id="track",
        track_length_m=7000,
        seconds=5,
        microphone={"name": "Mic"},
        output_device="Speaker",
        output_host_api="Windows WASAPI",
        instrument_tap="tap",
        sidecar_url="ws://127.0.0.1:8765",
        http_url="http://127.0.0.1:8765",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8765",
        "http://127.0.0.1.evil.test:8765",
        "http://secret@127.0.0.1:8765",
        "http://127.0.0.1:8765?token=secret",
    ],
)
def test_config_rejects_nonlocal_or_credential_urls(url):
    config = recording_config()
    config["http_url"] = url
    with pytest.raises(ValueError):
        live.validate_config(config)


def test_channel_map_uses_shared_validation_and_preserves_explicit_selection():
    config = recording_config()
    config["output_channel_map"] = "5,6"
    assert live.validate_config(config)["output_channel_map"] == [5, 6]
    config["output_channel_map"] = "5,5"
    with pytest.raises(ValueError):
        live.validate_config(config)


def test_different_actual_playback_channel_map_fails(tmp_path):
    capture, _ = build_bundle(tmp_path)
    capture["config"]["output_channel_map"] = [5, 6]
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["one_matching_output_endpoint"]


def test_failed_rig_ownership_never_opens_audio_or_network(tmp_path, monkeypatch):
    def rejected(pid):
        raise RuntimeError("different rig owner")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not reach hardware/network")

    monkeypatch.setattr(live, "verify_owner", rejected)
    monkeypatch.setattr(live, "health", forbidden)
    monkeypatch.setattr(live, "Microphone", forbidden)
    monkeypatch.setattr(live.al, "play_chirp", forbidden)
    receipt = live.record(recording_config(), tmp_path / "new-run", 123)
    assert not receipt["recording_complete"]
    assert "different rig owner" in receipt["errors"][0]
    assert not (tmp_path / "new-run" / "microphone.wav").exists()


def test_capture_orchestration_closes_only_owned_resources(tmp_path, monkeypatch):
    calls = []
    original = tmp_path / "protected"
    original.write_bytes(b"protected bytes")
    config = recording_config()
    config["loopback"] = {"speaker_name": "Speaker"}
    monkeypatch.setattr(live, "verify_owner", lambda pid: dict(pid=pid))
    monkeypatch.setattr(
        live,
        "immutable_inputs",
        lambda cfg: ({str(original): live.sha(original)}, {"authority": "legacy_unknown"}),
    )
    monkeypatch.setattr(live, "health", lambda cfg: {"voice": "unit-test-double"})
    monkeypatch.setattr(live, "sidecar_process", lambda cfg: {"pid": 456, "port": 8765})
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            query_devices=lambda: [dict(name="Speaker", hostapi=0, max_output_channels=6)],
            query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        ),
    )

    class CaptureDouble:
        def __init__(self, *args):
            self.tag = "microphone" if len(args) == 2 else "loopback"

        def start(self):
            calls.append(self.tag + ":start")

        def finish(self, path):
            calls.append(self.tag + ":finish")
            path.write_bytes(b"unit test only; not WAV")
            return dict(file=str(path), sha256=live.sha(path), statuses=[])

    monkeypatch.setattr(live, "Microphone", CaptureDouble)
    monkeypatch.setattr(live, "Loopback", CaptureDouble)
    monkeypatch.setattr(live.al, "play_chirp", lambda label, **kwargs: al.ChirpMark(label, 1, 1, 0))
    counter = [0]

    def advancing_clock():
        counter[0] += 0.25
        return counter[0]

    monkeypatch.setattr(live.time, "monotonic", advancing_clock)
    monkeypatch.setattr(live.time, "sleep", lambda duration: None)

    async def wire(cfg, path, ready, stop):
        path.write_text("unit test fake wire", encoding="utf-8")
        ready.set()
        while not stop.is_set():
            stop.wait(0.001)

    monkeypatch.setattr(live, "record_wire", wire)
    receipt = live.record(config, tmp_path / "new-run", 123)
    assert receipt["recording_complete"]
    assert receipt["input_hashes_before"] == receipt["input_hashes_after"]
    assert calls == ["microphone:start", "loopback:start", "microphone:finish", "loopback:finish"]
    assert not any(
        t.name in ("acceptance-wire", "acceptance-loopback") for t in threading.enumerate()
    )


def test_wall_clock_step_is_diagnostic_but_a_broken_monotonic_interval_fails(tmp_path):
    capture, _ = build_bundle(tmp_path)
    baseline = live.analyze_bundle(tmp_path, tmp_path / "baseline.json")
    capture["finished_wall_ms"] += 1000  # NTP step/slew: the wall clock is not a join basis.
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    stepped = live.analyze_bundle(tmp_path, tmp_path / "stepped.json")
    assert stepped["timebase"] == "monotonic"
    assert stepped["gates"] == baseline["gates"]
    assert stepped["wall_clock_drift"]["spread_ms"] == 1000
    assert stepped["wall_clock_drift"]["gating"] is False
    capture["finished_mono_ms"] = capture["started_mono_ms"] - 1
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    broken = live.analyze_bundle(tmp_path, tmp_path / "broken.json")
    assert not broken["gates"]["monotonic_timebase_valid"]
    assert "capture_monotonic_interval_invalid" in broken["monotonic_timebase"]["reasons"]
    assert not broken["gates"]["microphone_timebase_qualified"]


@pytest.mark.parametrize(
    "advisory, expected",
    [
        (
            {"kind": "late_brake", "urgency": "prepare", "detail": {"anticipatory": True}},
            "anticipatory_brake",
        ),
        ({"kind": "late_brake", "urgency": "act", "detail": {}}, "diagnostic_or_other"),
        (
            {"kind": "late_brake", "urgency": "info", "detail": {"anticipatory": True}},
            "diagnostic_or_other",
        ),
        ({"kind": "save", "urgency": "act", "detail": {"coach": "save"}}, "reactive_save"),
        (
            {
                "kind": "early_brake",
                "urgency": "prepare",
                "detail": {"coach": "prime", "root": "early_brake"},
            },
            "anticipatory_brake",
        ),
        (
            {
                "kind": "brake_late",
                "urgency": "prepare",
                "detail": {"coach": "prime", "root": "brake_late"},
            },
            "anticipatory_brake",
        ),
        (
            {
                "kind": "no_trail",
                "urgency": "prepare",
                "detail": {"coach": "prime", "root": "no_trail"},
            },
            "diagnostic_or_other",
        ),
    ],
)
def test_timing_class_uses_actual_producer_semantics(advisory, expected):
    assert live.cue_timing_class(advisory) == expected


def rewrite_taps(capture, taps):
    Path(capture["config"]["instrument_tap"]).write_text(
        "".join(json.dumps(row) + "\n" for row in taps)
    )


@pytest.mark.parametrize("kind", ["early_brake", "brake_late"])
def test_prime_matches_reference_corner_not_emission_position(
    tmp_path, kind, single_phrase_completeness
):
    capture, taps = build_bundle(tmp_path)
    advisory = next(row for row in taps if row["kind"] == "advisory_submitted")["advisory"]
    advisory.update(kind=kind, spline=0.60, detail={"coach": "prime", "root": kind})
    rewrite_taps(capture, taps)
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    cue = report["cues"][0]
    assert cue["timing_class"] == "anticipatory_brake"
    assert cue["brake_target_basis"] == "reference_corner_geometry"
    assert abs(cue["brake_target_spline"] - advisory["spline"]) * 7000 > 50
    assert cue["brake_match_count"] == 1
    assert cue["minimum_completion_lead_ms"] > 1200
    assert report["anticipatory_assessment"]["coverage_denominator"] == 1


def test_reactive_save_keeps_acoustic_and_act_gates_without_false_anticipatory_pass(
    tmp_path, single_phrase_completeness
):
    capture, taps = build_bundle(tmp_path)
    advisory = next(row for row in taps if row["kind"] == "advisory_submitted")["advisory"]
    advisory.update(kind="save", detail={"coach": "save"})
    rewrite_taps(capture, taps)
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert report["gates"]["all_phrases_captured_complete"]
    assert report["gates"]["act_latency_budget"]
    assert not report["gates"]["brake_cues_complete_with_reaction_lead"]
    assert not report["gates"]["timely_brake_coverage"]
    assert report["timely_brake_coverage"] is None
    assert "minimum_completion_lead_ms" not in report["cues"][0]
    assert report["cue_timing_counts"] == dict(
        anticipatory_brake=0, reactive_save=1, diagnostic_or_other=0
    )


def test_brake_target_requires_same_corner_and_unambiguous_measured_event():
    advisory = dict(corner=1, detail={"brake_point_spline": 0.2})
    targets = {1: dict(spline_lo=0.19, spline_hi=0.3)}
    event = dict(event_id=1, lap=2, spline=0.2, end_spline=0.21)
    assert (
        live.match_brake_target(advisory, {"lap": 2}, [event], targets, 7000)["brake_event_id"] == 1
    )
    assert (
        live.match_brake_target(advisory, {"lap": 2}, [event, event], targets, 7000)[
            "brake_match_count"
        ]
        == 2
    )
    assert "brake_event_id" not in live.match_brake_target(
        {**advisory, "corner": 2}, {"lap": 2}, [event], targets, 7000
    )
    assert "brake_event_id" not in live.match_brake_target(
        advisory, {"lap": 3}, [event], targets, 7000
    )


def test_coverage_counts_submitted_targets_including_dropped_cues_not_all_lap_brakes():
    events = [
        dict(event_id=i, lap=2, spline=s, end_spline=s + 0.01)
        for i, s in enumerate([0.2, 0.4, 0.6])
    ]
    targets = {1: dict(spline_lo=0.19, spline_hi=0.5)}

    def submission(mark):
        return dict(
            advisory=dict(
                kind="late_brake",
                urgency="prepare",
                corner=1,
                detail={"anticipatory": True, "brake_point_spline": mark},
            ),
            producer_tick={"frame": {"payload": {"lap": 2}}},
        )

    cues = [
        dict(timing_class="anticipatory_brake", brake_event_id=0, minimum_completion_lead_ms=1300)
    ]
    config = {"track_length_m": 7000}
    one = live.anticipatory_assessment(cues, [submission(0.2)], events, targets, config)
    assert one["timely_brake_coverage"] == 1  # Two other pedal events were never selected to coach.
    assert one["all_eligible_corner_coverage"].startswith("NOT_ESTABLISHED")
    dropped = live.anticipatory_assessment(
        cues, [submission(0.2), submission(0.4)], events, targets, config
    )
    assert dropped["timely_brake_coverage"] == 0.5
    assert not dropped["coverage_gate"]
    ambiguous = live.anticipatory_assessment(
        cues, [submission(0.2), submission(0.9)], events, targets, config
    )
    assert ambiguous["unmatched_target_count"] == 1
    assert ambiguous["timely_brake_coverage"] == 0.5


@pytest.mark.parametrize("result, balanced", [(0, True), (1, True), (-2147417850, False)])
def test_com_apartment_balances_only_owned_initialization_even_on_error(result, balanced):
    calls = []
    ole32 = SimpleNamespace(
        CoInitializeEx=lambda reserved, mode: calls.append((reserved, mode)) or result,
        CoUninitialize=lambda: calls.append("uninitialize"),
    )
    with pytest.raises(ValueError, match="record failure"):
        with live.com_apartment(ole32):
            raise ValueError("record failure")
    assert calls == [(None, 0)] + (["uninitialize"] if balanced else [])


def test_com_apartment_failure_cannot_open_recorder_or_uninitialize_unowned_state():
    calls = []
    ole32 = SimpleNamespace(
        CoInitializeEx=lambda reserved, mode: -2147467259,  # E_FAIL
        CoUninitialize=lambda: calls.append("uninitialize"),
    )
    with pytest.raises(RuntimeError, match="0x80004005"):
        with live.com_apartment(ole32):
            calls.append("unexpected recorder")
    assert calls == []


@pytest.mark.parametrize("failure", [False, True])
def test_loopback_com_and_recorder_lifecycle_share_the_worker_thread(monkeypatch, failure):
    capture = live.Loopback.__new__(live.Loopback)
    capture.spec = {"samplerate": RATE}
    capture.stop, capture.ready = threading.Event(), threading.Event()
    capture.blocks, capture.error = [], None
    capture.warning_records = []
    capture.warning_capture_complete = False
    capture.warning_module = SimpleNamespace(warnings=SimpleNamespace(warn=lambda *a, **k: None))
    calls = []

    def note(event):
        calls.append((event, threading.get_ident()))

    ole32 = SimpleNamespace(
        CoInitializeEx=lambda reserved, mode: note("initialize") or 0,
        CoUninitialize=lambda: note("uninitialize"),
    )
    original = live.com_apartment
    monkeypatch.setattr(live, "com_apartment", lambda: original(ole32))

    class Recorder:
        def __enter__(self):
            note("recorder_enter")
            return self

        def record(self, numframes):
            note("record")
            capture.stop.set()
            if failure:
                raise RuntimeError("test failure")
            return np.zeros((numframes, 2))

        def __exit__(self, *args):
            note("recorder_exit")

    capture.device = SimpleNamespace(recorder=lambda **kwargs: Recorder())
    worker = threading.Thread(target=capture._record)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    assert [event for event, _ in calls] == [
        "initialize",
        "recorder_enter",
        "record",
        "recorder_exit",
        "uninitialize",
    ]
    assert {thread_id for _, thread_id in calls} == {worker.ident}
    assert worker.ident != threading.get_ident()
    assert (capture.error is not None) is failure
    assert capture.ready.is_set()


def test_overlapping_suffix_cannot_count_as_a_second_complete_physical_phrase():
    signal = voice_signal()
    recording = np.zeros(RATE * 4)
    recording[RATE : RATE + len(signal)] = signal
    bank = Bank(samplerate=RATE, clips={"full": signal, "suffix": signal[480:]}, channels=1)
    cues = live.match_audio(
        recording,
        RATE,
        al.ClockMap(0, 100000, 1000 / RATE, anchors_used=2),
        [
            dict(seq=1, clip_id="full", t_mono_ms=100800),
            dict(seq=2, clip_id="suffix", t_mono_ms=100850),
        ],
        bank,
    )
    assert cues[0]["complete"]
    assert cues[1]["matched"]
    assert not cues[1]["complete"]
    assert cues[1]["completion_ms"] is None
    assert cues[1]["reason"] == "acoustic_interval_already_assigned"


def test_physical_dispatch_missing_from_wire_is_not_silently_omitted(tmp_path):
    capture, taps = build_bundle(tmp_path)
    physical = json.loads(json.dumps(next(row for row in taps if row["kind"] == "voice_dispatch")))
    physical.update(wall_ms=106000, mono_ms=106000)
    physical["dispatch"].update(seq=2, t_wall_ms=106000, t_mono_ms=106000)
    physical["correlation"]["token"] = "second-physical-cue"
    taps.insert(-1, physical)
    rewrite_taps(capture, taps)
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["physical_dispatch_wire_bijection"]


def test_dispatch_without_monotonic_stamp_fails_a_gate_instead_of_crashing(tmp_path):
    capture, _ = build_bundle(tmp_path)
    wire_path = tmp_path / "wire.jsonl"
    wire = live.read_jsonl(wire_path)
    for row in wire:
        if row["frame"].get("topic") == "coaching.voice":
            del row["frame"]["payload"]["t_mono_ms"]  # a legacy/malformed producer payload
    wire_path.write_text("".join(json.dumps(row) + "\n" for row in wire))
    capture["wire_sha256"] = live.sha(wire_path)
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["dispatch_monotonic_stamped"]
    assert not report["gates"]["cues_present"]
    assert report["engineering_acceptance"] == "NO_GO"


def test_unconvertible_chirp_writes_an_explicit_no_go_report(tmp_path, monkeypatch, capsys):
    capture, _ = build_bundle(tmp_path)
    capture["chirps"][1]["t_dac_wall_ms"] = 1.0  # no recorder stamp within one second
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    out = tmp_path / "analysis.json"
    monkeypatch.setattr(
        sys, "argv", ["live_acceptance", "analyze", "--capture", str(tmp_path), "--out", str(out)]
    )
    assert live.main() == 2
    written = json.loads(out.read_text())
    assert written["engineering_acceptance"] == "NO_GO"
    assert written["failed_gates"] == ["analysis_incomplete"]
    assert "monotonic DAC anchor" in written["error"]
    assert json.loads(capsys.readouterr().out)["acceptance"] == "NO_GO"


def test_cue_producer_must_match_actual_current_session_ingress(tmp_path):
    capture, taps = build_bundle(tmp_path)
    for row in taps:
        producer = row.get("producer_tick") or (row.get("correlation") or {}).get("producer_tick")
        if producer:
            producer["frame"] = {**producer["frame"], "seq": 999999}
    rewrite_taps(capture, taps)
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["all_cues_exactly_correlated"]
    assert not report["gates"]["submitted_producers_verified"]
    assert not report["cues"][0]["producer_tick_verified"]
    assert "minimum_completion_lead_ms" not in report["cues"][0]


def test_temporary_wall_clock_step_cannot_move_brake_or_reaction_timing(tmp_path):
    capture, taps = build_bundle(tmp_path)
    baseline = live.analyze_bundle(tmp_path, tmp_path / "baseline.json")
    wire_path = tmp_path / "wire.jsonl"
    wire = live.read_jsonl(wire_path)
    for row in wire + taps:
        frame = row.get("frame") or {}
        if frame.get("type") == "telemetry_tick" and 89 <= frame["seq"] <= 95:
            row["wall_ms"] += 40  # Returns to the initial wall offset before capture ends.
    wire_path.write_text("".join(json.dumps(row) + "\n" for row in wire))
    capture["wire_sha256"] = live.sha(wire_path)
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    rewrite_taps(capture, taps)
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert report["wall_clock_drift"]["spread_ms"] == 40  # still visible, never a join basis
    assert report["brake_events"] == baseline["brake_events"]
    assert report["gates"] == baseline["gates"]
    for key in ("minimum_completion_lead_ms", "maximum_completion_lead_ms", "latency_ms"):
        assert report["cues"][0].get(key) == baseline["cues"][0].get(key)


def test_wire_monotonic_disorder_fails_the_timebase(tmp_path):
    capture, _ = build_bundle(tmp_path)
    wire_path = tmp_path / "wire.jsonl"
    wire = live.read_jsonl(wire_path)
    wire[40]["mono_ms"] = wire[39]["mono_ms"] - 5  # a single writer cannot run backwards
    wire_path.write_text("".join(json.dumps(row) + "\n" for row in wire))
    capture["wire_sha256"] = live.sha(wire_path)
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert "wire_monotonic_order_violated" in report["monotonic_timebase"]["reasons"]
    assert not report["gates"]["microphone_timebase_qualified"]


@pytest.mark.parametrize("info", [None, {"monotonic": True, "resolution": 0.015625}])
def test_millisecond_tick_monotonic_clock_is_rejected(info):
    # Python < 3.13 on Windows backs time.monotonic with GetTickCount64 (15.6 ms ticks).
    capture = dict(started_mono_ms=1.0, finished_mono_ms=2.0, monotonic_clock=info)
    capture["microphone"] = callback_evidence(start=100000)
    for row in capture["microphone"]["callback_stamps"]:
        row["mono_ms"] = float(round(row["mono_ms"] / 15.625) * 15)
    if info is not None:
        capture["microphone"] = callback_evidence()
    result = live.monotonic_timebase_evidence(capture, [], [], 0, 1)
    assert not result["passed"]
    expected = (
        "monotonic_resolution_unproven" if info is None else "monotonic_clock_info_inadequate"
    )
    assert expected in result["reasons"]


def test_legacy_wall_only_chirp_converts_through_its_local_offset():
    stamps = callback_evidence()["callback_stamps"]
    for row in stamps:  # wall leads monotonic by 5 s and is slewing at ~78 ppm
        row["wall_ms"] = row["mono_ms"] + 5000 + (row["mono_ms"] - 100000) * 78e-6
    wall = 104000.0 + 5000 + 4000 * 78e-6
    legacy = live.chirp_monotonic_anchor(al.ChirpMark("start", wall, wall, 0), stamps)
    assert legacy["basis"] == "wall_converted_with_local_offset"
    assert legacy["anchor_ms"] == pytest.approx(104000.0, abs=0.2)
    assert legacy["uncertainty_ms"] < 0.2
    recorded = live.chirp_monotonic_anchor(
        al.ChirpMark("start", wall, wall, 0, t_dac_mono_ms=104000.5), stamps
    )
    assert (recorded["basis"], recorded["anchor_ms"]) == ("recorded", 104000.5)
    lost = live.chirp_monotonic_anchor(al.ChirpMark("end", 1.0, 1.0, 0), stamps)
    assert lost["anchor_ms"] is None


def test_matching_corrects_template_time_scale_using_calibrated_sample_period():
    signal = voice_signal()
    effective_rate = RATE * 1.005
    stretched = al._resample_linear(signal, RATE, effective_rate, np)
    recording = np.zeros(RATE * 4)
    onset = round(effective_rate)
    recording[onset : onset + len(stretched)] = stretched
    bank = Bank(samplerate=RATE, clips={"brake": signal}, channels=1)
    cue = live.match_audio(
        recording,
        RATE,
        al.ClockMap(0, 100000, 1000 / effective_rate, anchors_used=2),
        [dict(seq=1, clip_id="brake", t_mono_ms=100800)],
        bank,
    )[0]
    assert cue["complete"]
    assert cue["template_effective_samplerate"] == pytest.approx(effective_rate)
    assert cue["latency_ms"] == pytest.approx(200, abs=1)
    assert cue["completion_ms"] == pytest.approx(101400, abs=2)


def test_microphone_records_every_callback_buffer_without_opening_hardware(monkeypatch):
    callbacks = []
    sd = SimpleNamespace(
        query_devices=lambda: [dict(name="Mic", hostapi=0, max_input_channels=1)],
        query_hostapis=lambda: [dict(name="Windows WASAPI")],
        check_input_settings=lambda **kwargs: None,
        get_portaudio_version=lambda: (190700, "synthetic-test"),
        InputStream=lambda **kwargs: callbacks.append(kwargs["callback"]),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    capture = live.Microphone(
        dict(name="Mic", host_api="Windows WASAPI", channels=1, samplerate=RATE), 1
    )
    for i, frames in enumerate((480, 240, 480)):
        callbacks[0](
            np.zeros((frames, 1)),
            frames,
            SimpleNamespace(inputBufferAdcTime=1 + i, currentTime=1 + i),
            None,
        )
    assert [(row["sample"], row["frames"]) for row in capture.stamps] == [
        (0, 480),
        (480, 240),
        (720, 480),
    ]


@pytest.mark.parametrize(
    "defect", ["sparse", "missing_size", "bad_count", "rate", "overflow", "mono", "warp"]
)
def test_independent_clock_evidence_rejects_incomplete_or_nonlinear_capture(defect):
    metadata = callback_evidence()
    rows = metadata["callback_stamps"]
    if defect == "sparse":
        metadata["callback_stamps"] = rows[::100]
    elif defect == "missing_size":
        del rows[3]["frames"]
    elif defect == "bad_count":
        metadata["frames"] -= 1
    elif defect == "rate":
        metadata["samplerate"] = 44100
    elif defect == "overflow":
        metadata["statuses"] = ["input overflow"]
    elif defect == "mono":
        rows[50]["mono_ms"] = rows[49]["mono_ms"]
    else:
        for i, row in enumerate(rows):
            displacement = 25 * np.sin(i / len(rows) * 2 * np.pi)
            row["mono_ms"] += displacement
            row["adc_time"] += displacement / 1000
    result = live.callback_clock_evidence(metadata, RATE * 10, RATE)
    assert not result["passed"]
    assert result["reasons"]


def test_wasapi_adc_estimate_is_reported_but_not_fitted_as_a_second_clock():
    # Run 02 of #815: PortAudio WASAPI reported adc = stream time + 10 or 20 ms. A buffer
    # delivered back to back after a late one stepped "ADC time" backwards 90 times while
    # the samples themselves stayed contiguous and uniformly spaced.
    metadata = callback_evidence()
    rows = metadata["callback_stamps"]
    late = range(49, len(rows), 250)
    for i, row in enumerate(rows):
        if i in late:  # delivered ~one period late, immediately followed by the next buffer
            row["mono_ms"] += 9.9
        row["stream_time"] = row["mono_ms"] / 1000
        row["adc_time"] = row["stream_time"] + (0.020 if i in late else 0.010)
    result = live.callback_clock_evidence(metadata, RATE * 10, RATE)
    assert result["passed"]
    assert list(result["fits"]) == ["mono_ms"]
    diagnostic = result["adc_time_diagnostic"]
    assert diagnostic["gating"] is False
    assert diagnostic["nonincreasing_steps"] == len(late)
    assert diagnostic["adc_minus_stream_ms"] == [10.0, 20.0]


def room_bundle_audio(tmp_path, capture, *, chirp_seconds=(0.5, 9)):
    """Reverberant chirps under strong low-frequency engine tone (no voice phrase)."""
    rng = np.random.default_rng(815)
    t = np.arange(int(0.25 * RATE)) / RATE
    response = rng.normal(0, 1, len(t)) * np.exp(-t / 0.06)
    response[0] = 6.0  # direct path dominates every individual reflection
    response /= np.sqrt(np.sum(response**2))
    room_chirp = np.convolve(al.make_chirp(RATE, np), response)
    recording = np.zeros(RATE * 10)
    for seconds in chirp_seconds:
        onset = round(RATE * seconds)
        recording[onset : onset + len(room_chirp)] += room_chirp
    tt = np.arange(len(recording)) / RATE
    recording += 0.2 * (np.sin(2 * np.pi * 110 * tt) + 0.5 * np.sin(2 * np.pi * 220 * tt + 1))
    recording += 0.002 * rng.normal(0, 1, len(recording))
    live.write_wav(tmp_path / "microphone.wav", recording, RATE)
    capture["microphone"] = dict(
        sha256=live.sha(tmp_path / "microphone.wav"),
        **callback_evidence(frames=len(recording)),
    )
    return recording


def test_reverberant_acoustic_chirps_anchor_inside_band_with_independent_agreement(tmp_path):
    capture, _ = build_bundle(tmp_path)
    recording = room_bundle_audio(tmp_path, capture)
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    chirps = [al.ChirpMark(**mark) for mark in capture["chirps"]]
    with pytest.raises(ValueError, match="no sync chirp"):
        al.build_clock_map(recording, RATE, chirps, np)  # near-field floor rejects the room
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    clock = report["microphone_clock"]
    assert report["gates"]["microphone_timebase_qualified"]
    assert clock["qualified"]
    assert [mark["onset_sample"] for mark in clock["chirps"]] == [RATE // 2, RATE * 9]
    for mark in clock["chirps"]:
        assert live.ACOUSTIC_CHIRP_MIN_SCORE <= mark["score"] < al.MATCH_MIN_SCORE
        assert mark["prominence"] >= live.ACOUSTIC_CHIRP_MIN_PROMINENCE
        assert mark["band_hz"] == list(live.acoustic_chirp_band(chirps, RATE))
    assert clock["uncertainty_components_ms"]["anchor_slope_disagreement"] < 1


def test_relaxed_acoustic_floor_cannot_invent_a_missing_end_anchor(tmp_path):
    capture, _ = build_bundle(tmp_path)
    room_bundle_audio(tmp_path, capture, chirp_seconds=(0.5,))
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    clock = report["microphone_clock"]
    assert [mark["onset_sample"] for mark in clock["chirps"]] == [RATE // 2, None]
    assert not report["gates"]["microphone_clock_calibrated"]
    assert not report["gates"]["microphone_timebase_qualified"]
    assert clock["reasons"] == ["two_ordered_dac_anchors_required"]


def test_engine_tone_alone_never_becomes_an_acoustic_anchor(tmp_path):
    capture, _ = build_bundle(tmp_path)
    room_bundle_audio(tmp_path, capture, chirp_seconds=())
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    with pytest.raises(ValueError, match="no sync chirp"):
        live.analyze_bundle(tmp_path, tmp_path / "result.json")


def replace_bundle_audio(tmp_path, capture, *, effective_rate=RATE, onset_seconds=2):
    recording = np.zeros(round(effective_rate * 10))
    chirp = al.make_chirp(effective_rate, np)
    for seconds in (0.5, 9):
        onset = round(effective_rate * seconds)
        recording[onset : onset + len(chirp)] = chirp
    phrase = al._resample_linear(voice_signal(), RATE, effective_rate, np)
    onset = round(effective_rate * onset_seconds)
    recording[onset : onset + len(phrase)] = phrase
    live.write_wav(tmp_path / "microphone.wav", recording, RATE)
    capture["microphone"] = dict(
        sha256=live.sha(tmp_path / "microphone.wav"),
        **callback_evidence(frames=len(recording), period=1000 / effective_rate),
    )


def test_large_stable_skew_needs_independent_proof_and_preserves_nominal_diagnostic(
    tmp_path, single_phrase_completeness
):
    capture, _ = build_bundle(tmp_path)
    replace_bundle_audio(tmp_path, capture, effective_rate=RATE / 0.9962)
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert report["failed_gates"] == ["actual_capture_kind"]
    assert report["engineering_acceptance"] == "NO_GO"
    clock = report["microphone_clock"]
    assert not clock["nominal_drift_bounded"]
    assert clock["nominal_drift_limit_ppm"] == 1000
    assert clock["qualified"]
    assert clock["chirp_template_samplerate"] == pytest.approx(RATE / 0.9962)
    assert all(mark["score"] > 0.9 for mark in clock["chirps"])
    assert clock["systematic_uncertainty_ms"] >= 15
    assert report["cues"][0]["latency_ms"] == pytest.approx(200, abs=1)


@pytest.mark.parametrize(
    "defect",
    [
        "no_dac",
        "one_anchor",
        "different_clock",
        "nan_period",
        "negative_period",
        "short_span",
        "outside_samples",
    ],
)
def test_two_acoustic_anchors_alone_do_not_qualify_timebase(defect):
    metadata = callback_evidence()
    independent = live.callback_clock_evidence(metadata, metadata["frames"], RATE)
    period = 1000 / RATE
    chirps = [al.ChirpMark("start", 100000, 100000, 0), al.ChirpMark("end", 109000, 109000, 0)]
    marks = [dict(label="start", onset_sample=0), dict(label="end", onset_sample=RATE * 9)]
    anchors = 2
    if defect == "no_dac":
        chirps[1] = al.ChirpMark("end", 109000, None, 0)
    elif defect == "one_anchor":
        anchors = 1
    elif defect == "different_clock":
        period *= 1.004
    elif defect == "nan_period":
        period = float("nan")
    elif defect == "negative_period":
        period = -period
        marks[1]["onset_sample"] = 1
    elif defect == "short_span":
        marks[1]["onset_sample"] = RATE // 2
    else:
        marks[1]["onset_sample"] = RATE * 10
    evidence = live.microphone_clock_evidence(
        al.ClockMap(0, 100000, period, anchors, "monotonic"),
        marks,
        [live.chirp_monotonic_anchor(mark, metadata["callback_stamps"]) for mark in chirps],
        independent,
        RATE,
        dict(passed=True),
    )
    assert not evidence["qualified"]
    assert evidence["reasons"]


@pytest.mark.parametrize("onset_seconds", [2.23, 3.33])
def test_measured_uncertainty_is_carried_into_act_latency_and_both_brake_bounds(
    tmp_path, onset_seconds, single_phrase_completeness
):
    capture, _ = build_bundle(tmp_path)
    replace_bundle_audio(tmp_path, capture, onset_seconds=onset_seconds)
    capture["microphone"].update(callback_evidence(buffer_frames=4800))
    for i, row in enumerate(capture["microphone"]["callback_stamps"]):
        displacement = 7 * (-1) ** i
        row["mono_ms"] += displacement
        row["wall_ms"] += displacement
        row["adc_time"] += displacement / 1000
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    uncertainty = report["microphone_clock"]["systematic_uncertainty_ms"]
    assert report["gates"]["microphone_timebase_qualified"]
    assert uncertainty > 20
    cue = report["cues"][0]
    if onset_seconds == 2.23:
        assert cue["latency_ms"] + 15 < 450
    assert cue["maximum_latency_ms"] == pytest.approx(cue["latency_ms"] + uncertainty)
    assert cue["minimum_latency_ms"] == pytest.approx(cue["latency_ms"] - uncertainty)
    assert not report["gates"]["act_latency_budget"]
    event = report["brake_events"][0]
    if onset_seconds == 3.33:
        assert event["earliest_ms"] - cue["completion_ms"] - 15 >= 1200
        assert cue["minimum_completion_lead_ms"] < 1200
        assert not report["gates"]["brake_cues_complete_with_reaction_lead"]
    assert cue["minimum_completion_lead_ms"] == pytest.approx(
        event["earliest_ms"] - cue["completion_ms"] - uncertainty
    )
    assert cue["maximum_completion_lead_ms"] == pytest.approx(
        event["onset_ms"] - cue["completion_ms"] + uncertainty
    )


@pytest.mark.parametrize("onset_seconds", [0.1, 8.8])
def test_cues_must_fit_entirely_between_calibration_anchors(tmp_path, onset_seconds):
    capture, _ = build_bundle(tmp_path)
    replace_bundle_audio(tmp_path, capture, onset_seconds=onset_seconds)
    dispatch_time = 100000 + onset_seconds * 1000 - 200
    wire = live.read_jsonl(tmp_path / "wire.jsonl")
    taps = live.read_jsonl(Path(capture["config"]["instrument_tap"]))
    for row in wire:
        if row["frame"].get("topic") == "coaching.voice":
            row["frame"]["payload"]["t_wall_ms"] = dispatch_time
            row["frame"]["payload"]["t_mono_ms"] = dispatch_time
    for row in taps:
        if row["kind"] == "voice_dispatch":
            row["dispatch"]["t_wall_ms"] = dispatch_time
            row["dispatch"]["t_mono_ms"] = dispatch_time
    for path, rows in (
        (tmp_path / "wire.jsonl", wire),
        (Path(capture["config"]["instrument_tap"]), taps),
    ):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    capture["wire_sha256"] = live.sha(tmp_path / "wire.jsonl")
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["all_phrases_inside_calibration"]
    assert "minimum_completion_lead_ms" not in report["cues"][0]


def test_loopback_warning_capture_scopes_owner_and_preserves_foreign_dispatch():
    import warnings

    forwarded, recorded = [], []
    original = SimpleNamespace(warn=lambda *args, **kwargs: forwarded.append((args, kwargs)))
    backend = SimpleNamespace(warnings=original)
    global_filters, global_dispatch = warnings.filters, warnings.showwarning
    with live.soundcard_warning_capture(backend, recorded):
        backend.warnings.warn("data discontinuity in recording", RuntimeWarning)
        worker = threading.Thread(
            target=lambda: backend.warnings.warn("foreign warning", UserWarning)
        )
        worker.start()
        worker.join()
        assert warnings.filters is global_filters and warnings.showwarning is global_dispatch
    assert backend.warnings is original
    assert [row["message"] for row in recorded] == ["data discontinuity in recording"]
    assert [args[0] for args, _ in forwarded] == [
        "data discontinuity in recording",
        "foreign warning",
    ]


def test_loopback_warning_proxy_preserves_real_warning_filename_and_stacklevel():
    import warnings

    backend = SimpleNamespace(warnings=warnings)
    recorded = []

    def outer_warning():
        backend.warnings.warn("outer caller", RuntimeWarning, stacklevel=2)

    with pytest.warns(RuntimeWarning) as emitted:
        with live.soundcard_warning_capture(backend, recorded):
            backend.warnings.warn("owned caller", RuntimeWarning)
            outer_warning()
            worker = threading.Thread(
                target=lambda: backend.warnings.warn("foreign caller", RuntimeWarning)
            )
            worker.start()
            worker.join()
    assert all(Path(row.filename).resolve() == Path(__file__).resolve() for row in emitted)
    assert len(emitted) == 3
    assert [row["message"] for row in recorded] == ["owned caller", "outer caller"]
    assert backend.warnings is warnings


def test_loopback_warning_capture_fails_closed_on_concurrent_owner_and_changed_proxy():
    original = SimpleNamespace(warn=lambda *args, **kwargs: None)
    backend = SimpleNamespace(warnings=original)
    with live.soundcard_warning_capture(backend, []):
        with pytest.raises(RuntimeError, match="another loopback"):
            with live.soundcard_warning_capture(backend, []):
                pytest.fail("concurrent capture acquired ownership")
    replacement = SimpleNamespace(warn=lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="proxy replaced"):
        with live.soundcard_warning_capture(backend, []):
            backend.warnings = replacement
    assert backend.warnings is replacement  # Cleanup must not overwrite foreign state.
    with live.soundcard_warning_capture(backend, []):
        pass  # The ownership lock was released despite failed restoration.
    assert backend.warnings is replacement


@pytest.mark.parametrize("defect", ["warning", "legacy_no_warning_capture"])
def test_loopback_cannot_be_clean_when_warnings_exist_or_were_not_observed(tmp_path, defect):
    capture, _ = build_bundle(tmp_path)
    if defect == "warning":
        capture["loopback"]["warnings"] = [dict(message="data discontinuity in recording")]
    else:
        del capture["loopback"]["warning_capture_complete"]
    (tmp_path / "capture.json").write_text(json.dumps(capture))
    report = live.analyze_bundle(tmp_path, tmp_path / "result.json")
    assert not report["gates"]["loopback_no_discontinuities"]
    assert report["engineering_acceptance"] == "NO_GO"
