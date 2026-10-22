"""End-to-end audible-latency harness — how timely is the coach IN THE ROOM (issue #381).

The CI timing report (:mod:`timing_report`) proves emit→dispatch with an injected clock; this
harness measures the half nothing else can: **dispatch → acoustic onset at a real microphone**,
covering the WS hop to a remote audio endpoint (the tablet page, issue #511 Part D), the
endpoint's audio stack, and the speaker→mic path.

Method (council-reviewed, 2026-07-11):

* **Room capture** — the Android tablet's opt-in AudioWorklet microphone stream is recorded
  ON THE PC over the existing USB-loopback WS. Legacy scrcpy capture is explicitly selectable.
  No mic hardware on the PC is needed.
* **Clock sync** — the PC plays a 5→15 kHz log chirp at the START and END of the capture,
  wall-stamped at the DAC via the PortAudio callback ``time_info``. Matched-filtering the known
  chirp in the recording maps recording samples ↔ PC wall clock; two anchors correct linear
  drift. The residual systematic uncertainty (PC output path estimate) is REPORTED, not hidden.
* **Cue onsets** — every dispatched clip's own baked waveform (the bank is the template
  library) is matched-filtered inside a search window after its ``t_wall_ms`` dispatch stamp
  (from the ``coaching.voice`` stream / ``/voice/dispatches``), which stays robust under game
  noise. ``audible_latency_ms = onset_wall - t_wall_ms``.
* **Decomposition** — when the tablet page's ``voice.echo`` records are available
  (``/voice/echoes``), the report also splits server→tablet round-trip (server clock) and
  receive→play JS time (tablet clock). Cross-device clock differences are never subtracted.

Two subcommands::

    python -m tools.ai_sidecar.voice.audible_latency run --bank <dir> --out-dir <dir> \
        [--burst N | --observe-seconds S] [--sidecar-url ws://127.0.0.1:8765] ...
    python -m tools.ai_sidecar.voice.audible_latency analyze --recording rec.wav \
        --bank <dir> --dispatches dispatches.json --chirps chirps.json --out-dir <dir>

``run`` orchestrates capture + cue injection + scraping and then runs ``analyze``. Heavy deps
(``numpy``, ``sounddevice``, ``websockets``) are imported lazily inside the functions that
need them, so importing this module stays stdlib-only (repo dependency discipline, #340).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import statistics
import subprocess
import time
import urllib.parse
import urllib.request
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.ai_sidecar.microphone import (
    MAX_CAPTURE_SECONDS,
    MIC_CHUNK,
    MIC_END,
    MIC_SUBSCRIBE,
    MicWavCapture,
)

_log = logging.getLogger("ai_sidecar.voice.audible_latency")

CHIRP_F0_HZ = 5_000.0
CHIRP_F1_HZ = 15_000.0
CHIRP_DURATION_S = 0.3
CHIRP_AMPLITUDE = 0.7
#: Matched-filter acceptance: normalized correlation peak must clear this floor AND stand
#: this many times above the window's median score (engine noise never correlates this well
#: with a specific speech waveform; validated by the synthetic-noise unit tests).
MATCH_MIN_SCORE = 0.20
MATCH_MIN_PROMINENCE = 3.0
#: A candidate region counts as a real instance only when its peak reaches this fraction of
#: the window's global max — separates a genuinely earlier same-clip instance (normalized
#: score is gain-invariant, so comparable) from the match's own correlation sidelobes
#: (structurally ~-13 dB / ~4x lower for the log chirp).
_REGION_DOMINANCE = 0.6
#: How long after a dispatch stamp the clip onset is searched for. Covers WS hop + a slow
#: Android audio stack with margin; anything later is reported unmatched rather than guessed.
SEARCH_WINDOW_MS = 3_000.0
DEFAULT_ACT_BUDGET_MS = 450.0

_BURST_CUES: tuple[dict[str, Any], ...] = (
    {"kind": "late_brake", "urgency": "act", "register": "critical"},
    {"kind": "apex_deficit", "urgency": "info", "register": "calm", "corner": 2},
    {"kind": "late_brake", "urgency": "act", "register": "urgent"},
    {"kind": "late_brake", "urgency": "prepare", "register": "alert", "corner": 4},
    {"kind": "apex_deficit", "urgency": "info", "register": "calm", "corner": 6},
    {"kind": "late_brake", "urgency": "act", "register": "critical", "corner": 8},
)


@dataclass
class ChirpMark:
    """One sync chirp: what the PC believes about when it hit the DAC (wall clock, ms)."""

    label: str
    t_wall_ms: float
    t_dac_wall_ms: float | None
    output_latency_ms: float | None
    f0_hz: float = CHIRP_F0_HZ
    f1_hz: float = CHIRP_F1_HZ

    def anchor_wall_ms(self) -> float:
        return self.t_dac_wall_ms if self.t_dac_wall_ms is not None else self.t_wall_ms


@dataclass
class CueResult:
    seq: int
    clip_id: str
    kind: str
    urgency: str
    register: str
    t_dispatch_wall_ms: float
    matched: bool
    onset_wall_ms: float | None = None
    audible_latency_ms: float | None = None
    match_score: float | None = None
    match_prominence: float | None = None
    rtt_ms: float | None = None
    js_play_ms: float | None = None
    buffer_state: str | None = None


@dataclass
class AudibleLatencyReport:
    recording: str
    recording_samplerate: int
    chirps: list[dict[str, Any]]
    clock_map: dict[str, Any]
    cues: list[CueResult]
    stats: dict[str, Any] = field(default_factory=dict)
    assertions: dict[str, bool] = field(default_factory=dict)
    systematic_uncertainty_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["cues"] = [asdict(c) for c in self.cues]
        return out


# --------------------------------------------------------------------------------------------
# Chirp generation + DAC-stamped playback
# --------------------------------------------------------------------------------------------


def make_chirp(
    samplerate: int, np: Any, *, f0_hz: float = CHIRP_F0_HZ, f1_hz: float = CHIRP_F1_HZ
) -> Any:
    """Log-frequency chirp; the default 5→15 kHz band avoids low/mid engine noise."""
    if not (math.isfinite(f0_hz) and math.isfinite(f1_hz) and 0 < f0_hz < f1_hz < samplerate / 2):
        raise ValueError("chirp frequencies must be finite, ordered, positive and below Nyquist")
    n = int(CHIRP_DURATION_S * samplerate)
    t = np.arange(n, dtype=np.float64) / samplerate
    k = (f1_hz / f0_hz) ** (1.0 / CHIRP_DURATION_S)
    phase = 2.0 * np.pi * f0_hz * (k**t - 1.0) / np.log(k)
    sig = np.sin(phase)
    # 10 ms raised-cosine edges: no click transient to smear the matched-filter peak.
    edge = max(1, int(0.010 * samplerate))
    ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(edge) / edge))
    sig[:edge] *= ramp
    sig[-edge:] *= ramp[::-1]
    return (CHIRP_AMPLITUDE * sig).astype(np.float32)


def _resolve_chirp_output(
    sd: Any,
    *,
    device: str | None,
    host_api: str | None,
    samplerate: int,
    channel_map: tuple[int, ...] | str | None = None,
) -> tuple[int, int, tuple[int, ...]]:
    """Resolve and negotiate the chirp output, including the system-default device."""
    from tools.ai_sidecar.voice.playback import (
        DeviceResolutionError,
        resolve_output_device,
        resolve_output_layout,
    )

    devices = list(sd.query_devices())
    host_apis = list(sd.query_hostapis())
    if device:
        device_index = resolve_output_device(
            device,
            host_api,
            devices=devices,
            host_apis=host_apis,
        )
    else:
        try:
            default_output = sd.default.device[1]
            if default_output is None:
                # Factory-default sounddevice settings delegate device selection to PortAudio.
                # query_devices(kind="output") exposes that selected device's concrete index.
                default_device = sd.query_devices(kind="output")
                device_index = int(default_device["index"])
            elif isinstance(default_output, str):
                device_index = resolve_output_device(
                    default_output,
                    host_api,
                    devices=devices,
                    host_apis=host_apis,
                )
            else:
                device_index = int(default_output)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise DeviceResolutionError("no default PortAudio output device is configured") from exc
        if device_index < 0 or device_index >= len(devices):
            raise DeviceResolutionError(
                f"default PortAudio output device index {device_index} is unavailable"
            )

    layout = resolve_output_layout(
        device_index,
        bank_channels=1,
        samplerate=samplerate,
        devices=devices,
        host_apis=host_apis,
        check_output_settings=sd.check_output_settings,
        channel_map=channel_map,
    )
    return (
        device_index,
        layout.stream_channels,
        tuple(channel - 1 for channel in layout.channel_map),
    )


def play_chirp(
    label: str,
    *,
    device: str | None,
    host_api: str | None,
    channel_map: tuple[int, ...] | str | None = None,
    f0_hz: float = CHIRP_F0_HZ,
    f1_hz: float = CHIRP_F1_HZ,
) -> ChirpMark:
    """Play the sync chirp on the PC output and wall-stamp its first sample at the DAC.

    Uses the PortAudio callback's ``outputBufferDacTime`` to map the first callback buffer to
    the wall clock — collapsing most of the "when did the speaker actually move" uncertainty
    that a naive pre-play stamp carries.
    """
    import numpy as np
    import sounddevice as sd

    samplerate = 48_000
    device_index, stream_channels, output_channels = _resolve_chirp_output(
        sd,
        device=device,
        host_api=host_api,
        samplerate=samplerate,
        channel_map=channel_map,
    )
    chirp = make_chirp(samplerate, np, f0_hz=f0_hz, f1_hz=f1_hz)
    state: dict[str, Any] = {"pos": 0, "dac_wall_ms": None, "latency_ms": None}
    done = __import__("threading").Event()

    def _callback(outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        if state["dac_wall_ms"] is None:
            now_wall = time.time()
            try:
                stream_now = stream.time
                dac = time_info.outputBufferDacTime
                state["dac_wall_ms"] = (now_wall + (dac - stream_now)) * 1000.0
                state["latency_ms"] = float(stream.latency) * 1000.0
            except Exception:  # noqa: BLE001 — DAC stamping is best-effort refinement
                state["dac_wall_ms"] = None
        pos = state["pos"]
        chunk = chirp[pos : pos + frames]
        outdata.fill(0.0)
        for output_channel in output_channels:
            outdata[: len(chunk), output_channel] = chunk
        if len(chunk) < frames:
            done.set()
            raise sd.CallbackStop
        state["pos"] = pos + frames

    t_wall_ms = time.time() * 1000.0
    stream = sd.OutputStream(
        samplerate=samplerate,
        channels=stream_channels,
        dtype="float32",
        device=device_index,
        callback=_callback,
    )
    with stream:
        done.wait(timeout=CHIRP_DURATION_S + 2.0)
    mark = ChirpMark(
        label=label,
        t_wall_ms=t_wall_ms,
        t_dac_wall_ms=state["dac_wall_ms"],
        output_latency_ms=state["latency_ms"],
        f0_hz=f0_hz,
        f1_hz=f1_hz,
    )
    _log.info(
        "chirp %s: wall=%.1f dac_wall=%s latency=%s",
        label,
        mark.t_wall_ms,
        f"{mark.t_dac_wall_ms:.1f}" if mark.t_dac_wall_ms else "n/a",
        f"{mark.output_latency_ms:.1f}ms" if mark.output_latency_ms else "n/a",
    )
    return mark


# --------------------------------------------------------------------------------------------
# Matched filter + clock mapping (pure numpy; unit-tested on synthetic signals)
# --------------------------------------------------------------------------------------------


def normalized_match(recording: Any, template: Any, np: Any) -> Any:
    """Normalized cross-correlation score in [0, 1] for every alignment (FFT-based).

    ``score[s] = |sum(rec[s:s+L] * tmpl)| / (||rec[s:s+L]|| * ||tmpl||)`` — invariant to
    recording gain, so scrcpy/mic AGC cannot fake or hide a match.
    """
    rec = recording.astype(np.float64)
    tmpl = template.astype(np.float64)
    n = len(rec)
    length = len(tmpl)
    if length == 0 or n < length:
        return np.zeros(0)
    size = 1
    while size < n + length:
        size *= 2
    corr = np.fft.irfft(np.fft.rfft(rec, size) * np.conj(np.fft.rfft(tmpl, size)), size)[
        : n - length + 1
    ]
    energy = np.concatenate(([0.0], np.cumsum(rec * rec)))
    window_energy = energy[length:] - energy[: n - length + 1]
    tmpl_norm = float(np.sqrt(np.sum(tmpl * tmpl)))
    denom = np.sqrt(np.maximum(window_energy, 1e-12)) * max(tmpl_norm, 1e-12)
    return np.abs(corr) / denom


def bandlimit(signal: Any, samplerate: float, low_hz: float, high_hz: float, np: Any) -> Any:
    """Zero-phase FFT band-pass with 500 Hz raised-cosine skirts.

    Zero phase keeps every onset in place, so a band-limited search reports the same sample
    as the unfiltered signal would. Out-of-band energy (engine rumble under a 5-15 kHz chirp)
    otherwise inflates the normalized-score denominator without carrying anchor evidence.
    """
    if not (
        math.isfinite(low_hz) and math.isfinite(high_hz) and 0 < low_hz < high_hz < samplerate / 2
    ):
        raise ValueError("band edges must be finite, ordered, positive and below Nyquist")
    values = np.asarray(signal, dtype=np.float64)
    size = 1
    while size < len(values):
        size *= 2
    spectrum = np.fft.rfft(values, size)
    freqs = np.fft.rfftfreq(size, 1.0 / samplerate)
    skirt = 500.0
    weights = ((freqs >= low_hz) & (freqs <= high_hz)).astype(np.float64)
    rise = (freqs > low_hz - skirt) & (freqs < low_hz)
    weights[rise] = 0.5 - 0.5 * np.cos(np.pi * (freqs[rise] - (low_hz - skirt)) / skirt)
    fall = (freqs > high_hz) & (freqs < high_hz + skirt)
    weights[fall] = 0.5 + 0.5 * np.cos(np.pi * (freqs[fall] - high_hz) / skirt)
    return np.fft.irfft(spectrum * weights, size)[: len(values)]


def find_onset(
    recording: Any,
    template: Any,
    np: Any,
    *,
    start: int = 0,
    end: int | None = None,
    min_score: float = MATCH_MIN_SCORE,
    min_prominence: float = MATCH_MIN_PROMINENCE,
) -> tuple[int | None, float, float]:
    """Best template onset inside ``recording[start:end]``.

    Returns ``(onset_sample, score, prominence)`` — onset ``None`` when the peak fails the
    score/prominence gates (never guess an onset the data does not support).
    """
    end = len(recording) if end is None else min(end, len(recording))
    segment = recording[start:end]
    scores = normalized_match(segment, template, np)
    if len(scores) == 0:
        return None, 0.0, 0.0
    median = float(np.median(scores))
    peak_idx = int(np.argmax(scores))
    if float(scores[peak_idx]) < min_score:
        peak = float(scores[peak_idx])
        return None, peak, peak / max(median, 1e-9)
    # EARLIEST comparable instance, not the loudest: with two instances of the same clip in
    # one window, a bare argmax locks onto the louder LATER one and reports an absurd
    # latency for the earlier cue (PR #519 adversarial review). An earlier candidate counts
    # as a distinct instance only when it is (a) separated from the current peak by more
    # than one template length — the same instance's own correlation ramp/sidelobes span
    # +/-L by construction (periodic tone clips ramp for the full overlap range; a chirp's
    # -13 dB sidelobes hug the main lobe) — and (b) comparable in normalized score
    # (gain-invariant, so a true instance scores near the max while noise does not).
    length = len(template)
    while True:
        cutoff = peak_idx - length
        if cutoff <= 0:
            break
        earlier = scores[:cutoff]
        candidate = int(np.argmax(earlier))
        if float(earlier[candidate]) < max(min_score, _REGION_DOMINANCE * float(scores[peak_idx])):
            break
        peak_idx = candidate
    peak = float(scores[peak_idx])
    prominence = peak / max(median, 1e-9)
    if prominence < min_prominence:
        return None, peak, prominence
    return start + peak_idx, peak, prominence


@dataclass
class ClockMap:
    """Linear map recording-sample → PC wall ms, anchored on one or two chirps.

    ``anchors_used`` records whether the slope came from a two-chirp drift fit (2) or the
    nominal samplerate (1) — the report asserts on it so a missed end chirp can never
    silently downgrade a drift-corrected run (PR #519 adversarial review).
    """

    anchor_sample: int
    anchor_wall_ms: float
    ms_per_sample: float
    anchors_used: int = 1

    def wall_ms(self, sample: int) -> float:
        return self.anchor_wall_ms + (sample - self.anchor_sample) * self.ms_per_sample

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_clock_map(
    recording: Any,
    samplerate: int,
    chirps: list[ChirpMark],
    np: Any,
    *,
    band_hz: tuple[float, float] | None = None,
    min_score: float = MATCH_MIN_SCORE,
    min_prominence: float = MATCH_MIN_PROMINENCE,
) -> tuple[ClockMap, list[dict[str, Any]]]:
    """Locate each chirp in the recording and fit the sample↔wall-clock map.

    With two located chirps the slope corrects capture-clock drift; with one, the nominal
    samplerate is trusted. Raises ``ValueError`` when no chirp is found — without an anchor
    every downstream number would be fiction. ``band_hz`` searches a zero-phase band-limited
    copy (onsets unchanged); callers that relax the score floor must cross-validate anchors.
    """
    if band_hz is not None:
        recording = bandlimit(recording, samplerate, band_hz[0], band_hz[1], np)
    criteria = {"min_score": min_score, "min_prominence": min_prominence}
    third = len(recording) // 3
    found: list[tuple[ChirpMark, int]] = []
    detail: list[dict[str, Any]] = []
    start_onset: int | None = None
    for mark in chirps:
        template = make_chirp(samplerate, np, f0_hz=mark.f0_hz, f1_hz=mark.f1_hz)
        if mark.label == "start":
            onset, score, prom = find_onset(
                recording, template, np, start=0, end=2 * third, **criteria
            )
            if onset is not None:
                start_onset = onset
        else:
            # Search for the END chirp strictly AFTER the located start chirp — the naive
            # overlapping regions could lock both anchors onto the SAME chirp instance on a
            # short run, degenerating the pair (PR #519 adversarial review).
            search_from = start_onset + 2 * len(template) if start_onset is not None else third
            onset, score, prom = find_onset(recording, template, np, start=search_from, **criteria)
        detail.append(
            {
                "label": mark.label,
                "onset_sample": onset,
                "score": round(score, 4),
                "prominence": round(prom, 2),
                "anchor_wall_ms": mark.anchor_wall_ms(),
                "band_hz": list(band_hz) if band_hz is not None else None,
                **criteria,
            }
        )
        if onset is not None:
            found.append((mark, onset))
    if not found:
        raise ValueError("no sync chirp located in the recording — cannot anchor the clock map")
    nominal = 1000.0 / samplerate
    if len(found) >= 2:
        (m0, s0), (m1, s1) = found[0], found[-1]
        if s1 > s0 + samplerate:  # anchors must be well separated to fit a slope
            slope = (m1.anchor_wall_ms() - m0.anchor_wall_ms()) / (s1 - s0)
            # A capture clock more than 5% off nominal means a mis-located chirp, not drift.
            if abs(slope - nominal) / nominal < 0.05:
                return ClockMap(s0, m0.anchor_wall_ms(), slope, anchors_used=2), detail
            _log.warning(
                "chirp-pair slope %.6f ms/sample deviates >5%% from nominal %.6f — "
                "falling back to single-anchor map",
                slope,
                nominal,
            )
    mark, sample = found[0]
    return ClockMap(sample, mark.anchor_wall_ms(), nominal, anchors_used=1), detail


def _load_wav_mono(path: Path, np: Any) -> tuple[Any, int]:
    with wave.open(str(path), "rb") as wf:
        samplerate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {width} in {path}")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, samplerate


def _resample_linear(signal: Any, sr_from: int, sr_to: int, np: Any) -> Any:
    if sr_from == sr_to:
        return signal
    n_to = int(round(len(signal) * sr_to / sr_from))
    x_to = np.linspace(0.0, len(signal) - 1.0, n_to)
    return np.interp(x_to, np.arange(len(signal)), signal)


# --------------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------------


def analyze(
    *,
    recording_path: Path,
    bank_dir: Path,
    dispatches: list[dict[str, Any]],
    chirps: list[ChirpMark],
    echoes: list[dict[str, Any]] | None = None,
    act_budget_ms: float = DEFAULT_ACT_BUDGET_MS,
    expected_dispatches: int | None = None,
) -> AudibleLatencyReport:
    """Locate every dispatched clip in the room recording and build the timeliness report.

    ``expected_dispatches`` (burst mode) asserts the scheduler actually spoke every injected
    cue — without it, scheduler suppression would silently shrink the sample and a partial
    run could read as a full PASS (PR #519 adversarial review).
    """
    import numpy as np

    from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest
    from tools.ai_sidecar.voice.playback import Bank

    recording, rec_sr = _load_wav_mono(recording_path, np)
    manifest = Manifest.load(bank_dir / MANIFEST_FILENAME)
    bank = Bank.from_manifest(manifest, bank_dir)

    clock_map, chirp_detail = build_clock_map(recording, rec_sr, chirps, np)
    echo_by_seq = {e.get("seq"): e for e in (echoes or [])}

    cues: list[CueResult] = []
    # Same-clip repeats inside one search window must not cross-assign onsets: process in
    # dispatch order and start each same-clip search after the previous match (PR #519
    # adversarial review).
    next_allowed_start: dict[str, int] = {}
    dispatches = sorted(dispatches, key=lambda d: float(d.get("t_wall_ms", 0.0)))
    for d in dispatches:
        seq = int(d.get("seq", -1))
        clip_id = str(d.get("clip_id", ""))
        t_dispatch = float(d.get("t_wall_ms", 0.0))
        cue = CueResult(
            seq=seq,
            clip_id=clip_id,
            kind=str(d.get("kind", "")),
            urgency=str(d.get("urgency", "")),
            register=str(d.get("register", "")),
            t_dispatch_wall_ms=t_dispatch,
            matched=False,
        )
        echo = echo_by_seq.get(seq)
        if echo is not None:
            t_server = echo.get("t_server_ms")
            t_receive = echo.get("t_receive_ms")
            t_play = echo.get("t_play_ms")
            if isinstance(t_server, int | float):
                cue.rtt_ms = float(t_server) - t_dispatch
            if isinstance(t_receive, int | float) and isinstance(t_play, int | float):
                cue.js_play_ms = float(t_play) - float(t_receive)
            state = echo.get("buffer_state")
            cue.buffer_state = state if isinstance(state, str) else None

        pcm = bank.get(clip_id)
        if pcm is None or t_dispatch <= 0:
            cues.append(cue)
            continue
        template = _resample_linear(np.asarray(pcm, dtype=np.float64), bank.samplerate, rec_sr, np)
        # Search from the dispatch stamp forward; a small negative margin absorbs clock-map
        # uncertainty without letting a pre-dispatch sound masquerade as the cue. The end is
        # extended by the template length: normalized_match only scores FULL alignments, so
        # without the extension an onset near the window edge could never match and the
        # effective window would silently shrink by the clip duration (PR #519 review).
        start_wall = t_dispatch - 100.0
        start_sample = clock_map.anchor_sample + int(
            (start_wall - clock_map.anchor_wall_ms) / clock_map.ms_per_sample
        )
        start_sample = max(0, start_sample, next_allowed_start.get(clip_id, 0))
        end_sample = (
            start_sample + int((SEARCH_WINDOW_MS + 100.0) / clock_map.ms_per_sample) + len(template)
        )
        onset, score, prom = find_onset(
            recording, template, np, start=start_sample, end=max(0, end_sample)
        )
        cue.match_score = round(score, 4)
        cue.match_prominence = round(prom, 2)
        if onset is not None:
            cue.matched = True
            cue.onset_wall_ms = clock_map.wall_ms(onset)
            cue.audible_latency_ms = cue.onset_wall_ms - t_dispatch
            next_allowed_start[clip_id] = onset + len(template) // 2
        cues.append(cue)

    matched = [c for c in cues if c.matched and c.audible_latency_ms is not None]
    latencies = [c.audible_latency_ms for c in matched if c.audible_latency_ms is not None]
    act_latencies = [
        c.audible_latency_ms
        for c in matched
        if c.urgency == "act" and c.audible_latency_ms is not None
    ]
    stats: dict[str, Any] = {
        "dispatched": len(cues),
        "matched": len(matched),
        "unmatched": len(cues) - len(matched),
    }
    if latencies:
        stats["latency_ms"] = _percentiles(latencies)
    if act_latencies:
        stats["act_latency_ms"] = _percentiles(act_latencies)

    # The chirp anchor carries the PC output path estimate; when the DAC stamp was available
    # the residual is small, otherwise the full pre-play stamp uncertainty applies.
    dac_ok = all(m.t_dac_wall_ms is not None for m in chirps)
    systematic = 15.0 if dac_ok else 60.0

    assertions = {
        "clock_map_anchored": True,
        # A missed/degenerate end chirp must FAIL loudly, never silently drop the drift fit.
        "clock_map_drift_corrected": clock_map.anchors_used >= 2 if len(chirps) >= 2 else True,
        "all_dispatched_cues_matched": len(matched) == len(cues) and len(cues) > 0,
        "act_cues_within_budget": bool(act_latencies)
        and max(act_latencies) + systematic <= act_budget_ms,
    }
    if expected_dispatches is not None:
        # Burst mode: every injected cue must have actually been dispatched by the scheduler.
        assertions["all_burst_cues_dispatched"] = len(cues) == expected_dispatches
    return AudibleLatencyReport(
        recording=str(recording_path),
        recording_samplerate=rec_sr,
        chirps=chirp_detail,
        clock_map=clock_map.to_dict(),
        cues=cues,
        stats=stats,
        assertions=assertions,
        systematic_uncertainty_ms=systematic,
    )


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 1),
        "p95": round(ordered[max(0, int(round(0.95 * (len(ordered) - 1))))], 1),
        "max": round(ordered[-1], 1),
        "min": round(ordered[0], 1),
    }


def render_markdown(report: AudibleLatencyReport) -> str:
    lines = [
        "# Audible-latency report (#381 / #511 Part D)",
        "",
        f"Recording: `{report.recording}` @ {report.recording_samplerate} Hz",
        f"Systematic uncertainty: +/-{report.systematic_uncertainty_ms:.0f} ms "
        "(PC output-path anchor)",
        "",
        "| seq | clip | urgency | register | dispatch->audible ms | rtt ms | js ms | score |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in report.cues:
        lat = f"{c.audible_latency_ms:.1f}" if c.audible_latency_ms is not None else "UNMATCHED"
        rtt = f"{c.rtt_ms:.1f}" if c.rtt_ms is not None else "-"
        js = f"{c.js_play_ms:.1f}" if c.js_play_ms is not None else "-"
        score = f"{c.match_score:.2f}" if c.match_score is not None else "-"
        lines.append(
            f"| {c.seq} | {c.clip_id} | {c.urgency} | {c.register} | {lat} | {rtt} | {js} "
            f"| {score} |"
        )
    lines.append("")
    lines.append(f"Stats: `{json.dumps(report.stats)}`")
    lines.append(f"Assertions: `{json.dumps(report.assertions)}`")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# Run orchestration (scrcpy capture + WS cue injection + HTTP scraping)
# --------------------------------------------------------------------------------------------


def filter_dispatches_to_window(
    dispatches: list[dict[str, Any]],
    chirps: list[ChirpMark],
    *,
    margin_ms: float = 250.0,
) -> list[dict[str, Any]]:
    """Keep only dispatches whose stamp lies inside this run's chirp-bounded window."""
    if not chirps:
        return dispatches
    start = min(c.anchor_wall_ms() for c in chirps) - margin_ms
    end = max(c.anchor_wall_ms() for c in chirps) + margin_ms
    kept: list[dict[str, Any]] = []
    for d in dispatches:
        t = d.get("t_wall_ms")
        if isinstance(t, int | float) and start <= float(t) <= end:
            kept.append(d)
    dropped = len(dispatches) - len(kept)
    if dropped:
        _log.info(
            "ignoring %d dispatch(es) outside this capture window (earlier sidecar activity)",
            dropped,
        )
    return kept


def _http_get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    # Parse the actual host — a prefix check would accept e.g. 127.0.0.1.evil.example
    # (PR #519 adversarial review).
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"refusing non-loopback sidecar URL: {url}")
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback-only
        return json.loads(resp.read().decode("utf-8"))


async def _ws_session(
    url: str,
    *,
    burst: int,
    burst_interval_s: float,
    observe_seconds: float,
    collected: list[dict[str, Any]],
) -> None:
    """Subscribe to ``coaching.voice``; optionally inject ``voice.demo`` burst cues."""
    import websockets

    async with websockets.connect(url) as ws:
        await ws.send(
            json.dumps(
                {"v": 1, "type": "hello", "client": "audible-latency", "client_class": "voice"}
            )
        )
        await ws.send(json.dumps({"v": 1, "type": "state.subscribe", "topics": ["coaching.voice"]}))

        async def _collect(deadline: float) -> None:
            while time.monotonic() < deadline:
                budget = max(0.05, deadline - time.monotonic())
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=budget)
                except TimeoutError:
                    return
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if frame.get("topic") == "coaching.voice":
                    payload = frame.get("payload")
                    if isinstance(payload, dict):
                        payload["t_client_recv_ms"] = time.time() * 1000.0
                        collected.append(payload)

        if burst > 0:
            for i in range(burst):
                cue = dict(_BURST_CUES[i % len(_BURST_CUES)])
                cue.update({"v": 1, "type": "voice.demo"})
                # Vary the corner per round so the scheduler's dedup window never eats a
                # repeat (dedup keys on kind:corner:register).
                if "corner" in cue and cue["corner"] is not None:
                    cue["corner"] = (int(cue["corner"]) + 2 * (i // len(_BURST_CUES))) % 20
                await ws.send(json.dumps(cue))
                await _collect(time.monotonic() + burst_interval_s)
        else:
            await _collect(time.monotonic() + observe_seconds)


async def capture_browser_microphone(
    url: str, path: Path, *, max_seconds: float, ready: asyncio.Event, stop: asyncio.Event
) -> dict[str, Any]:
    """Receive only explicitly subscribed, continuous local PCM; never fabricate gap silence."""
    import websockets

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("browser microphone recording requires a loopback ws URL")
    capture = MicWavCapture(path, max_seconds=max_seconds)
    try:
        async with websockets.connect(url, max_queue=8, max_size=16384) as ws:
            await ws.send(
                json.dumps(
                    {
                        "v": 1,
                        "type": "hello",
                        "client": "audible-microphone",
                        "client_class": "voice",
                    }
                )
            )
            await ws.send(json.dumps({"v": 1, "type": MIC_SUBSCRIBE, "enabled": True}))
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except TimeoutError:
                    if ready.is_set() and not stop.is_set():
                        raise ValueError("browser microphone stream stalled") from None
                    continue
                frame = json.loads(raw)
                if frame.get("type") == MIC_CHUNK:
                    capture.accept(frame)
                    ready.set()
                elif frame.get("type") == MIC_END:
                    raise ValueError("browser microphone stopped before proof capture completed")
                elif frame.get("type") == "error":
                    raise ValueError(
                        "browser microphone protocol error: " + str(frame.get("error"))
                    )
            await ws.send(json.dumps({"v": 1, "type": MIC_SUBSCRIBE, "enabled": False}))
        if not capture.samples:
            raise ValueError("browser microphone recording is empty")
        return {
            "backend": "browser",
            "continuous": True,
            "sample_rate": capture.stream.sample_rate,
            "samples": capture.samples,
            "capture_id": capture.stream.capture_id,
        }
    finally:
        capture.close()


async def _browser_probe(
    args: argparse.Namespace, path: Path, total_s: float
) -> tuple[list[ChirpMark], list[dict[str, Any]], dict[str, Any]]:
    ready, stop = asyncio.Event(), asyncio.Event()
    reader = asyncio.create_task(
        capture_browser_microphone(
            args.sidecar_url, path, max_seconds=total_s + 10, ready=ready, stop=stop
        )
    )
    ready_task = asyncio.create_task(ready.wait())
    work: asyncio.Task[Any] | None = None

    async def probe() -> tuple[list[ChirpMark], list[dict[str, Any]]]:
        await asyncio.sleep(args.lead_in)
        kwargs = {
            "device": args.chirp_device,
            "host_api": args.chirp_host_api,
            "channel_map": args.chirp_channel_map,
            "f0_hz": getattr(args, "chirp_f0_hz", CHIRP_F0_HZ),
            "f1_hz": getattr(args, "chirp_f1_hz", CHIRP_F1_HZ),
        }
        chirps = [await asyncio.to_thread(play_chirp, "start", **kwargs)]
        collected: list[dict[str, Any]] = []
        await _ws_session(
            args.sidecar_url,
            burst=args.burst,
            burst_interval_s=args.burst_interval,
            observe_seconds=float(args.observe_seconds),
            collected=collected,
        )
        chirps.append(await asyncio.to_thread(play_chirp, "end", **kwargs))
        await asyncio.sleep(args.tail)
        return chirps, collected

    try:
        done, _ = await asyncio.wait(
            {reader, ready_task}, timeout=30, return_when=asyncio.FIRST_COMPLETED
        )
        if reader in done:
            reader.result()
            raise ValueError("microphone capture ended before readiness")
        if not ready.is_set():
            raise ValueError("tap START MIC on /tablet/voice; no PCM arrived within 30s")
        work = asyncio.create_task(probe())
        done, _ = await asyncio.wait({reader, work}, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            reader.result()
            raise ValueError("microphone capture ended during the probe")
        chirps, collected = work.result()
        stop.set()
        receipt = await reader
        return chirps, collected, receipt
    finally:
        stop.set()
        for task in (reader, ready_task, work):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (reader, ready_task, work) if t is not None), return_exceptions=True
        )


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(
            "proof output directory is not empty; preserve it and use a fresh run"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    recording_path = out_dir / "room_capture.wav"

    cue_phase_s = (
        args.burst * args.burst_interval if args.burst > 0 else float(args.observe_seconds)
    )
    total_s = int(args.lead_in + cue_phase_s + args.tail + 2 * CHIRP_DURATION_S) + 3

    capture_backend = getattr(args, "capture", "browser")
    if capture_backend == "browser":
        if total_s + 10 > MAX_CAPTURE_SECONDS:
            raise ValueError("browser capture exceeds 180s; use a shorter bounded probe")
        try:
            chirps, collected, receipt = asyncio.run(_browser_probe(args, recording_path, total_s))
        except Exception as exc:
            (out_dir / "capture.json").write_text(
                json.dumps(
                    {"backend": "browser", "continuous": False, "error": str(exc)}, indent=2
                ),
                encoding="utf-8",
            )
            raise
        (out_dir / "capture.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    else:
        chirps, collected = _capture_scrcpy(args, out_dir, recording_path, total_s)

    http_base = args.http_url.rstrip("/")
    dispatches = _http_get_json(f"{http_base}/voice/dispatches").get("dispatches", [])
    echoes = _http_get_json(f"{http_base}/voice/echoes").get("echoes", [])
    dispatches = filter_dispatches_to_window(dispatches, chirps)
    (out_dir / "dispatches.json").write_text(json.dumps(dispatches, indent=2), encoding="utf-8")
    (out_dir / "echoes.json").write_text(json.dumps(echoes, indent=2), encoding="utf-8")
    (out_dir / "chirps.json").write_text(
        json.dumps([asdict(c) for c in chirps], indent=2), encoding="utf-8"
    )
    (out_dir / "ws_frames.json").write_text(json.dumps(collected, indent=2), encoding="utf-8")
    try:
        report = analyze(
            recording_path=recording_path,
            bank_dir=Path(args.bank),
            dispatches=dispatches,
            chirps=chirps,
            echoes=echoes,
            act_budget_ms=args.act_budget_ms,
            expected_dispatches=args.burst if args.burst > 0 else None,
        )
    except ValueError as exc:
        (out_dir / "analysis_error.json").write_text(
            json.dumps({"verified": False, "error": str(exc)}, indent=2), encoding="utf-8"
        )
        _log.error("acoustic proof failed: %s; capture preserved in %s", exc, out_dir)
        return 2
    if capture_backend == "browser":
        report.assertions["browser_pcm_continuous"] = receipt["continuous"]
    if getattr(args, "require_native_wired", False):
        critical = [d for d in dispatches if d.get("register") == "critical"]
        by_seq = {e.get("seq"): e for e in echoes}
        report.assertions["native_wired_critical_observed"] = bool(critical) and all(
            by_seq.get(d["seq"], {}).get("playback_backend") == "fully"
            and by_seq.get(d["seq"], {}).get("output_route") == "wired"
            and isinstance(by_seq.get(d["seq"], {}).get("t_play_ms"), (int, float))
            for d in critical
        )
    return _emit_report(report, out_dir)


def _capture_scrcpy(
    args: argparse.Namespace, out_dir: Path, recording_path: Path, total_s: int
) -> tuple[list[ChirpMark], list[dict[str, Any]]]:
    """Legacy opt-in capture backend for devices on which scrcpy is stable."""
    scrcpy_cmd = [
        args.scrcpy,
        "--no-video",
        "--no-playback",
        f"--audio-source={args.audio_source}",
        "--audio-codec=raw",
        f"--record={recording_path}",
        "--record-format=wav",
        f"--time-limit={total_s}",
    ]
    _log.info("starting capture: %s", " ".join(scrcpy_cmd))
    scrcpy_log = (out_dir / "scrcpy.log").open("w", encoding="utf-8")
    proc = None
    try:
        proc = subprocess.Popen(scrcpy_cmd, stdout=scrcpy_log, stderr=subprocess.STDOUT)
        time.sleep(args.lead_in)  # let the capture stream settle before the first anchor
        if proc.poll() is not None:
            _log.error("scrcpy exited early (rc=%s) — see %s", proc.returncode, scrcpy_log.name)
            raise RuntimeError("scrcpy exited before recording")

        chirps = [
            play_chirp(
                "start",
                device=args.chirp_device,
                host_api=args.chirp_host_api,
                channel_map=args.chirp_channel_map,
                f0_hz=getattr(args, "chirp_f0_hz", CHIRP_F0_HZ),
                f1_hz=getattr(args, "chirp_f1_hz", CHIRP_F1_HZ),
            )
        ]

        collected: list[dict[str, Any]] = []
        asyncio.run(
            _ws_session(
                args.sidecar_url,
                burst=args.burst,
                burst_interval_s=args.burst_interval,
                observe_seconds=float(args.observe_seconds),
                collected=collected,
            )
        )

        chirps.append(
            play_chirp(
                "end",
                device=args.chirp_device,
                host_api=args.chirp_host_api,
                channel_map=args.chirp_channel_map,
                f0_hz=getattr(args, "chirp_f0_hz", CHIRP_F0_HZ),
                f1_hz=getattr(args, "chirp_f1_hz", CHIRP_F1_HZ),
            )
        )
        _log.info(
            "cue phase complete (%d coaching.voice frames); waiting for capture to close",
            len(collected),
        )
        try:
            proc.wait(timeout=total_s + 30)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
    finally:
        if proc is not None and proc.poll() is None:
            # Failure path: wait after terminate (kill on timeout) so a dying scrcpy cannot
            # keep writing the WAV or hold the log handle into the next run (PR #519 review).
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
        scrcpy_log.close()

    return chirps, collected


def analyze_cmd(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dispatches = json.loads(Path(args.dispatches).read_text(encoding="utf-8"))
    if isinstance(dispatches, dict):
        dispatches = dispatches.get("dispatches", [])
    chirps_raw = json.loads(Path(args.chirps).read_text(encoding="utf-8"))
    chirps = [ChirpMark(**c) for c in chirps_raw]
    echoes: list[dict[str, Any]] = []
    if args.echoes:
        echoes = json.loads(Path(args.echoes).read_text(encoding="utf-8"))
        if isinstance(echoes, dict):
            echoes = echoes.get("echoes", [])
    report = analyze(
        recording_path=Path(args.recording),
        bank_dir=Path(args.bank),
        dispatches=dispatches,
        chirps=chirps,
        echoes=echoes,
        act_budget_ms=args.act_budget_ms,
    )
    return _emit_report(report, out_dir)


def _emit_report(report: AudibleLatencyReport, out_dir: Path) -> int:
    (out_dir / "audible_latency.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    md = render_markdown(report)
    (out_dir / "audible_latency.md").write_text(md, encoding="utf-8")
    print(md)
    ok = all(report.assertions.values())
    print(f"assertions: {'PASS' if ok else 'FAIL'} -> {json.dumps(report.assertions)}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bank", required=True, help="baked voice bank dir (clip templates)")
    common.add_argument("--out-dir", required=True, help="artifact output directory")
    common.add_argument("--act-budget-ms", type=float, default=DEFAULT_ACT_BUDGET_MS)

    p_run = sub.add_parser("run", parents=[common], help="capture + inject + analyze")
    p_run.add_argument("--sidecar-url", default="ws://127.0.0.1:8765")
    p_run.add_argument("--http-url", default="http://127.0.0.1:8765")
    p_run.add_argument("--burst", type=int, default=0, help="inject N voice.demo cues")
    p_run.add_argument("--burst-interval", type=float, default=4.0)
    p_run.add_argument(
        "--observe-seconds", type=float, default=60.0, help="passive window (drive mode)"
    )
    p_run.add_argument("--lead-in", type=float, default=3.0)
    p_run.add_argument("--tail", type=float, default=4.0)
    p_run.add_argument("--scrcpy", default="scrcpy", help="scrcpy executable path")
    p_run.add_argument(
        "--capture",
        choices=["browser", "scrcpy"],
        default="browser",
        help="microphone transport (default: opt-in browser AudioWorklet over WS)",
    )
    p_run.add_argument(
        "--require-native-wired",
        action="store_true",
        help="fail unless critical dispatch echoes used Fully native + wired earpiece",
    )
    p_run.add_argument(
        "--audio-source",
        default="mic-unprocessed",
        choices=["mic", "mic-unprocessed", "mic-camcorder", "mic-voice-recognition"],
    )
    p_run.add_argument("--chirp-device", default=None, help="PC output device name substring")
    p_run.add_argument("--chirp-host-api", default=None)
    p_run.add_argument("--chirp-f0-hz", type=float, default=CHIRP_F0_HZ)
    p_run.add_argument("--chirp-f1-hz", type=float, default=CHIRP_F1_HZ)
    p_run.add_argument(
        "--chirp-channel-map", default=None, help="One-based output channels, e.g. 5,6"
    )
    p_run.set_defaults(func=run)

    p_an = sub.add_parser("analyze", parents=[common], help="analyze an existing capture")
    p_an.add_argument("--recording", required=True)
    p_an.add_argument("--dispatches", required=True)
    p_an.add_argument("--chirps", required=True)
    p_an.add_argument("--echoes", default=None)
    p_an.set_defaults(func=analyze_cmd)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
