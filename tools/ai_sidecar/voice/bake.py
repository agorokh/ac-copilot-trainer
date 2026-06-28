"""Offline phrase-bank baker — render the bounded vocabulary once to WAV + a content-addressed
manifest.

Baking is **not** time-critical (it runs offline, not at the wheel), so it can use a naturalistic
neural voice. The runtime then plays the pre-rendered clips with deterministic, jitter-free latency.

Backends (pluggable via the :class:`VoiceBackend` protocol — wording always comes from
:mod:`tools.ai_sidecar.voice.vocabulary`, never from the backend):

* :class:`PiperBackend` — **production** neural voice (Piper, MIT). Shells to the ``piper`` CLI; the
  bank is baked on the rig and committed/deployed there.
* :class:`MacSayBackend` — local dev verification on macOS (``say`` + ``afconvert``): real
  speech, for listening to what the engine would say, without a Piper model download.
* :class:`ToneBackend` — **stdlib-only**, deterministic per-text tones. No third-party
  dependency, so CI and the off-rig pipeline check can bake a real (audible) bank and exercise
  manifest content-addressing + the full resolve->schedule->play path without a TTS engine.

CLI::

    python -m tools.ai_sidecar.voice.bake --out <dir> --backend tone|piper|say [--samplerate 22050]
"""

from __future__ import annotations

import argparse
import logging
import math
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Protocol

from tools.ai_sidecar.voice.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ClipEntry,
    Manifest,
    sha256_bytes,
)
from tools.ai_sidecar.voice.vocabulary import iter_vocabulary, vocabulary_hash

_log = logging.getLogger("ai_sidecar.voice.bake")


class VoiceBackend(Protocol):
    """Renders one text string to a WAV file at a samplerate. ``voice_signature`` IDs the voice."""

    @property
    def voice_signature(self) -> str: ...

    def synthesize(self, text: str, out_path: Path, samplerate: int) -> None: ...


# --------------------------------------------------------------------------------------------------
# Stdlib-only deterministic backend (CI + pipeline verification)
# --------------------------------------------------------------------------------------------------


class ToneBackend:
    """Deterministic, dependency-free tones — distinct per text, audible, reproducible.

    Not speech; a smoke/verification voice that proves the bake + manifest + playback plumbing with
    zero third-party deps. Frequency and duration derive from a stable hash of the text, so the bank
    is byte-reproducible across runs (content-addressing is meaningful).
    """

    voice_signature = "tone-v1"

    def synthesize(self, text: str, out_path: Path, samplerate: int) -> None:
        # Stable, platform-independent hash of the text (avoid Python's salted hash()).
        digest = sha256_bytes(text.encode("utf-8"))
        seed = int(digest[:8], 16)
        freq = 220.0 + (seed % 660)  # 220–880 Hz, a comfortable musical band
        words = max(1, len(text.split()))
        duration_s = min(1.2, 0.18 * words)  # ~0.18 s/word, capped — terse like a real cue
        n = int(samplerate * duration_s)
        amp = 0.4
        # 5 ms raised-cosine fade in/out so the tone has no click (mirrors the real join crossfade).
        fade = max(1, int(samplerate * 0.005))
        frames = bytearray()
        for i in range(n):
            env = 1.0
            if i < fade:
                env = 0.5 * (1 - math.cos(math.pi * i / fade))
            elif i > n - fade:
                env = 0.5 * (1 - math.cos(math.pi * (n - i) / fade))
            sample = amp * env * math.sin(2 * math.pi * freq * i / samplerate)
            frames += struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767))
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(bytes(frames))


# --------------------------------------------------------------------------------------------------
# Production / dev speech backends (external tools; not exercised on CI)
# --------------------------------------------------------------------------------------------------


class PiperBackend:
    """Production neural voice via the Piper CLI (MIT). Bake once on the rig, deploy the WAVs."""

    def __init__(self, model_path: str | Path, piper_bin: str = "piper") -> None:
        self._model = Path(model_path)
        self._bin = piper_bin
        if not self._model.is_file():
            raise FileNotFoundError(f"piper model not found: {self._model}")

    @property
    def voice_signature(self) -> str:
        return f"piper:{self._model.stem}"

    def synthesize(self, text: str, out_path: Path, samplerate: int) -> None:
        # piper reads text on stdin and writes a WAV at the model's native samplerate; we ask the
        # caller to bake at that samplerate (Piper voices are commonly 22050 Hz).
        subprocess.run(  # noqa: S603 - fixed binary + our own text, no shell
            [self._bin, "--model", str(self._model), "--output_file", str(out_path)],
            input=text.encode("utf-8"),
            check=True,
        )


class MacSayBackend:
    """macOS dev voice: ``say`` -> AIFF -> ``afconvert`` -> mono 16-bit WAV at samplerate."""

    def __init__(self, voice: str = "Daniel") -> None:
        self._voice = voice

    @property
    def voice_signature(self) -> str:
        return f"macsay:{self._voice}"

    def synthesize(self, text: str, out_path: Path, samplerate: int) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "clip.aiff"
            subprocess.run(  # noqa: S603 - fixed binary, our own text
                ["say", "-v", self._voice, "-o", str(aiff), text],
                check=True,
            )
            subprocess.run(  # noqa: S603 - convert to mono 16-bit PCM WAV at target samplerate
                [
                    "afconvert",
                    str(aiff),
                    str(out_path),
                    "-d",
                    "LEI16",
                    "-f",
                    "WAVE",
                    "-c",
                    "1",
                    "--rate",
                    str(samplerate),
                ],
                check=True,
            )


# --------------------------------------------------------------------------------------------------
# Bake driver
# --------------------------------------------------------------------------------------------------


def bake_bank(out_dir: str | Path, backend: VoiceBackend, *, samplerate: int = 22050) -> Manifest:
    """Render every vocabulary phrase to ``out_dir/<clip_id>.wav`` and write ``manifest.json``.

    The manifest stamps the current :func:`vocabulary_hash` and the backend's
    ``voice_signature``, so a later wording change (or a different voice) is detected at load.
    Returns the in-memory manifest.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    clips: dict[str, ClipEntry] = {}
    count = 0
    for phrase in iter_vocabulary():
        fname = f"{phrase.clip_id}.wav"
        fp = out / fname
        backend.synthesize(phrase.text, fp, samplerate)
        data = fp.read_bytes()
        clips[phrase.clip_id] = ClipEntry(
            clip_id=phrase.clip_id,
            file=fname,
            kind=phrase.kind,
            urgency=phrase.urgency,
            corner=phrase.corner,
            text=phrase.text,
            sha256=sha256_bytes(data),
        )
        count += 1
    manifest = Manifest(
        version=MANIFEST_VERSION,
        samplerate=samplerate,
        voice_signature=backend.voice_signature,
        vocabulary_hash=vocabulary_hash(),
        clips=clips,
    )
    (out / MANIFEST_FILENAME).write_text(manifest.to_json(), encoding="utf-8")
    _log.info("voice: baked %d clips with %s into %s", count, backend.voice_signature, out)
    return manifest


def _build_backend(args: argparse.Namespace) -> VoiceBackend:
    if args.backend == "tone":
        return ToneBackend()
    if args.backend == "piper":
        if not args.piper_model:
            raise SystemExit("--piper-model is required for --backend piper")
        return PiperBackend(args.piper_model)
    if args.backend == "say":
        return MacSayBackend(voice=args.say_voice)
    raise SystemExit(f"unknown backend {args.backend!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bake the voice-coach phrase bank.")
    parser.add_argument("--out", required=True, help="output bank directory")
    parser.add_argument(
        "--backend", default="tone", choices=("tone", "piper", "say"), help="synthesis backend"
    )
    parser.add_argument("--samplerate", type=int, default=22050)
    parser.add_argument("--piper-model", help="path to a Piper .onnx voice model (backend=piper)")
    parser.add_argument("--say-voice", default="Daniel", help="macOS voice name (backend=say)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    manifest = bake_bank(args.out, _build_backend(args), samplerate=args.samplerate)
    print(f"baked {len(manifest.clips)} clips → {Path(args.out) / MANIFEST_FILENAME}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
