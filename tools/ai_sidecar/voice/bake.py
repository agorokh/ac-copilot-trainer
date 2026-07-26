"""Offline phrase-bank baker — render the bounded vocabulary once to WAV + a content-addressed
manifest, with a per-register **prosody** layer so the SAME command is rendered with a tone that
reflects the situation (issue #381).

Baking is **not** time-critical (it runs offline, not at the wheel), so it can use a naturalistic
neural voice and shell to ``ffmpeg`` for prosody shaping. The runtime then plays the pre-rendered
clips with deterministic, jitter-free latency — no live TTS in the hot path (invariant #1).

**Register -> tone.** Every clip carries a ``register`` (calm | alert | urgent | critical). A
speech backend renders the words once; a :class:`ProsodyShaper` then applies a per-register
``ffmpeg`` filter chain
(rate / pitch / loudness / compression / brightness) so the tone escalates with the register. The
shaping is baked into the WAV bytes — tone is delivered with zero hot-path cost. ``ffmpeg`` is run
with ``-bitexact`` + stripped metadata so a given ffmpeg build produces **byte-identical** output
run-to-run (so per-clip ``sha256`` over the file bytes stays the drift detector); cross-build
differences are expected and gated by ``voice_signature`` (which carries the ffmpeg major version +
the prosody-chain version).

Backends (pluggable via the :class:`VoiceBackend` protocol — wording always comes from
:mod:`tools.ai_sidecar.voice.vocabulary`, never from the backend):

* :class:`KokoroBackend` — **recommended production** neural voice (Kokoro-82M via ``kokoro-onnx``,
  Apache-2.0). Clean license, deterministic ONNX, best naturalness in the permissive tier.
* :class:`MacSayExpressiveBackend` — macOS dev voice that **varies tone by register** (``say`` rate
  + the prosody chain), so the operator can bake and **listen to** all three registers on the Mac.
* :class:`PiperBackend` — neural voice via the Piper CLI; kept for the voice-path benchmark
  (#368 AC d).
* :class:`MacSayBackend` — flat macOS ``say`` (no register variation) — the benchmark's plain
  baseline.
* :class:`ToneBackend` — **stdlib-only**, deterministic per-(text, register) tones. No third-party
  dependency and **no ffmpeg**, so CI bakes a real (audible) bank whose three registers are
  measurably distinct, exercising the full key path without a TTS engine.

CLI::

    python -m tools.ai_sidecar.voice.bake --out <dir> \
        --backend tone|say|say-expressive|piper|kokoro [--samplerate 48000]
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from tools.ai_sidecar.voice.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ClipEntry,
    Manifest,
    sha256_bytes,
)
from tools.ai_sidecar.voice.vocabulary import (
    EXPECTED_SIGNATURE_SUFFIX,
    iter_vocabulary,
    vocabulary_hash,
)

_log = logging.getLogger("ai_sidecar.voice.bake")

# PROSODY_VERSION moved to tools.ai_sidecar.voice.vocabulary and is folded into
# EXPECTED_SIGNATURE_SUFFIX, so the stdlib-only manifest gate enforces prosody staleness too
# (codex review #441).


def _signature_suffix() -> str:
    # Manifest.validate anchors on this exact suffix with ``endswith`` (issue #438) — it must stay
    # the FINAL segment of every backend's voice_signature.
    return EXPECTED_SIGNATURE_SUFFIX


class VoiceBackend(Protocol):
    """Renders one ``(text, register)`` to a WAV file at a samplerate. ``voice_signature`` IDs the
    voice (and, for shaped backends, the prosody-chain + ffmpeg version that produced the tones)."""

    @property
    def voice_signature(self) -> str: ...

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None: ...


class BatchVoiceBackend(VoiceBackend, Protocol):
    """Backend that can render a whole phrase bank in one process."""

    def synthesize_many(self, items: list[tuple[str, str, Path]], samplerate: int) -> None: ...


# --------------------------------------------------------------------------------------------------
# ffmpeg prosody shaper (shared by the speech backends; ToneBackend never touches it)
# --------------------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def ffmpeg_version() -> str:
    """Major ffmpeg version string (e.g. ``ff8``) for ``voice_signature``; ``ff?`` if unknown."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed binary, no shell
            ["ffmpeg", "-version"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return "ff?"
    m = re.search(r"ffmpeg version (\d+)", out)
    return f"ff{m.group(1)}" if m else "ff?"


def _prosody_filter(register: str, samplerate: int, *, apply_tempo: bool) -> str:
    """Return the ``ffmpeg -af`` chain for a register.

    ``apply_tempo`` is ``False`` for backends that already vary speaking rate at synthesis time
    (macOS ``say -r``), so we never stack tempo twice and turn a terse cue unintelligible (issue
    #368 AC c / adversary finding). Neutral-rate neural backends (Kokoro/Piper) pass
    ``apply_tempo=True``. Every chain starts by resampling backend-native WAVs to the requested bank
    rate before any tempo/pitch filter, then ends with a 6 ms fade, a brick-wall limiter, and a
    fixed output format so the bytes are reproducible on a given ffmpeg build.
    """
    sr = samplerate
    # A short fade-IN declicks the onset after the highpass/compressor; we deliberately do NOT add a
    # fade-OUT (ffmpeg's ``afade=t=out`` needs a start time we don't know ahead of render, and with
    # the default ``st=0`` it silences the whole clip after 6 ms — a real bug caught by
    # measurement).
    prefix = f"aresample={sr}"
    tail = f"afade=t=in:d=0.006,alimiter=limit=0.97,aformat=sample_fmts=s16:sample_rates={sr}:channel_layouts=mono"  # noqa: E501
    if register == "calm":
        # measured, warm, slightly softer — a guidance tone.
        body = "highpass=f=90,acompressor=threshold=-20dB:ratio=2.5:attack=10:release=80,treble=g=2:f=3000,volume=-2dB"  # noqa: E501
    elif register == "alert":
        tempo = "atempo=1.06," if apply_tempo else ""
        body = f"{tempo}highpass=f=100,acompressor=threshold=-19dB:ratio=3:attack=7:release=70,treble=g=3:f=3200,volume=1.5dB"  # noqa: E501
    elif register == "urgent":
        tempo = "atempo=1.13," if apply_tempo else ""
        body = f"{tempo}highpass=f=110,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,treble=g=3.5:f=3300,volume=3dB"  # noqa: E501
    elif register == "critical":
        # faster + brighter + harder-compressed + louder — an alarm that cuts through engine noise.
        tempo = f"asetrate={sr}*1.05,aresample={sr},atempo=1.12," if apply_tempo else ""
        body = f"{tempo}highpass=f=130,acompressor=threshold=-22dB:ratio=5:attack=3:release=45,treble=g=5.5:f=3600,volume=6dB"  # noqa: E501
    else:  # pragma: no cover - registers are validated upstream
        body = "anull"
    return f"{prefix},{body},{tail}"


class ProsodyShaper:
    """Applies a per-register ffmpeg filter chain to a raw WAV, deterministically.

    ``-bitexact`` + ``-map_metadata -1`` strip the version-identifying ``ISFT``/encoder tags so the
    output WAV is byte-identical run-to-run on a given ffmpeg build — keeping the per-clip
    ``sha256`` over file bytes a meaningful drift detector. Cross-ffmpeg-build byte differences are
    expected and gated by :func:`ffmpeg_version` in ``voice_signature``.
    """

    def __init__(self, *, apply_tempo: bool) -> None:
        self._apply_tempo = apply_tempo

    @property
    def signature(self) -> str:
        # Host-varying part only (ffmpeg major). The code-owned prosody-chain version rides in
        # EXPECTED_SIGNATURE_SUFFIX so the runtime gate enforces it (codex review #441).
        return ffmpeg_version()

    def shape(self, in_wav: Path, out_wav: Path, register: str, samplerate: int) -> None:
        filt = _prosody_filter(register, samplerate, apply_tempo=self._apply_tempo)
        subprocess.run(  # noqa: S603 - fixed binary + our own filter string, no shell
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-fflags", "+bitexact", "-flags", "+bitexact",
                "-i", str(in_wav),
                "-af", filt,
                "-map_metadata", "-1",
                "-ac", "1", "-c:a", "pcm_s16le",
                "-bitexact",
                str(out_wav),
            ],
            check=True,
        )  # fmt: skip


# --------------------------------------------------------------------------------------------------
# Stdlib-only deterministic backend (CI + pipeline verification) — register-aware, no ffmpeg
# --------------------------------------------------------------------------------------------------


class ToneBackend:
    """Deterministic, dependency-free tones — distinct per (text, register), audible, reproducible.

    Not speech; a smoke/verification voice that proves the bake + manifest + playback plumbing with
    zero third-party deps and **no ffmpeg** (stdlib ``wave`` only), so it runs in CI. Frequency and
    duration derive from a stable hash of the text PLUS a per-register shift, so the four registers
    for one cue are **measurably distinct** (critical is higher-pitched and shorter than calm) and
    the bank is byte-reproducible across runs — CI exercises the register dimension end-to-end.
    """

    voice_signature = f"tone-v3+{_signature_suffix()}"

    #: (frequency offset Hz, duration scale) per register — critical is brighter + shorter.
    _REGISTER_TONE: dict[str, tuple[float, float]] = {
        "calm": (0.0, 1.0),
        "alert": (70.0, 0.92),
        "urgent": (140.0, 0.80),
        "critical": (240.0, 0.70),
    }

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None:
        digest = sha256_bytes(text.encode("utf-8"))
        seed = int(digest[:8], 16)
        freq_off, dur_scale = self._REGISTER_TONE.get(register, (0.0, 1.0))
        freq = 220.0 + (seed % 520) + freq_off  # base band + per-register brightness
        words = max(1, len(text.split()))
        duration_s = min(1.2, 0.18 * words) * dur_scale  # ~0.18 s/word, capped, register-scaled
        n = int(samplerate * duration_s)
        amp = 0.4
        fade = max(1, int(samplerate * 0.005))  # 5 ms raised-cosine fade — no click
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
    """Normalize backend output to mono 16-bit PCM at ``samplerate``."""
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


class KokoroBackend:
    """Recommended production neural voice: Kokoro-82M via ``kokoro-onnx`` (Apache-2.0).

    Renders the words at a register-appropriate base speed, then the :class:`ProsodyShaper` applies
    the per-register tone. Deterministic on the ONNX CPU provider. The model + voices file are
    downloaded once and committed/deployed with the bank on the rig. ``kokoro-onnx`` is imported
    lazily so the bake module stays importable without it.
    """

    #: Per-register synthesis speed. Kokoro quantizes short utterances into different duration
    #: bands, so these bases are tuned against the *shaped output* rather than required to be
    #: monotonic themselves: alert/urgent retain the <=450 ms act-cue budget while critical leaves
    #: enough room for its final consonant (operator A/B finding, issue #381). The shaped
    #: production ladder remains monotonic.
    _REGISTER_SPEED: dict[str, float] = {
        "calm": 0.95,
        "alert": 1.26,
        "urgent": 1.28,
        "critical": 1.25,
    }

    _CRITICAL_BRAKE_MIN_MS = 380.0
    _BRAKE_ACT_MAX_MS = 450.0

    def __init__(
        self,
        model_path: str | Path,
        voices_path: str | Path,
        *,
        voice: str = "am_michael",
    ) -> None:
        self._model = Path(model_path)
        self._voices = Path(voices_path)
        self._voice = voice
        if not self._model.is_file():
            raise FileNotFoundError(f"kokoro model not found: {self._model}")
        if not self._voices.is_file():
            raise FileNotFoundError(f"kokoro voices not found: {self._voices}")
        self._shaper = ProsodyShaper(apply_tempo=True)
        self._kokoro = None  # lazy

    @property
    def voice_signature(self) -> str:
        return f"kokoro:{self._voice}+{self._shaper.signature}+{_signature_suffix()}"

    def _engine(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro  # lazy import — heavy dep

            self._kokoro = Kokoro(str(self._model), str(self._voices))
        return self._kokoro

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None:
        import soundfile as sf  # lazy

        speed = self._REGISTER_SPEED.get(register, 1.0)
        samples, sr = self._engine().create(text, voice=self._voice, speed=speed, lang="en-us")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.wav"
            sf.write(str(raw), samples, sr, subtype="PCM_16")
            self._shaper.shape(raw, out_path, register, samplerate)
        self._validate_brake_act_duration(text, register, out_path)

    def _validate_brake_act_duration(self, text: str, register: str, out_path: Path) -> None:
        """Fail a Kokoro bake whose brake act cue is clipped or too slow to be actionable."""
        normalized = text.strip().casefold()
        if register not in {"alert", "urgent", "critical"} or normalized not in {
            "brake.",
            "brake!",
        }:
            return
        with wave.open(str(out_path), "rb") as wf:
            duration_ms = wf.getnframes() * 1000.0 / wf.getframerate()
        if duration_ms > self._BRAKE_ACT_MAX_MS:
            raise RuntimeError(
                "brake act cue must be at most "
                f"{self._BRAKE_ACT_MAX_MS:.0f} ms after shaping; "
                f"got {duration_ms:.1f} ms"
            )
        if register == "critical" and duration_ms < self._CRITICAL_BRAKE_MIN_MS:
            raise RuntimeError(
                "critical Brake! articulation must be at least "
                f"{self._CRITICAL_BRAKE_MIN_MS:.0f} ms after shaping; "
                f"got {duration_ms:.1f} ms"
            )


class PiperBackend:
    """Neural voice via the Piper CLI (kept for the #368 AC(d) voice-path benchmark).

    Renders at a register-appropriate ``length_scale`` (lower = faster), then shapes per register.
    """

    _REGISTER_LENGTH_SCALE: dict[str, float] = {
        "calm": 1.05,
        "alert": 0.75,
        "urgent": 0.72,
        "critical": 0.69,
    }

    def __init__(self, model_path: str | Path, piper_bin: str = "piper") -> None:
        self._model = Path(model_path)
        self._bin = piper_bin
        if not self._model.is_file():
            raise FileNotFoundError(f"piper model not found: {self._model}")
        self._shaper = ProsodyShaper(apply_tempo=True)

    @property
    def voice_signature(self) -> str:
        return f"piper:{self._model.stem}+{self._shaper.signature}+{_signature_suffix()}"

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None:
        length_scale = self._REGISTER_LENGTH_SCALE.get(register, 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.wav"
            subprocess.run(  # noqa: S603 - fixed binary + our own text, no shell
                [
                    self._bin, "--model", str(self._model),
                    "--length_scale", str(length_scale),
                    "--output_file", str(raw),
                ],
                input=text.encode("utf-8"),
                check=True,
            )  # fmt: skip
            self._shaper.shape(raw, out_path, register, samplerate)

    def synthesize_many(self, items: list[tuple[str, str, Path]], samplerate: int) -> None:
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
            for text, register, target in items:
                target.parent.mkdir(parents=True, exist_ok=True)
                self.synthesize(text, register, target, samplerate)

    def _synthesize_many_batch(self, items: list[tuple[str, str, Path]], samplerate: int) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            groups: dict[str, list[tuple[str, Path]]] = {}
            for text, register, target in items:
                groups.setdefault(register, []).append((text, target))
            for register, group in groups.items():
                self._synthesize_register_batch(tmp_path, register, group, samplerate)

    def _synthesize_register_batch(
        self,
        tmp_path: Path,
        register: str,
        items: list[tuple[str, Path]],
        samplerate: int,
    ) -> None:
        length_scale = self._REGISTER_LENGTH_SCALE.get(register, 1.0)
        with tempfile.TemporaryDirectory(dir=tmp_path) as group_tmp:
            group_path = Path(group_tmp)
            input_path = group_path / "phrases.txt"
            output_dir = group_path / "clips"
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
                    "--length_scale",
                    str(length_scale),
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
            # silently mis-order at a digit-count rollover (...9.wav vs ...10.wav) and the count
            # guard below would not catch it. Odd/non-numeric names raise and fall back per clip.
            generated = sorted(output_dir.glob("*.wav"), key=lambda p: int(p.stem))
            if len(generated) != len(items):
                raise RuntimeError(
                    f"piper generated {len(generated)} clips for {len(items)} input phrases"
                )
            for index, (source, (_text, target)) in enumerate(zip(generated, items, strict=True)):
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = group_path / f"raw_{index}.wav"
                # shutil.move (not Path.replace): the temp dir and bank output dir can be on
                # different drives on a Windows rig (%TEMP% on C:, bank on D:).
                shutil.move(str(source), str(raw))
                self._shaper.shape(raw, target, register, samplerate)


class MacSayExpressiveBackend:
    """macOS dev voice that varies tone by register: a fixed ``say`` rate + the prosody chain.

    Lets the operator bake on the Mac and **listen** to all three registers (issue #368). ``say``
    renders at ONE moderate rate (just the voice timbre); the :class:`ProsodyShaper`
    (``apply_tempo=True``) owns ALL of the register shaping — tempo, pitch, loudness, brightness —
    exactly like the production neural backends. This keeps a single tone path (so what the operator
    hears on the Mac matches how the rig's Kokoro clips are shaped) and avoids the say-rate +
    chain-tempo double-fast unintelligibility the adversary flagged.
    """

    #: one moderate rate — terse but natural; the prosody chain does the per-register tempo.
    _SAY_RATE = 200

    def __init__(self, voice: str = "Daniel") -> None:
        self._voice = voice
        self._shaper = ProsodyShaper(apply_tempo=True)

    @property
    def voice_signature(self) -> str:
        return f"macsay-expr:{self._voice}+{self._shaper.signature}+{_signature_suffix()}"

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "clip.aiff"
            raw = Path(tmp) / "raw.wav"
            subprocess.run(  # noqa: S603 - fixed binary, our own text
                ["say", "-v", self._voice, "-r", str(self._SAY_RATE), "-o", str(aiff), text],
                check=True,
            )
            subprocess.run(  # noqa: S603 - convert to mono 16-bit PCM WAV at target samplerate
                ["afconvert", str(aiff), str(raw), "-d", f"LEI16@{samplerate}", "-f", "WAVE", "-c", "1"],  # noqa: E501
                check=True,
            )  # fmt: skip
            self._shaper.shape(raw, out_path, register, samplerate)


class MacSayBackend:
    """Flat macOS ``say`` (no register variation) — the voice-path benchmark's plain baseline.

    Renders every register identically (the "before" the issue rejects: one flat narration voice),
    so the benchmark can quantify what the expressive path adds.
    """

    def __init__(self, voice: str = "Daniel") -> None:
        self._voice = voice

    @property
    def voice_signature(self) -> str:
        return f"macsay:{self._voice}+{_signature_suffix()}"

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "clip.aiff"
            subprocess.run(  # noqa: S603 - fixed binary, our own text
                ["say", "-v", self._voice, "-o", str(aiff), text], check=True
            )
            subprocess.run(  # noqa: S603 - convert to mono 16-bit PCM WAV at target samplerate
                ["afconvert", str(aiff), str(out_path), "-d", f"LEI16@{samplerate}", "-f", "WAVE", "-c", "1"],  # noqa: E501
                check=True,
            )  # fmt: skip


# --------------------------------------------------------------------------------------------------
# Bake driver
# --------------------------------------------------------------------------------------------------


def bake_bank(out_dir: str | Path, backend: VoiceBackend, *, samplerate: int = 48000) -> Manifest:
    """Render every vocabulary phrase to ``out_dir/<clip_id>.wav`` and write ``manifest.json``.

    The manifest stamps the current :func:`vocabulary_hash` and the backend's ``voice_signature``,
    so a later wording/register change (or a different voice / prosody chain / ffmpeg build) is
    detected at load. Returns the in-memory manifest.

    Raises :class:`ValueError` when the backend's ``voice_signature`` lacks the enforced
    persona/prosody/intensity suffix — such a bank would pass the bake but be refused by
    ``Manifest.validate`` on every load (qodo review #441).
    """
    if not backend.voice_signature.endswith(EXPECTED_SIGNATURE_SUFFIX):
        # Fail loudly BEFORE rendering a single clip — and never auto-append: stamping a
        # persona/prosody provenance the backend did not declare would forge exactly what the
        # runtime gate exists to verify.
        raise ValueError(
            f"backend voice_signature {backend.voice_signature!r} must end with "
            f"vocabulary.EXPECTED_SIGNATURE_SUFFIX {EXPECTED_SIGNATURE_SUFFIX!r} — append "
            "bake._signature_suffix() to the backend's signature"
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    phrases = list(iter_vocabulary())
    targets = [(phrase, out / f"{phrase.clip_id}.wav") for phrase in phrases]
    batch = getattr(backend, "synthesize_many", None)
    if callable(batch):
        batch([(phrase.text, phrase.register, target) for phrase, target in targets], samplerate)
    else:
        for phrase, target in targets:
            backend.synthesize(phrase.text, phrase.register, target, samplerate)

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
            register=phrase.register,
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
    if args.backend == "say":
        return MacSayBackend(voice=args.say_voice)
    if args.backend == "say-expressive":
        _require_ffmpeg(args.backend)
        return MacSayExpressiveBackend(voice=args.say_voice)
    if args.backend == "piper":
        if not args.piper_model:
            raise SystemExit("--piper-model is required for --backend piper")
        _require_ffmpeg(args.backend)
        return PiperBackend(args.piper_model)
    if args.backend == "kokoro":
        if not args.kokoro_model or not args.kokoro_voices:
            raise SystemExit("--kokoro-model and --kokoro-voices are required for --backend kokoro")
        _require_ffmpeg(args.backend)
        return KokoroBackend(args.kokoro_model, args.kokoro_voices, voice=args.kokoro_voice)
    raise SystemExit(f"unknown backend {args.backend!r}")


def _require_ffmpeg(backend: str) -> None:
    """Fail early with an actionable CLI error for backends that use the prosody shaper."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            f"--backend {backend} requires ffmpeg on PATH for deterministic prosody shaping"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bake the voice-coach phrase bank.")
    parser.add_argument("--out", required=True, help="output bank directory")
    parser.add_argument(
        "--backend",
        default="tone",
        choices=("tone", "say", "say-expressive", "piper", "kokoro"),
        help="synthesis backend",
    )
    parser.add_argument("--samplerate", type=int, default=48000)
    parser.add_argument("--piper-model", help="path to a Piper .onnx voice model (backend=piper)")
    parser.add_argument("--kokoro-model", help="path to kokoro .onnx model (backend=kokoro)")
    parser.add_argument("--kokoro-voices", help="path to kokoro voices .bin (backend=kokoro)")
    parser.add_argument("--kokoro-voice", default="am_michael", help="kokoro voice name")
    parser.add_argument("--say-voice", default="Daniel", help="macOS voice name (backend=say*)")
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
