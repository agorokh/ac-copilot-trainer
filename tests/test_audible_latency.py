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
