"""End-to-end audible-latency harness — how timely is the coach IN THE ROOM (issue #381).

The CI timing report (:mod:`timing_report`) proves emit→dispatch with an injected clock; this
harness measures the half nothing else can: **dispatch → acoustic onset at a real microphone**,
covering the WS hop to a remote audio endpoint (the tablet page, issue #511 Part D), the
endpoint's audio stack, and the speaker→mic path.

Method (council-reviewed, 2026-07-11):

* **Room capture** — the Android tablet's microphone is recorded ON THE PC over USB via
  ``scrcpy --no-video --audio-source=mic* --audio-codec=raw --record=<wav>``. No mic hardware
  on the PC is needed.
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
import statistics
import subprocess
import time
import urllib.request
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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


def make_chirp(samplerate: int, np: Any) -> Any:
    """Log-frequency chirp 5→15 kHz — cuts through engine roar (low/mid dominant)."""
    n = int(CHIRP_DURATION_S * samplerate)
    t = np.arange(n, dtype=np.float64) / samplerate
    k = (CHIRP_F1_HZ / CHIRP_F0_HZ) ** (1.0 / CHIRP_DURATION_S)
    phase = 2.0 * np.pi * CHIRP_F0_HZ * (k**t - 1.0) / np.log(k)
    sig = np.sin(phase)
    # 10 ms raised-cosine edges: no click transient to smear the matched-filter peak.
    edge = max(1, int(0.010 * samplerate))
    ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(edge) / edge))
    sig[:edge] *= ramp
    sig[-edge:] *= ramp[::-1]
    return (CHIRP_AMPLITUDE * sig).astype(np.float32)


def play_chirp(label: str, *, device: str | None, host_api: str | None) -> ChirpMark:
    """Play the sync chirp on the PC output and wall-stamp its first sample at the DAC.

    Uses the PortAudio callback's ``outputBufferDacTime`` to map the first callback buffer to
    the wall clock — collapsing most of the "when did the speaker actually move" uncertainty
    that a naive pre-play stamp carries.
    """
    import numpy as np
    import sounddevice as sd

    device_index: int | None = None
    if device:
        from tools.ai_sidecar.voice.playback import resolve_output_device

        device_index = resolve_output_device(
            device,
            host_api,
            devices=list(sd.query_devices()),
            host_apis=list(sd.query_hostapis()),
        )
    samplerate = 48_000
    chirp = make_chirp(samplerate, np)
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
        outdata[: len(chunk), 0] = chunk
        if len(chunk) < frames:
            outdata[len(chunk) :, 0] = 0.0
            done.set()
            raise sd.CallbackStop
        state["pos"] = pos + frames

    t_wall_ms = time.time() * 1000.0
    stream = sd.OutputStream(
        samplerate=samplerate,
        channels=1,
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


def find_onset(
    recording: Any,
    template: Any,
    np: Any,
    *,
    start: int = 0,
    end: int | None = None,
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
    peak_idx = int(np.argmax(scores))
    peak = float(scores[peak_idx])
    median = float(np.median(scores))
    prominence = peak / max(median, 1e-9)
    if peak < MATCH_MIN_SCORE or prominence < MATCH_MIN_PROMINENCE:
        return None, peak, prominence
    return start + peak_idx, peak, prominence


@dataclass
class ClockMap:
    """Linear map recording-sample → PC wall ms, anchored on one or two chirps."""

    anchor_sample: int
    anchor_wall_ms: float
    ms_per_sample: float

    def wall_ms(self, sample: int) -> float:
        return self.anchor_wall_ms + (sample - self.anchor_sample) * self.ms_per_sample

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_clock_map(
    recording: Any,
    samplerate: int,
    chirps: list[ChirpMark],
    np: Any,
) -> tuple[ClockMap, list[dict[str, Any]]]:
    """Locate each chirp in the recording and fit the sample↔wall-clock map.

    With two located chirps the slope corrects capture-clock drift; with one, the nominal
    samplerate is trusted. Raises ``ValueError`` when no chirp is found — without an anchor
    every downstream number would be fiction.
    """
    template = make_chirp(samplerate, np)
    third = len(recording) // 3
    found: list[tuple[ChirpMark, int]] = []
    detail: list[dict[str, Any]] = []
    for mark in chirps:
        if mark.label == "start":
            onset, score, prom = find_onset(recording, template, np, start=0, end=2 * third)
        else:
            onset, score, prom = find_onset(recording, template, np, start=third)
        detail.append(
            {
                "label": mark.label,
                "onset_sample": onset,
                "score": round(score, 4),
                "prominence": round(prom, 2),
                "anchor_wall_ms": mark.anchor_wall_ms(),
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
                return ClockMap(s0, m0.anchor_wall_ms(), slope), detail
            _log.warning(
                "chirp-pair slope %.6f ms/sample deviates >5%% from nominal %.6f — "
                "falling back to single-anchor map",
                slope,
                nominal,
            )
    mark, sample = found[0]
    return ClockMap(sample, mark.anchor_wall_ms(), nominal), detail


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
) -> AudibleLatencyReport:
    """Locate every dispatched clip in the room recording and build the timeliness report."""
    import numpy as np

    from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest
    from tools.ai_sidecar.voice.playback import Bank

    recording, rec_sr = _load_wav_mono(recording_path, np)
    manifest = Manifest.load(bank_dir / MANIFEST_FILENAME)
    bank = Bank.from_manifest(manifest, bank_dir)

    clock_map, chirp_detail = build_clock_map(recording, rec_sr, chirps, np)
    echo_by_seq = {e.get("seq"): e for e in (echoes or [])}

    cues: list[CueResult] = []
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
        # uncertainty without letting a pre-dispatch sound masquerade as the cue.
        start_wall = t_dispatch - 100.0
        start_sample = clock_map.anchor_sample + int(
            (start_wall - clock_map.anchor_wall_ms) / clock_map.ms_per_sample
        )
        end_sample = start_sample + int((SEARCH_WINDOW_MS + 100.0) / clock_map.ms_per_sample)
        onset, score, prom = find_onset(
            recording, template, np, start=max(0, start_sample), end=max(0, end_sample)
        )
        cue.match_score = round(score, 4)
        cue.match_prominence = round(prom, 2)
        if onset is not None:
            cue.matched = True
            cue.onset_wall_ms = clock_map.wall_ms(onset)
            cue.audible_latency_ms = cue.onset_wall_ms - t_dispatch
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
        "all_dispatched_cues_matched": len(matched) == len(cues) and len(cues) > 0,
        "act_cues_within_budget": bool(act_latencies)
        and max(act_latencies) + systematic <= act_budget_ms,
    }
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
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
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


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    recording_path = out_dir / "room_capture.wav"

    cue_phase_s = (
        args.burst * args.burst_interval if args.burst > 0 else float(args.observe_seconds)
    )
    total_s = int(args.lead_in + cue_phase_s + args.tail + 2 * CHIRP_DURATION_S) + 3

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
    proc = subprocess.Popen(scrcpy_cmd, stdout=scrcpy_log, stderr=subprocess.STDOUT)
    try:
        time.sleep(args.lead_in)  # let the capture stream settle before the first anchor
        if proc.poll() is not None:
            _log.error("scrcpy exited early (rc=%s) — see %s", proc.returncode, scrcpy_log.name)
            return 2

        chirps = [play_chirp("start", device=args.chirp_device, host_api=args.chirp_host_api)]

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

        chirps.append(play_chirp("end", device=args.chirp_device, host_api=args.chirp_host_api))
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
        if proc.poll() is None:
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

    http_base = args.http_url.rstrip("/")
    dispatches = _http_get_json(f"{http_base}/voice/dispatches").get("dispatches", [])
    echoes = _http_get_json(f"{http_base}/voice/echoes").get("echoes", [])
    # The ring buffers span the whole sidecar process, not this run. Keep only cues
    # dispatched between the two sync chirps — anything earlier/later is outside the
    # recording and would be reported UNMATCHED, failing a perfectly good run (PR #519
    # review). The chirps bound the capture by construction.
    dispatches = filter_dispatches_to_window(dispatches, chirps)
    (out_dir / "dispatches.json").write_text(json.dumps(dispatches, indent=2), encoding="utf-8")
    (out_dir / "echoes.json").write_text(json.dumps(echoes, indent=2), encoding="utf-8")
    (out_dir / "chirps.json").write_text(
        json.dumps([asdict(c) for c in chirps], indent=2), encoding="utf-8"
    )
    (out_dir / "ws_frames.json").write_text(json.dumps(collected, indent=2), encoding="utf-8")

    report = analyze(
        recording_path=recording_path,
        bank_dir=Path(args.bank),
        dispatches=dispatches,
        chirps=chirps,
        echoes=echoes,
        act_budget_ms=args.act_budget_ms,
    )
    return _emit_report(report, out_dir)


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
        "--audio-source",
        default="mic-unprocessed",
        choices=["mic", "mic-unprocessed", "mic-camcorder", "mic-voice-recognition"],
    )
    p_run.add_argument("--chirp-device", default=None, help="PC output device name substring")
    p_run.add_argument("--chirp-host-api", default=None)
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
