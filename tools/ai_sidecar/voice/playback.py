"""Audio playback — the ``Playback`` interface, a pure device resolver, fakes, and real backends.

The scheduler talks to playback only through the :class:`Playback` protocol (``play`` / ``cancel`` /
``current`` / ``close``), so the real audio path and the test double are interchangeable.

**Dependency discipline (issue #340):** ``numpy`` / ``sounddevice`` / ``rtmixer`` are imported
**lazily inside the real backends** here — importing this module pulls in no third-party dependency,
so the scheduler/resolver/manifest logic stays CI-testable with no audio hardware. The device
resolver :func:`resolve_output_device` is a **pure function** over a device table, so the
"re-resolve by name + host-API, never route onto the haptic USB-DAC" criterion is unit-tested
without PortAudio.

Real backends:

* :class:`RtMixerPlayback` — the production path: one continuously-open WASAPI **shared-mode**
stream
  with a C/CFFI callback that bypasses the GIL (predictable latency under game load), per-action
  ``cancel()`` for barge-in, output device pinned by name + host-API to a headset.
* :class:`SoundDevicePlayback` — the acceptable interim fallback (``sounddevice.play``/``.stop``)
  behind the same interface, if rtmixer integration slips.

Test/verification doubles:

* :class:`RecordingPlayback` — records the dispatch sequence, lets a test mark the current clip
  finished, and (optionally) writes the played PCM to a WAV for offline inspection.
"""

from __future__ import annotations

import logging
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from tools.ai_sidecar.voice.manifest import Manifest, sha256_bytes
from tools.ai_sidecar.voice.utterance import Utterance

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy as _np

_log = logging.getLogger("ai_sidecar.voice.playback")


@runtime_checkable
class Playback(Protocol):
    """The one channel the scheduler dispatches to. Implementations must be non-blocking on play."""

    @property
    def current(self) -> Utterance | None:
        """The utterance currently sounding, or ``None`` when the channel is idle."""
        ...

    def play(self, utterance: Utterance) -> None:
        """Start ``utterance`` asynchronously. Does not block until it finishes."""
        ...

    def cancel(self) -> None:
        """Stop whatever is sounding now (barge-in). No-op if idle."""
        ...

    def close(self) -> None:
        """Release any audio resources."""
        ...


class DeviceResolutionError(RuntimeError):
    """No suitable output device matched the configured name + host-API."""


def resolve_output_device(
    name: str | None,
    host_api: str | None,
    *,
    devices: list[dict],
    host_apis: list[dict],
) -> int:
    """Resolve a PortAudio output-device index by ``name`` (+ optional ``host_api``). Pure function.

    ``devices`` / ``host_apis`` are the ``sounddevice.query_devices()`` /
    ``sounddevice.query_hostapis()`` shapes (list of dicts). A device qualifies when it has output
    channels and its name contains ``name`` (case-insensitive). When ``host_api`` is given, the
    device's host-API name must also contain it — this is what keeps voice off a same-named endpoint
    on the wrong host-API, and (because the headset name never matches the haptic USB-DAC's name)
    what guarantees voice never lands on the haptic device.

    Raises :class:`DeviceResolutionError` when nothing qualifies. On multiple matches, prefers an
    exact host-API match, else the lowest index (logging the ambiguity).
    """
    if name is None or not name.strip():
        raise DeviceResolutionError("no device name configured to pin voice output")
    needle = name.strip().lower()
    api_needle = host_api.strip().lower() if host_api else None

    matches: list[tuple[int, bool]] = []  # (device_index, exact_host_api_match)
    for idx, dev in enumerate(devices):
        if int(dev.get("max_output_channels", 0)) <= 0:
            continue
        dev_name = str(dev.get("name", "")).lower()
        if needle not in dev_name:
            continue
        exact_api = True
        if api_needle is not None:
            api_idx = int(dev.get("hostapi", -1))
            api_name = ""
            if 0 <= api_idx < len(host_apis):
                api_name = str(host_apis[api_idx].get("name", "")).lower()
            if api_needle not in api_name:
                continue  # host-API was specified and does not match → not a candidate at all
            exact_api = api_needle == api_name
        matches.append((idx, exact_api))

    if not matches:
        raise DeviceResolutionError(f"no output device matches name={name!r} host_api={host_api!r}")
    if len(matches) > 1:
        exact = [m for m in matches if m[1]]
        chosen = (exact or matches)[0][0]
        _log.warning(
            "voice: %d output devices match name=%r host_api=%r; using index %d",
            len(matches),
            name,
            host_api,
            chosen,
        )
        return chosen
    return matches[0][0]


# --------------------------------------------------------------------------------------------------
# Pre-decoded clip bank
# --------------------------------------------------------------------------------------------------


class Bank:
    """Pre-decoded float32 PCM for every clip, keyed by ``clip_id``, at one samplerate.

    Built once at startup so the hot path never touches the filesystem or a decoder. ``numpy`` is
    lazy-imported here (real-backend territory); the resolver/scheduler never construct a ``Bank``.
    """

    def __init__(self, samplerate: int, clips: dict[str, _np.ndarray]) -> None:
        self.samplerate = samplerate
        self.clips = clips

    def get(self, clip_id: str) -> _np.ndarray | None:
        return self.clips.get(clip_id)

    @staticmethod
    def from_manifest(manifest: Manifest, bank_dir: str | Path) -> Bank:
        """Decode every manifest clip under ``bank_dir`` to float32 PCM at the manifest
        samplerate."""
        import numpy as np  # lazy — only when a real bank is built

        base = Path(bank_dir)
        clips: dict[str, np.ndarray] = {}
        for entry in manifest.clips.values():
            fp = base / entry.file
            try:
                raw = fp.read_bytes()
            except OSError as exc:
                _log.error("voice: cannot read clip %s (%s): %s", entry.clip_id, fp, exc)
                continue
            # Enforce the manifest digest at LOAD, not just in validate(): a corrupted or
            # substituted (yet decodable) clip must be skipped, never played — "never play the
            # wrong clip" (#340).
            digest = sha256_bytes(raw)
            if digest != entry.sha256:
                _log.error(
                    "voice: sha256 mismatch for clip %s (file=%s… manifest=%s…) — skipping",
                    entry.clip_id,
                    digest[:12],
                    entry.sha256[:12],
                )
                continue
            try:
                pcm = _decode_wav_float32(fp, manifest.samplerate, np)
            except (OSError, wave.Error, ValueError) as exc:
                # Skip a bad clip loudly rather than abort the whole bank (graceful degradation).
                _log.error("voice: failed to decode clip %s (%s): %s", entry.clip_id, fp, exc)
                continue
            clips[entry.clip_id] = pcm
        return Bank(samplerate=manifest.samplerate, clips=clips)


def _decode_wav_float32(path: str | Path, expected_sr: int, np) -> _np.ndarray:
    """Decode a 16/32-bit PCM WAV to mono float32 in [-1, 1]. Stdlib ``wave`` + numpy."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        if sr != expected_sr:
            raise ValueError(f"samplerate {sr} != manifest {expected_sr}")
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sampwidth == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {sampwidth} bytes")
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return np.ascontiguousarray(data, dtype=np.float32)


# --------------------------------------------------------------------------------------------------
# Test / verification double
# --------------------------------------------------------------------------------------------------


class RecordingPlayback:
    """A :class:`Playback` that records dispatches instead of making sound.

    Used by unit tests and the offline verification harness. ``current`` reflects the last
    :meth:`play` until :meth:`finish` (or :meth:`cancel`) is called, so a test can model "a clip is
    still sounding" for barge-in assertions. Optionally appends each played clip's PCM (from a
    :class:`Bank`) to an output WAV so a human can listen to what the engine would have spoken.
    """

    def __init__(self, *, bank: Bank | None = None) -> None:
        self._current: Utterance | None = None
        self.played: list[Utterance] = []
        self.cancelled: list[Utterance] = []
        self._bank = bank
        self._wav_pcm: list = []

    @property
    def current(self) -> Utterance | None:
        return self._current

    def play(self, utterance: Utterance) -> None:
        self.played.append(utterance)
        self._current = utterance
        if self._bank is not None:
            pcm = self._bank.get(utterance.clip_id)
            if pcm is not None:
                self._wav_pcm.append(pcm)

    def cancel(self) -> None:
        if self._current is not None:
            self.cancelled.append(self._current)
        self._current = None

    def finish(self) -> None:
        """Mark the current clip as having finished sounding (frees the channel)."""
        self._current = None

    def close(self) -> None:
        self._current = None

    def write_wav(self, path: str | Path, samplerate: int) -> None:
        """Write the concatenation of every played clip to a 16-bit WAV (offline inspection)."""
        import numpy as np

        if not self._wav_pcm:
            raise ValueError("no PCM captured — RecordingPlayback needs a Bank to write WAV")
        joined = np.concatenate(self._wav_pcm)
        pcm16 = np.clip(joined, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype("<i2")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(pcm16.tobytes())


# --------------------------------------------------------------------------------------------------
# Real backends (lazy-imported deps; not exercised on CI)
# --------------------------------------------------------------------------------------------------


class RtMixerPlayback:
    """Production playback: a continuously-open ``sounddevice`` stream driven by ``rtmixer``.

    One shared-mode output stream stays open and warmed; ``play`` submits a pre-decoded clip to the
    rtmixer C callback (GIL-free, predictable latency under game load); ``cancel`` cancels the live
    action for barge-in. The device is re-resolved by name + host-API on construction so a USB
    replug
    (which reshuffles PortAudio indices) never routes voice onto the haptic USB-DAC.

    All heavy deps are imported here, not at module import time.
    """

    def __init__(
        self,
        bank: Bank,
        *,
        device_name: str | None,
        host_api: str | None,
        channels: int = 1,
    ) -> None:
        import rtmixer  # noqa: F401 - imported to fail fast if the extra is missing
        import sounddevice as sd

        self._bank = bank
        self._sd = sd
        self._rtmixer = rtmixer
        device_index = resolve_output_device(
            device_name,
            host_api,
            devices=list(sd.query_devices()),
            host_apis=list(sd.query_hostapis()),
        )
        self._mixer = rtmixer.Mixer(
            device=device_index,
            channels=channels,
            samplerate=bank.samplerate,
        )
        self._mixer.start()
        self._current: Utterance | None = None
        self._action = None
        _log.info(
            "voice: rtmixer stream open on device index %d @ %d Hz", device_index, bank.samplerate
        )

    @property
    def current(self) -> Utterance | None:
        # An action that has run to completion frees the channel.
        if self._action is not None and self._action.done:
            self._current = None
            self._action = None
        return self._current

    def play(self, utterance: Utterance) -> None:
        pcm = self._bank.get(utterance.clip_id)
        if pcm is None:
            _log.error("voice: clip %s absent from bank — staying silent", utterance.clip_id)
            return
        self._action = self._mixer.play_buffer(pcm, channels=1)
        self._current = utterance

    def cancel(self) -> None:
        if self._action is not None:
            try:
                self._mixer.cancel(self._action)
            except Exception:  # noqa: BLE001 - cancel is best-effort
                _log.exception("voice: rtmixer cancel failed")
        self._action = None
        self._current = None

    def close(self) -> None:
        try:
            self._mixer.stop()
        except Exception:  # noqa: BLE001
            _log.exception("voice: rtmixer stop failed")
        self._current = None


class _TimedCurrent:
    """Tracks the currently-sounding utterance with an estimated end time. Pure (no audio dep).

    ``sounddevice.play`` is fire-and-forget with no cheap "is it still playing?" signal, so the
    fallback backend estimates completion from clip duration: :meth:`set` stamps an end time, and
    :attr:`current` auto-clears once the clock passes it. Without this the channel would read busy
    forever and the scheduler would drop every cue after the first. Clock is injectable for tests.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._current: Utterance | None = None
        self._until = 0.0

    def set(self, utterance: Utterance, duration_s: float) -> None:
        self._current = utterance
        self._until = self._clock() + max(0.0, duration_s)

    def clear(self) -> None:
        self._current = None

    @property
    def current(self) -> Utterance | None:
        if self._current is not None and self._clock() >= self._until:
            self._current = None
        return self._current


class SoundDevicePlayback:
    """Interim fallback: ``sounddevice.play(device=)`` + ``.stop()`` behind the same interface."""

    def __init__(
        self,
        bank: Bank,
        *,
        device_name: str | None,
        host_api: str | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        import sounddevice as sd

        self._bank = bank
        self._sd = sd
        self._device = resolve_output_device(
            device_name,
            host_api,
            devices=list(sd.query_devices()),
            host_apis=list(sd.query_hostapis()),
        )
        # Estimated-completion tracking so the channel frees when a clip finishes (not just on
        # cancel/close) — otherwise the scheduler treats it as perpetually busy after the first cue.
        self._timed = _TimedCurrent(clock)

    @property
    def current(self) -> Utterance | None:
        return self._timed.current

    def play(self, utterance: Utterance) -> None:
        pcm = self._bank.get(utterance.clip_id)
        if pcm is None:
            _log.error("voice: clip %s absent from bank — staying silent", utterance.clip_id)
            return
        self._sd.play(pcm, samplerate=self._bank.samplerate, device=self._device)
        self._timed.set(utterance, len(pcm) / self._bank.samplerate)

    def cancel(self) -> None:
        self._sd.stop()
        self._timed.clear()

    def close(self) -> None:
        self._sd.stop()
        self._timed.clear()
