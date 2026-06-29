"""Tests for the voice-path benchmark tool (tools.ai_sidecar.voice.bench_voices, issue #368 AC d).

The stdlib ToneBackend path is exercised on any OS; speech-backend rows degrade to ``unavailable``
when ``say``/``ffmpeg`` or model files are absent (so the table is always complete + CI-safe).
"""

from __future__ import annotations

from tools.ai_sidecar.voice.bench_voices import (
    BackendResult,
    run_bench,
    to_markdown,
)


def _results() -> list[BackendResult]:
    return run_bench(piper_model=None, kokoro_model=None, kokoro_voices=None, kokoro_voice="x")


def test_bench_runs_and_covers_every_backend_row() -> None:
    results = _results()
    names = {r.backend for r in results}
    # the rejected baselines + the recommended neural voice are all represented
    assert any("tone" in n for n in names)
    assert "kokoro-82M" in names
    assert "pyttsx3/SAPI" in names


def test_tone_backend_row_is_available_with_measured_act_clips() -> None:
    tone = next(r for r in _results() if "tone" in r.backend)
    assert tone.available
    # firm + critical act clips are measured (the time-critical cues)
    assert set(tone.act_clip_ms) == {"firm", "critical"}
    assert all(ms > 0 for ms in tone.act_clip_ms.values())


def test_unavailable_backends_carry_static_facts() -> None:
    kokoro = next(r for r in _results() if r.backend == "kokoro-82M")
    assert not kokoro.available
    assert "Apache-2.0" in kokoro.license  # static fact carried even when the engine is absent
    assert kokoro.note  # explains why it is unavailable here


def test_markdown_table_renders_with_recommendation() -> None:
    md = to_markdown(_results())
    assert "| backend |" in md and "verdict |" in md
    assert "kokoro-82M" in md
    assert "Recommendation" in md
