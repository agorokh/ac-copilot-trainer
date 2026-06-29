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

    python -m tools.ai_sidecar.voice.bake --out <dir> --backend tone|piper|say [--samplerate 48000]
"""

from __future__ import annotations

import argparse
import logging
import math
import shutil
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


class BatchVoiceBackend(VoiceBackend, Protocol):
    """Backend that can render a whole phrase bank in one process."""

    def synthesize_many(self, items: list[tuple[str, Path]], samplerate: int) -> None: ...


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


def _normalize_wav(path: Path, samplerate: int) -> None:
    """Normalize backend output to mono 16-bit PCM at ``samplerate``.

    Some external synthesizers (notably Piper voices) write at the model's native sample rate even
    when the target bank should match a 48 kHz Windows endpoint. Resample offline during baking so
    the hot path can keep a single pre-opened audio stream.
    """
    with wave.open(str(path), "rb") as wf:
        source_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if source_rate == samplerate and channels == 1 and sample_width == 2:
        return

    try:
        import numpy as np
    except ImportError as exc:
        # numpy is an optional `voice` extra, not a base dep. With the 48 kHz bank default a Piper
        # voice (commonly 22050 Hz) lands here, so surface an actionable message instead of a raw
        # ModuleNotFoundError deep in the bake.
        raise RuntimeError(
            f"numpy is required to resample {path.name} ({source_rate} Hz -> {samplerate} Hz); "
            "install it with `pip install -e '.[voice]'` (or `pip install numpy`), or bake with "
            f"`--samplerate {source_rate}` to skip resampling."
        ) from exc

    if sample_width == 2:
        audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    else:
        raise ValueError(f"unsupported sample width {sample_width} bytes in {path}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if source_rate != samplerate:
        old_x = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        new_len = max(1, round(len(audio) * samplerate / source_rate))
        new_x = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        audio = np.interp(new_x, old_x, audio).astype(np.float32)
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(pcm16.tobytes())


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
        # piper reads text on stdin and writes a WAV at the model's native samplerate, then we
        # rewrite it to the bank samplerate so WASAPI devices that reject 22050 Hz can still
        # play it.
        subprocess.run(  # noqa: S603 - fixed binary + our own text, no shell
            [self._bin, "--model", str(self._model), "--output_file", str(out_path)],
            input=text.encode("utf-8"),
            check=True,
        )
        _normalize_wav(out_path, samplerate)

    def synthesize_many(self, items: list[tuple[str, Path]], samplerate: int) -> None:
        """Render a phrase bank in one Piper process, with a per-clip fallback.

        Spawning Piper once per clip is prohibitively slow on Windows, so we try a single
        batch process (piper1-gpl ``--input-file`` + ``--output-dir``). That batch path is
        best-effort: if the installed Piper is the MIT ``rhasspy/piper`` build (which lacks
        those flags), or the generated count/ordering cannot be trusted, or anything else
        fails, we fall back to the per-clip :meth:`synthesize` path that every Piper build
        supports. Slower but always correct -- never a silent mis-bake.
        """
        if not items:
            return
        try:
            self._synthesize_many_batch(items, samplerate)
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as exc:
            _log.warning(
                "voice: piper batch bake failed (%s); falling back to per-clip synthesis", exc
            )
            for text, target in items:
                target.parent.mkdir(parents=True, exist_ok=True)
                self.synthesize(text, target, samplerate)

    def _synthesize_many_batch(self, items: list[tuple[str, Path]], samplerate: int) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "phrases.txt"
            output_dir = tmp_path / "clips"
            output_dir.mkdir(parents=True, exist_ok=True)
            input_path.write_text(
                "".join(f"{text}\n" for text, _target in items),
                encoding="utf-8",
            )
            subprocess.run(  # noqa: S603 - fixed binary + our own text, no shell
                [
                    self._bin,
                    "--model",
                    str(self._model),
                    "--input-file",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--output-dir-naming",
                    "timestamp",
                ],
                check=True,
                input=b"",  # close stdin: a flag-incompatible Piper errors out instead of hanging
                timeout=600,
            )
            # piper1-gpl names each clip ``{time.monotonic_ns()}.wav`` in generation order, so a
            # NUMERIC sort maps the generated clips back to input order. A LEXICAL sort would
            # silently mis-order at a digit-count rollover (…9.wav vs …10.wav) and the count guard
            # below — which checks cardinality, not correspondence — would not catch it. Any odd /
            # non-numeric naming raises ValueError here and the caller falls back to per-clip.
            generated = sorted(output_dir.glob("*.wav"), key=lambda p: int(p.stem))
            if len(generated) != len(items):
                raise RuntimeError(
                    f"piper generated {len(generated)} clips for {len(items)} input phrases"
                )
            for source, (_text, target) in zip(generated, items, strict=True):
                target.parent.mkdir(parents=True, exist_ok=True)
                # shutil.move (not Path.replace): the temp dir and the bank output dir can be on
                # different drives on a Windows rig (%TEMP% on C:, bank on D:), where os.replace
                # raises a cross-device OSError.
                shutil.move(str(source), str(target))
                _normalize_wav(target, samplerate)


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
                    # afconvert carries the sample rate in the data-format spec (@<rate>); there is
                    # no separate --rate flag. LEI16 = little-endian 16-bit PCM; -c 1 = mono.
                    "-d",
                    f"LEI16@{samplerate}",
                    "-f",
                    "WAVE",
                    "-c",
                    "1",
                ],
                check=True,
            )


# --------------------------------------------------------------------------------------------------
# Bake driver
# --------------------------------------------------------------------------------------------------


def bake_bank(out_dir: str | Path, backend: VoiceBackend, *, samplerate: int = 48000) -> Manifest:
    """Render every vocabulary phrase to ``out_dir/<clip_id>.wav`` and write ``manifest.json``.

    The manifest stamps the current :func:`vocabulary_hash` and the backend's
    ``voice_signature``, so a later wording change (or a different voice) is detected at load.
    Returns the in-memory manifest.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    phrases = list(iter_vocabulary())
    targets = [(phrase, out / f"{phrase.clip_id}.wav") for phrase in phrases]
    batch = getattr(backend, "synthesize_many", None)
    if callable(batch):
        batch([(phrase.text, target) for phrase, target in targets], samplerate)
    else:
        for phrase, target in targets:
            backend.synthesize(phrase.text, target, samplerate)

    clips: dict[str, ClipEntry] = {}
    for phrase, fp in targets:
        fname = fp.name
        _normalize_wav(fp, samplerate)
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
    manifest = Manifest(
        version=MANIFEST_VERSION,
        samplerate=samplerate,
        voice_signature=backend.voice_signature,
        vocabulary_hash=vocabulary_hash(),
        clips=clips,
    )
    (out / MANIFEST_FILENAME).write_text(manifest.to_json(), encoding="utf-8")
    _log.info("voice: baked %d clips with %s into %s", len(clips), backend.voice_signature, out)
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
    parser.add_argument("--samplerate", type=int, default=48000)
    parser.add_argument("--piper-model", help="path to a Piper .onnx voice model (backend=piper)")
    parser.add_argument("--say-voice", default="Daniel", help="macOS voice name (backend=say)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        manifest = bake_bank(args.out, _build_backend(args), samplerate=args.samplerate)
    except RuntimeError as exc:
        # e.g. numpy missing on the resample path -> clean CLI error, not a deep traceback
        raise SystemExit(str(exc)) from exc
    print(f"baked {len(manifest.clips)} clips -> {Path(args.out) / MANIFEST_FILENAME}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
