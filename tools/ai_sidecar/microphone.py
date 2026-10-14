"""Bounded, opt-in tablet PCM transport and local proof capture (#531 Part I).

No audio dependencies, playback, background recording, or server-side audio storage.
The browser supplies PCM16 little-endian mono at its actual AudioContext sample rate.
"""

from __future__ import annotations

import base64
import binascii
import re
import wave
from pathlib import Path
from typing import Any

MIC_CHUNK = "voice.mic.chunk"
MIC_SUBSCRIBE = "voice.mic.subscribe"
MIC_END = "voice.mic.end"
MAX_SAMPLES = 4096
MAX_CAPTURE_SECONDS = 180
SAMPLE_RATES = frozenset({16000, 22050, 24000, 32000, 44100, 48000, 96000})
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def decode_chunk(frame: dict[str, Any]) -> bytes:
    """Validate one bounded chunk before decoding; raise ValueError on malformed input."""
    capture_id = frame.get("capture_id")
    if not isinstance(capture_id, str) or not _ID.fullmatch(capture_id):
        raise ValueError("microphone capture_id must be 1-64 ASCII identifier characters")
    for key in ("seq", "sample_offset", "sample_rate"):
        if type(frame.get(key)) is not int or frame[key] < 0:
            raise ValueError(f"microphone {key} must be a non-negative integer")
    rate = frame["sample_rate"]
    if rate not in SAMPLE_RATES:
        raise ValueError("microphone sample_rate is unsupported")
    if frame["sample_offset"] > rate * MAX_CAPTURE_SECONDS:
        raise ValueError("microphone capture exceeds duration limit")
    encoded = frame.get("pcm16")
    if not isinstance(encoded, str) or not 4 <= len(encoded) <= ((MAX_SAMPLES * 2 + 2) // 3) * 4:
        raise ValueError("microphone pcm16 must be bounded base64 PCM")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("microphone pcm16 must be valid base64") from exc
    if not pcm or len(pcm) % 2 or len(pcm) > MAX_SAMPLES * 2:
        raise ValueError("microphone pcm16 must contain 1-4096 whole PCM16 samples")
    if frame["sample_offset"] + len(pcm) // 2 > rate * MAX_CAPTURE_SECONDS:
        raise ValueError("microphone capture exceeds duration limit")
    return pcm


class MicContinuity:
    """One stream identity and exact sequence/sample progression; gaps are never filled."""

    def __init__(self) -> None:
        self.capture_id: str | None = None
        self.sample_rate = 0
        self.next_seq = 0
        self.next_offset = 0

    def accept(self, frame: dict[str, Any], *, allow_midstream: bool = False) -> bytes:
        pcm = decode_chunk(frame)
        first = self.capture_id is None
        if first:
            if not allow_midstream and (frame["seq"] != 0 or frame["sample_offset"] != 0):
                raise ValueError("microphone stream must start at sequence/sample zero")
            self.capture_id = frame["capture_id"]
            self.sample_rate = frame["sample_rate"]
            self.next_seq = frame["seq"]
            self.next_offset = frame["sample_offset"]
        if frame["capture_id"] != self.capture_id or frame["sample_rate"] != self.sample_rate:
            raise ValueError("microphone stream identity/sample rate changed")
        if frame["seq"] != self.next_seq or frame["sample_offset"] != self.next_offset:
            raise ValueError("microphone stream sequence/sample gap or duplicate")
        self.next_seq += 1
        self.next_offset += len(pcm) // 2
        return pcm


class MicWavCapture:
    """Write a single continuous stream without overwriting prior evidence."""

    def __init__(self, path: Path, *, max_seconds: float) -> None:
        if not 0 < max_seconds <= MAX_CAPTURE_SECONDS:
            raise ValueError(f"capture duration must be >0 and <= {MAX_CAPTURE_SECONDS}s")
        self.stream = MicContinuity()
        self.max_seconds = max_seconds
        self.samples = 0
        self._file = path.open("xb")
        self._wav = wave.open(self._file, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(48000)  # overwritten by the first actual chunk before any data

    def accept(self, frame: dict[str, Any]) -> None:
        pcm = self.stream.accept(frame, allow_midstream=True)
        if not self.samples:
            self._wav.setframerate(self.stream.sample_rate)
        if self.samples + len(pcm) // 2 > self.stream.sample_rate * self.max_seconds:
            raise ValueError("microphone recording duration limit reached")
        self._wav.writeframesraw(pcm)
        self.samples += len(pcm) // 2

    def close(self) -> None:
        try:
            self._wav.close()
        finally:
            self._file.close()
