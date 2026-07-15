"""Audible-latency harness math tests (issue #381 verification / #511 Part D).

All synthetic: a fabricated room recording (noise + known chirp + known clip waveform at
known offsets) must yield a clock map and per-cue onsets within tight tolerance, and the
matched filter must REFUSE to invent onsets that are not there. No audio hardware, no
scrcpy — the capture orchestration is exercised live on the rig, not in CI.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from tools.ai_sidecar.voice import audible_latency as al  # noqa: E402
from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank  # noqa: E402
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest  # noqa: E402
from tools.ai_sidecar.voice.playback import Bank  # noqa: E402

SR = 48_000
RNG = np.random.default_rng(20260711)


def _write_wav(path: Path, signal: np.ndarray, sr: int = SR) -> None:
    pcm = (np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _place(recording: np.ndarray, signal: np.ndarray, at: int, gain: float = 0.6) -> None:
    recording[at : at + len(signal)] += gain * signal[: len(recording) - at]


def test_chirp_is_locatable_in_noise() -> None:
    chirp = al.make_chirp(SR, np)
    recording = 0.05 * RNG.standard_normal(SR * 6)
    _place(recording, chirp, 2 * SR)
    onset, score, prom = al.find_onset(recording, chirp, np)
    assert onset is not None
    assert abs(onset - 2 * SR) <= 48  # within 1 ms
    assert score > 0.5
    assert prom > al.MATCH_MIN_PROMINENCE


def test_chirp_negotiates_fixed_layout_for_default_output() -> None:
    attempted: list[int] = []

    def check_output_settings(*, device, channels, samplerate):  # noqa: ANN001
        assert device == 0
        assert samplerate == SR
        attempted.append(channels)
        if channels != 6:
            raise RuntimeError("Invalid number of channels [PaErrorCode -9998]")

    sd = SimpleNamespace(
        default=SimpleNamespace(device=(1, 0)),
        query_devices=lambda: [
            {"name": "5.1 Speakers (USB Sound Device)", "max_output_channels": 6, "hostapi": 0}
        ],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_output_settings=check_output_settings,
    )

    assert al._resolve_chirp_output(
        sd,
        device=None,
        host_api=None,
        samplerate=SR,
    ) == (0, 6, (2,))
    assert attempted == [1, 2, 3, 4, 5, 6]


def test_chirp_uses_both_front_channels_for_compact_fixed_output() -> None:
    attempted: list[int] = []

    def check_output_settings(*, device, channels, samplerate):  # noqa: ANN001
        assert device == 0
        assert samplerate == SR
        attempted.append(channels)
        if channels != 4:
            raise RuntimeError("Invalid number of channels [PaErrorCode -9998]")

    sd = SimpleNamespace(
        default=SimpleNamespace(device=(1, 0)),
        query_devices=lambda: [{"name": "Fixed quad", "max_output_channels": 4, "hostapi": 0}],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_output_settings=check_output_settings,
    )

    assert al._resolve_chirp_output(
        sd,
        device=None,
        host_api=None,
        samplerate=SR,
    ) == (0, 4, (0, 1))
    assert attempted == [1, 2, 3, 4]


def test_play_chirp_writes_every_selected_output_channel(monkeypatch) -> None:
    import sys

    written: dict[str, np.ndarray] = {}

    class CallbackStop(Exception):
        pass

    class FakeOutputStream:
        time = 10.0
        latency = 0.01

        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.callback = kwargs["callback"]
            assert kwargs["channels"] == 4

        def __enter__(self):
            # Exceed the 0.3 s chirp at 48 kHz so the callback reaches its final partial chunk,
            # signals completion, and never falls through to play_chirp's timeout wait.
            outdata = np.zeros((20_000, 4), dtype=np.float32)
            try:
                self.callback(
                    outdata,
                    len(outdata),
                    SimpleNamespace(outputBufferDacTime=10.01),
                    None,
                )
            except CallbackStop:
                pass
            written["outdata"] = outdata
            return self

        def __exit__(self, *args) -> None:  # noqa: ANN002
            return None

    fake_sd = SimpleNamespace(CallbackStop=CallbackStop, OutputStream=FakeOutputStream)
    monkeypatch.setattr(al, "_resolve_chirp_output", lambda *args, **kwargs: (0, 4, (0, 1)))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    al.play_chirp("compact", device=None, host_api=None)

    outdata = written["outdata"]
    assert np.any(outdata[:, 0])
    np.testing.assert_array_equal(outdata[:, 0], outdata[:, 1])
    assert not np.any(outdata[:, 2:])


def test_find_onset_refuses_absent_template() -> None:
    chirp = al.make_chirp(SR, np)
    noise = 0.05 * RNG.standard_normal(SR * 4)
    onset, _score, _prom = al.find_onset(noise, chirp, np)
    assert onset is None


def test_clock_map_two_anchor_drift_fit() -> None:
    chirp = al.make_chirp(SR, np)
    recording = 0.03 * RNG.standard_normal(SR * 14)
    _place(recording, chirp, SR)
    _place(recording, chirp, 12 * SR)
    w0 = 1_000_000.0
    marks = [
        al.ChirpMark("start", w0, w0, 10.0),
        al.ChirpMark("end", w0 + 11_000.0, w0 + 11_000.0, 10.0),
    ]
    clock_map, detail = al.build_clock_map(recording, SR, marks, np)
    assert {d["label"] for d in detail} == {"start", "end"}
    # 11 s of wall clock over exactly 11 s of samples -> nominal slope.
    assert clock_map.wall_ms(SR) == pytest.approx(w0, abs=2.0)
    assert clock_map.wall_ms(12 * SR) == pytest.approx(w0 + 11_000.0, abs=2.0)


def test_clock_map_requires_a_chirp() -> None:
    with pytest.raises(ValueError):
        al.build_clock_map(0.01 * RNG.standard_normal(SR), SR, [al.ChirpMark("start", 0, 0, 0)], np)


def test_end_to_end_analysis_on_synthetic_room(tmp_path: Path) -> None:
    bake_bank(tmp_path, ToneBackend())
    manifest = Manifest.load(tmp_path / MANIFEST_FILENAME)
    bank = Bank.from_manifest(manifest, tmp_path)
    clip_id = "late_brake.act.critical.generic"
    clip = np.asarray(bank.get(clip_id), dtype=np.float64)
    assert bank.samplerate == SR, "test assumes the baked bank is 48 kHz"

    chirp = al.make_chirp(SR, np)
    recording = 0.04 * RNG.standard_normal(SR * 10)
    w0 = 5_000_000.0
    chirp_at = SR  # 1 s in -> wall w0
    _place(recording, chirp, chirp_at)
    # True acoustic onset 3.0 s after the chirp -> wall w0 + 3000 ms.
    clip_at = chirp_at + 3 * SR
    _place(recording, clip, clip_at)
    rec_path = tmp_path / "room.wav"
    _write_wav(rec_path, recording)

    # Dispatch stamped 180 ms before the acoustic onset -> expected latency ~180 ms.
    dispatches = [
        {
            "seq": 1,
            "clip_id": clip_id,
            "kind": "late_brake",
            "urgency": "act",
            "register": "critical",
            "t_wall_ms": w0 + 3_000.0 - 180.0,
        }
    ]
    echoes = [
        {
            "seq": 1,
            "clip_id": clip_id,
            "t_dispatch_ms": w0 + 2_820.0,
            "t_receive_ms": 42.0,
            "t_play_ms": 54.0,
            "t_server_ms": w0 + 2_828.0,
        }
    ]
    report = al.analyze(
        recording_path=rec_path,
        bank_dir=tmp_path,
        dispatches=dispatches,
        chirps=[al.ChirpMark("start", w0, w0, 12.0)],
        echoes=echoes,
    )
    assert report.assertions["clock_map_anchored"]
    cue = report.cues[0]
    assert cue.matched, f"cue unmatched (score={cue.match_score}, prom={cue.match_prominence})"
    assert cue.audible_latency_ms == pytest.approx(180.0, abs=15.0)
    assert cue.rtt_ms == pytest.approx(8.0, abs=0.1)
    assert cue.js_play_ms == pytest.approx(12.0, abs=0.1)
    assert report.assertions["all_dispatched_cues_matched"]
    assert report.assertions["act_cues_within_budget"]
    assert report.stats["act_latency_ms"]["n"] == 1

    md = al.render_markdown(report)
    assert clip_id in md
    assert "Systematic uncertainty" in md


def test_unmatched_cue_fails_assertions_not_silently(tmp_path: Path) -> None:
    bake_bank(tmp_path, ToneBackend())
    chirp = al.make_chirp(SR, np)
    recording = 0.04 * RNG.standard_normal(SR * 6)
    w0 = 1_000.0
    _place(recording, chirp, SR)
    rec_path = tmp_path / "room.wav"
    _write_wav(rec_path, recording)
    dispatches = [
        {
            "seq": 1,
            "clip_id": "late_brake.act.critical.generic",
            "kind": "late_brake",
            "urgency": "act",
            "register": "critical",
            "t_wall_ms": w0 + 2_000.0,  # dispatched, but the clip never sounded
        }
    ]
    report = al.analyze(
        recording_path=rec_path,
        bank_dir=tmp_path,
        dispatches=dispatches,
        chirps=[al.ChirpMark("start", w0, w0, 12.0)],
    )
    assert not report.cues[0].matched
    assert not report.assertions["all_dispatched_cues_matched"]
    assert not report.assertions["act_cues_within_budget"]


def test_same_clip_repeats_do_not_cross_assign_onsets(tmp_path: Path) -> None:
    """Two dispatches of the SAME clip inside one search window must each match their own
    acoustic instance (onset consumption), never both lock onto the later/louder one
    (PR #519 adversarial review)."""
    bake_bank(tmp_path, ToneBackend())
    manifest = Manifest.load(tmp_path / MANIFEST_FILENAME)
    bank = Bank.from_manifest(manifest, tmp_path)
    clip_id = "late_brake.act.critical.generic"
    clip = np.asarray(bank.get(clip_id), dtype=np.float64)

    chirp = al.make_chirp(SR, np)
    recording = 0.04 * RNG.standard_normal(SR * 10)
    w0 = 100_000.0
    _place(recording, chirp, SR)
    # Two acoustic instances of the SAME clip, 1.5 s apart; the second slightly louder.
    a_at = SR + 2 * SR
    b_at = a_at + int(1.5 * SR)
    _place(recording, clip, a_at, gain=0.5)
    _place(recording, clip, b_at, gain=0.7)
    rec_path = tmp_path / "room.wav"
    _write_wav(rec_path, recording)

    dispatches = [
        {
            "seq": 1,
            "clip_id": clip_id,
            "kind": "late_brake",
            "urgency": "act",
            "register": "critical",
            "t_wall_ms": w0 + 2_000.0 - 150.0,
        },
        {
            "seq": 2,
            "clip_id": clip_id,
            "kind": "late_brake",
            "urgency": "act",
            "register": "critical",
            "t_wall_ms": w0 + 3_500.0 - 150.0,
        },
    ]
    report = al.analyze(
        recording_path=rec_path,
        bank_dir=tmp_path,
        dispatches=dispatches,
        chirps=[al.ChirpMark("start", w0, w0, 10.0)],
    )
    lats = [c.audible_latency_ms for c in report.cues]
    assert all(c.matched for c in report.cues), lats
    # Each cue matched its OWN instance: ~150 ms each, not ~1650 ms for the first.
    assert lats[0] == pytest.approx(150.0, abs=20.0)
    assert lats[1] == pytest.approx(150.0, abs=20.0)


def test_missed_end_chirp_fails_drift_assertion(tmp_path: Path) -> None:
    """When two chirps were played but only one is locatable, the run must FAIL loudly
    (clock_map_drift_corrected=False), never silently fall back (PR #519 review)."""
    bake_bank(tmp_path, ToneBackend())
    chirp = al.make_chirp(SR, np)
    recording = 0.04 * RNG.standard_normal(SR * 8)
    w0 = 50_000.0
    _place(recording, chirp, SR)  # start chirp only — the end chirp never made it
    rec_path = tmp_path / "room.wav"
    _write_wav(rec_path, recording)
    report = al.analyze(
        recording_path=rec_path,
        bank_dir=tmp_path,
        dispatches=[],
        chirps=[
            al.ChirpMark("start", w0, w0, 10.0),
            al.ChirpMark("end", w0 + 6_000.0, w0 + 6_000.0, 10.0),
        ],
    )
    assert report.clock_map["anchors_used"] == 1
    assert report.assertions["clock_map_drift_corrected"] is False


def test_burst_count_assertion_fails_on_suppressed_cues(tmp_path: Path) -> None:
    """Burst mode must assert every injected cue was dispatched — scheduler suppression
    silently shrinking the sample is a FAIL, not a smaller PASS (PR #519 review)."""
    bake_bank(tmp_path, ToneBackend())
    manifest = Manifest.load(tmp_path / MANIFEST_FILENAME)
    bank = Bank.from_manifest(manifest, tmp_path)
    clip_id = "late_brake.act.critical.generic"
    clip = np.asarray(bank.get(clip_id), dtype=np.float64)
    chirp = al.make_chirp(SR, np)
    recording = 0.04 * RNG.standard_normal(SR * 8)
    w0 = 70_000.0
    _place(recording, chirp, SR)
    _place(recording, clip, 3 * SR)
    rec_path = tmp_path / "room.wav"
    _write_wav(rec_path, recording)
    dispatches = [
        {
            "seq": 1,
            "clip_id": clip_id,
            "kind": "late_brake",
            "urgency": "act",
            "register": "critical",
            "t_wall_ms": w0 + 2_000.0 - 150.0,
        },
    ]
    report = al.analyze(
        recording_path=rec_path,
        bank_dir=tmp_path,
        dispatches=dispatches,
        chirps=[al.ChirpMark("start", w0, w0, 10.0)],
        expected_dispatches=3,  # 3 injected, only 1 dispatched
    )
    assert report.assertions["all_burst_cues_dispatched"] is False


def test_http_get_json_rejects_lookalike_loopback_hosts() -> None:
    for bad in [
        "http://127.0.0.1.evil.example/voice/dispatches",
        "http://localhost.evil.example/voice/dispatches",
        "https://127.0.0.1:8765/voice/dispatches",  # https ≠ the loopback sidecar
        "http://192.168.1.10:8765/voice/dispatches",
    ]:
        with pytest.raises(ValueError):
            al._http_get_json(bad)


def test_filter_dispatches_to_window() -> None:
    """Only cues dispatched inside THIS run's chirp-bounded window are analyzed — the ring
    buffer spans the whole sidecar process (PR #519 review)."""
    chirps = [
        al.ChirpMark("start", 10_000.0, 10_000.0, 5.0),
        al.ChirpMark("end", 40_000.0, 40_000.0, 5.0),
    ]
    dispatches = [
        {"seq": 1, "t_wall_ms": 5_000.0},  # earlier sidecar activity — dropped
        {"seq": 2, "t_wall_ms": 10_100.0},  # in window — kept
        {"seq": 3, "t_wall_ms": 39_900.0},  # in window — kept
        {"seq": 4, "t_wall_ms": 55_000.0},  # after the capture — dropped
        {"seq": 5},  # no stamp — dropped
    ]
    kept = al.filter_dispatches_to_window(dispatches, chirps)
    assert [d["seq"] for d in kept] == [2, 3]
    # No chirps (analysis-only edge) -> passthrough rather than dropping everything.
    assert al.filter_dispatches_to_window(dispatches, []) == dispatches


def test_analyze_cmd_round_trip(tmp_path: Path) -> None:
    """The CLI analyze path parses the run artifacts it writes (shape contract)."""
    bake_bank(tmp_path, ToneBackend())
    manifest = Manifest.load(tmp_path / MANIFEST_FILENAME)
    bank = Bank.from_manifest(manifest, tmp_path)
    clip_id = "late_brake.act.critical.generic"
    clip = np.asarray(bank.get(clip_id), dtype=np.float64)
    chirp = al.make_chirp(SR, np)
    recording = 0.04 * RNG.standard_normal(SR * 8)
    w0 = 9_000.0
    _place(recording, chirp, SR)
    _place(recording, clip, SR + 2 * SR)
    rec = tmp_path / "room.wav"
    _write_wav(rec, recording)
    (tmp_path / "dispatches.json").write_text(
        json.dumps(
            {
                "dispatches": [
                    {
                        "seq": 1,
                        "clip_id": clip_id,
                        "kind": "late_brake",
                        "urgency": "act",
                        "register": "critical",
                        "t_wall_ms": w0 + 2_000.0 - 150.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "chirps.json").write_text(
        json.dumps(
            [
                {
                    "label": "start",
                    "t_wall_ms": w0,
                    "t_dac_wall_ms": w0,
                    "output_latency_ms": 10.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    rc = al.main(
        [
            "analyze",
            "--bank",
            str(tmp_path),
            "--out-dir",
            str(out_dir),
            "--recording",
            str(rec),
            "--dispatches",
            str(tmp_path / "dispatches.json"),
            "--chirps",
            str(tmp_path / "chirps.json"),
        ]
    )
    assert rc == 0
    report = json.loads((out_dir / "audible_latency.json").read_text(encoding="utf-8"))
    assert report["cues"][0]["matched"] is True
    assert (out_dir / "audible_latency.md").exists()
