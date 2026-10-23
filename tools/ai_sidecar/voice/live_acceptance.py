"""Owner-run Windows live acoustic capture, with a hardware-free analyze subcommand.

No rig/app launch, settings/profile/attribution writes, demo cues, or synthetic pass.
Capture emits two calibration chirps on the explicitly selected output, records microphone
and (optionally) separate WASAPI loopback, and passively records the local sidecar stream.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import math
import os
import threading
import time
import urllib.request
import uuid
import wave
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from tools.ai_sidecar.voice import audible_latency as al
from tools.ai_sidecar.voice.manifest import Manifest
from tools.ai_sidecar.voice.playback import Bank
from tools.ai_sidecar.voice.shadow_replay import cue_timing_class

BASE_CLOCK_UNCERTAINTY_MS = 15
# A room microphone hears the chirp through reverberation, which caps its normalized
# correlation (run 02 of #815: 0.19-0.21 with 30x prominence). Acoustic anchors are therefore
# searched inside the chirp band and accepted at a calibrated detection level; they qualify a
# timebase only through microphone_clock_evidence's independent callback-clock agreement.
ACOUSTIC_CHIRP_MIN_SCORE = 0.10
ACOUSTIC_CHIRP_MIN_PROMINENCE = 10.0
# Reverb-aware phrase completeness (#815 runs 03-05; council-reviewed 2026-10-23). A room
# microphone hears each clip through the speaker/cabin response, so the dry 40 ms block rule
# (kept as a diagnostic) fails on quiet blocks after loud syllables even when the digital mix is
# complete. Each phrase is instead split into equal-speech-energy segments; every segment's own
# new speech, through a room response estimated from the run's OTHER phrases, must stand out from
# a local same-recording null after the predicted echo of earlier speech is subtracted.
COMPLETENESS_SEGMENTS = 6
COMPLETENESS_MIN_Z = 6.0
COMPLETENESS_NULL_SAMPLES = 300
COMPLETENESS_NULL_RADIUS_S = 60.0
COMPLETENESS_MIN_NULL_MATERIAL_S = 10.0
COMPLETENESS_MIN_OTHER_PHRASES = 5
ROOM_RESPONSE_PRE_S = 0.010
ROOM_RESPONSE_TAIL_S = 0.300
SEGMENT_TAIL_S = 0.050
# Segment positions are fixed by the located onset and the room response (which absorbs any
# systematic delay). A wider search would let an inverted copy of never-played speech, left by
# subtracting its predicted echo, align positively at a shifted lag.
SEGMENT_SLACK_SAMPLES = 2
# The matched-filter onset ranks |correlation|, so in a reverberant room it can lock onto an
# inverted lobe a half pitch period away (run 05 of #815: 5/19 phrases, room-model z near -21).
# Each phrase is re-aligned once, by a signed search against its own leave-one-out prediction,
# and the room-model null searches the same width.
PHRASE_ALIGNMENT_SEARCH_S = 0.010
_LOOPBACK_WARNINGS_LOCK = threading.Lock()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def monotonic_clock_info():
    info = time.get_clock_info("monotonic")
    return dict(
        implementation=info.implementation,
        monotonic=info.monotonic,
        adjustable=info.adjustable,
        resolution=info.resolution,
    )


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2, allow_nan=False)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def exact_device(devices, apis, name, host, direction):
    candidates = [
        i
        for i, device in enumerate(devices)
        if device["name"] == name
        and apis[device["hostapi"]]["name"] == host
        and device[f"max_{direction}_channels"] > 0
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"expected one exact {direction} endpoint, found {len(candidates)}: {name!r}"
        )
    return candidates[0]


def validate_config(config):
    from tools.ai_sidecar.voice.config import VoiceConfig

    for key in (
        "bank_dir",
        "reference_archive",
        "attribution_ledger",
        "car_id",
        "track_id",
        "microphone",
        "output_device",
        "output_host_api",
        "instrument_tap",
    ):
        if not config.get(key):
            raise ValueError(f"missing config: {key}")
    for key in ("sidecar_url", "http_url"):
        parsed = urlparse(config[key])
        if parsed.scheme != ("ws" if key == "sidecar_url" else "http"):
            raise ValueError(f"unexpected loopback URL scheme: {key}")
        if parsed.hostname not in ("127.0.0.1", "::1") or parsed.username or parsed.password:
            raise ValueError(f"only explicit untokened loopback URLs supported: {key}")
        if parsed.query or parsed.fragment:
            raise ValueError(f"URL must not carry credentials/query/fragment: {key}")
    if not finite(config["seconds"]) or not 5 <= config["seconds"] <= 600:
        raise ValueError("seconds must be finite in [5,600]")
    if not finite(config["track_length_m"]) or config["track_length_m"] <= 0:
        raise ValueError("track_length_m must be measured and positive")
    channel_map = VoiceConfig(channel_map=config.get("output_channel_map")).channel_map
    config["output_channel_map"] = list(channel_map) if channel_map is not None else None
    for key, default, low, high in (
        ("reaction_ms", 1200, 0, 10000),
        ("minimum_brake_coverage", 0.8, 0, 1),
        ("minimum_ticks", 100, 1, 1000000),
        ("minimum_brake_events", 1, 1, 1000),
        ("minimum_cues", 1, 1, 1000),
    ):
        value = config.get(key, default)
        if not finite(value) or not low <= value <= high:
            raise ValueError(f"invalid acceptance threshold: {key}")
    return config


@contextmanager
def attribution_path(path):
    key = "AC_COPILOT_LAP_ATTRIBUTIONS"
    previous = os.environ.get(key)
    os.environ[key] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def immutable_inputs(config):
    manifest_path = Path(config["bank_dir"]) / "manifest.json"
    manifest = Manifest.load(manifest_path)
    validation = manifest.validate(config["bank_dir"])
    if not validation.ok:
        raise ValueError(f"bank invalid: {validation.problems}")
    paths = [manifest_path, Path(config["reference_archive"]), Path(config["attribution_ledger"])]
    paths += [Path(config["bank_dir"]) / entry.file for entry in manifest.clips.values()]
    paths += [Path(path) for path in config.get("protected_files", [])]
    hashes = {str(path.resolve()): sha(path) for path in paths}
    from tools.lap_qualification import (
        archive_identity,
        qualify_archive,
        resolve_archive_provenance,
    )

    raw = json.loads(Path(config["reference_archive"]).read_bytes())
    with attribution_path(config["attribution_ledger"]):
        reference = resolve_archive_provenance(raw, source_path=config["reference_archive"])
        result = qualify_archive(
            reference,
            use="live_reference",
            expected_combo=(config["car_id"], config["track_id"], config.get("layout")),
        )
    if not result.allowed:
        raise ValueError(f"reference not allowed: {result.reasons}")
    return hashes, {**asdict(result), "identity": archive_identity(reference)}


def health(config):
    with urllib.request.urlopen(config["http_url"].rstrip("/") + "/health", timeout=3) as response:
        data = json.load(response)
    # Deliberately exclude arbitrary environment/config data.
    return {key: data.get(key) for key in ("voice", "observer", "coach_v2", "status")}


def verify_owner(pid):
    from tools.ac_harness.rig_lock import default_rig_session_lock_path, read_rig_session_owner

    owner = read_rig_session_owner(default_rig_session_lock_path())
    if not owner or owner.get("pid") != pid:
        raise RuntimeError(f"rig owner mismatch: expected {pid}; found {owner}")
    return owner


def sidecar_process(config):
    """Read-only listener PID/start-time binding; never inspect command lines or tokens."""
    import psutil

    with Path(config["instrument_tap"]).open(encoding="utf-8") as file:
        start = json.loads(file.readline())
    if start.get("kind") != "tap_start":
        raise ValueError("instrument tap does not begin with process identity")
    process = psutil.Process(start["pid"])
    port = urlparse(config["sidecar_url"]).port
    if not any(
        connection.status == psutil.CONN_LISTEN and connection.laddr.port == port
        for connection in process.net_connections(kind="tcp")
    ):
        raise ValueError("instrumented sidecar PID does not own the selected listening port")
    return dict(
        pid=process.pid,
        create_time=process.create_time(),
        port=port,
        tap_run_id=start["tap_run_id"],
    )


class Microphone:
    def __init__(self, spec, seconds):
        import numpy as np
        import sounddevice as sd

        self.np = np
        self.spec = spec
        devices, apis = list(sd.query_devices()), list(sd.query_hostapis())
        index = exact_device(devices, apis, spec["name"], spec["host_api"], "input")
        channels, rate = int(spec["channels"]), int(spec["samplerate"])
        sd.check_input_settings(device=index, channels=channels, samplerate=rate, dtype="float32")
        self.data = np.zeros((int((seconds + 20) * rate), channels), dtype=np.float32)
        self.pos = 0
        self.statuses = []
        self.stamps = []
        self.info = dict(
            kind="physical_microphone",
            name=spec["name"],
            host_api=spec["host_api"],
            resolved_index=index,
            samplerate=rate,
            channels=channels,
            portaudio_version=list(sd.get_portaudio_version()),
        )

        def callback(indata, frames, timing, status):
            if status:
                self.statuses.append(str(status))
            if self.pos + frames > len(self.data):
                self.statuses.append("capture_buffer_exhausted")
                raise sd.CallbackStop
            self.data[self.pos : self.pos + frames] = indata
            self.stamps.append(
                dict(
                    sample=self.pos,
                    frames=frames,
                    wall_ms=time.time_ns() / 1e6,
                    mono_ms=time.monotonic_ns() / 1e6,
                    adc_time=timing.inputBufferAdcTime,
                    stream_time=timing.currentTime,
                )
            )
            self.pos += frames

        self.stream = sd.InputStream(
            device=index, samplerate=rate, channels=channels, dtype="float32", callback=callback
        )

    def start(self):
        self.stream.start()

    def finish(self, path):
        self.stream.stop()
        self.stream.close()
        write_wav(path, self.data[: self.pos], self.info["samplerate"])
        return dict(
            **self.info,
            frames=self.pos,
            statuses=self.statuses,
            callback_stamps=self.stamps,
            file=str(path),
            sha256=sha(path),
        )


@contextmanager
def com_apartment(ole32=None):
    """COM initialization is thread-local; SoundCard's import initializes only its importer."""
    if ole32 is None:
        import ctypes

        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
    result = int(ole32.CoInitializeEx(None, 0)) & 0xFFFFFFFF  # COINIT_MULTITHREADED
    initialized = result in (0, 1)  # S_OK and S_FALSE both add a reference to balance.
    if not initialized and result != 0x80010106:  # RPC_E_CHANGED_MODE: existing apartment.
        raise RuntimeError(f"COM initialization failed: 0x{result:08x}")
    try:
        yield
    finally:
        if initialized:
            ole32.CoUninitialize()


@contextmanager
def soundcard_warning_capture(module, records):
    """Observe only the owned worker's backend warnings without global warning hooks.

    Python 3.13 catch_warnings changes process-wide filters/dispatch. A backend-local
    proxy preserves normal warning behavior in every thread, including error filters.
    Concurrent captures fail closed; cleanup never overwrites somebody else's proxy.
    """
    if not _LOOPBACK_WARNINGS_LOCK.acquire(blocking=False):
        raise RuntimeError("another loopback warning capture owns the backend")
    try:
        original = module.warnings
    except BaseException:
        _LOOPBACK_WARNINGS_LOCK.release()
        raise
    owner = threading.get_ident()

    class WarningProxy:
        def __getattr__(self, name):
            return getattr(original, name)

        def warn(self, message, category=None, stacklevel=1, source=None, **kwargs):
            if threading.get_ident() == owner:
                effective_category = (
                    type(message) if isinstance(message, Warning) else category or UserWarning
                )
                records.append(
                    dict(
                        message=str(message),
                        category=effective_category.__name__,
                        thread_id=owner,
                        wall_ms=time.time_ns() / 1e6,
                        mono_ms=time.monotonic_ns() / 1e6,
                    )
                )
            # Preserve the original callsite, including module-scoped warning filters.
            return original.warn(message, category, stacklevel + 1, source, **kwargs)

    proxy = WarningProxy()
    try:
        module.warnings = proxy
        yield
    finally:
        try:
            unchanged = getattr(module, "warnings", None) is proxy
            if unchanged:
                module.warnings = original
        finally:
            _LOOPBACK_WARNINGS_LOCK.release()
        if not unchanged:
            raise RuntimeError("loopback warning proxy replaced during capture")


class Loopback:
    """Separate digital-output evidence. Never called a microphone/acoustic measurement."""

    def __init__(self, spec):
        import soundcard as sc

        speakers = [
            speaker
            for speaker in sc.all_speakers()
            if speaker.name == spec["speaker_name"]
            and (not spec.get("speaker_id") or speaker.id == spec["speaker_id"])
        ]
        if len(speakers) != 1:
            raise ValueError(f"loopback speaker ambiguous/absent: {len(speakers)}")
        self.device = sc.get_microphone(speakers[0].id, include_loopback=True)
        if not self.device.isloopback:
            raise ValueError("selected source is not loopback")
        self.spec = spec
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.blocks = []
        self.error = None
        self.warning_records = []
        self.warning_capture_complete = False
        self.warning_module = importlib.import_module("soundcard.mediafoundation")
        self.info = dict(
            kind="wasapi_loopback",
            speaker_id=speakers[0].id,
            speaker_name=speakers[0].name,
            samplerate=spec["samplerate"],
        )
        self.thread = threading.Thread(target=self._record, name="acceptance-loopback", daemon=True)

    def _record(self):
        try:
            with soundcard_warning_capture(self.warning_module, self.warning_records):
                with com_apartment():
                    with self.device.recorder(
                        samplerate=self.spec["samplerate"], blocksize=1024
                    ) as recorder:
                        self.ready.set()
                        while not self.stop.is_set():
                            self.blocks.append(recorder.record(numframes=4096))
            self.warning_capture_complete = True
        except BaseException as exc:
            self.error = repr(exc)
            self.ready.set()

    def start(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise RuntimeError(f"loopback start failed: {self.error}")

    def finish(self, path):
        import numpy as np

        self.stop.set()
        self.thread.join(5)
        if self.thread.is_alive() or self.error or not self.blocks:
            raise RuntimeError(f"loopback incomplete: {self.error}")
        data = np.concatenate(self.blocks)
        write_wav(path, data, self.spec["samplerate"])
        return dict(
            **self.info,
            frames=len(data),
            channels=data.shape[1],
            statuses=[f"{row['category']}: {row['message']}" for row in self.warning_records],
            warnings=self.warning_records,
            warning_capture_complete=self.warning_capture_complete,
            file=str(path),
            sha256=sha(path),
        )


def write_wav(path, values, rate):
    import numpy as np

    with wave.open(str(path), "wb") as file:
        file.setnchannels(1 if values.ndim == 1 else values.shape[1])
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes((np.clip(values, -1, 1) * 32767).astype("<i2").tobytes())


def load_wav(path, channel):
    import numpy as np

    with wave.open(str(path), "rb") as file:
        if file.getsampwidth() != 2 or not 0 <= channel < file.getnchannels():
            raise ValueError("expected PCM16 and explicit valid channel")
        data = np.frombuffer(file.readframes(file.getnframes()), dtype="<i2").reshape(
            -1, file.getnchannels()
        )
        return data[:, channel].astype(np.float64) / 32768, file.getframerate()


async def record_wire(config, path, ready, stop):
    import websockets

    with path.open("x", encoding="utf-8") as file:
        async with websockets.connect(config["sidecar_url"], max_size=2**22) as ws:
            await ws.send(
                json.dumps(
                    dict(
                        v=1, type="hello", client="815-acoustic-acceptance", client_class="physical"
                    )
                )
            )
            await ws.send(
                json.dumps(
                    dict(
                        v=1,
                        type="state.subscribe",
                        topics=["session", "lap", "coaching.cue", "coaching.voice"],
                    )
                )
            )
            ready.set()
            session = None
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except TimeoutError:
                    continue
                wall, mono = time.time_ns() / 1e6, time.monotonic_ns() / 1e6
                frame = json.loads(raw)
                if frame.get("topic") == "session":
                    session = frame.get("payload")
                file.write(
                    json.dumps(
                        dict(wall_ms=wall, mono_ms=mono, session=session, frame=frame),
                        allow_nan=False,
                    )
                    + "\n"
                )
                file.flush()


def record(config, out, owner_pid):
    validate_config(config)
    out.mkdir(parents=True, exist_ok=False)
    capture = dict(
        schema=1,
        kind="windows_live",
        run_id=str(uuid.uuid4()),
        config=config,
        started_wall_ms=time.time_ns() / 1e6,
        started_mono_ms=time.monotonic_ns() / 1e6,
        monotonic_clock=monotonic_clock_info(),
        errors=[],
        capture_code_sha256=sha(__file__),
    )
    microphones = []
    loopback = None
    wire_stop, wire_ready = threading.Event(), threading.Event()
    wire_error = []
    thread = None
    try:
        capture["owner_before"] = verify_owner(owner_pid)
        capture["input_hashes_before"], capture["reference_qualification"] = immutable_inputs(
            config
        )
        capture["sidecar_before"] = sidecar_process(config)
        capture["health_before"] = health(config)
        import sounddevice as sd

        devices, apis = list(sd.query_devices()), list(sd.query_hostapis())
        exact_device(devices, apis, config["output_device"], config["output_host_api"], "output")
        microphone = Microphone(config["microphone"], config["seconds"])
        microphones.append(microphone)
        microphone.start()
        if config.get("loopback"):
            loopback = Loopback(config["loopback"])
            loopback.start()

        def wire_thread():
            try:
                asyncio.run(record_wire(config, out / "wire.jsonl", wire_ready, wire_stop))
            except BaseException as exc:
                wire_error.append(repr(exc))
                wire_ready.set()

        thread = threading.Thread(target=wire_thread, name="acceptance-wire", daemon=True)
        thread.start()
        if not wire_ready.wait(5) or wire_error:
            raise RuntimeError(f"wire capture failed: {wire_error}")
        time.sleep(1)
        chirps = [
            al.play_chirp(
                "start",
                device=config["output_device"],
                host_api=config["output_host_api"],
                channel_map=config.get("output_channel_map"),
            )
        ]
        deadline = time.monotonic() + config["seconds"]
        while time.monotonic() < deadline:
            verify_owner(owner_pid)
            if wire_error:
                raise RuntimeError(f"wire capture failed: {wire_error}")
            if not thread.is_alive():
                raise RuntimeError("wire capture exited before the observation window ended")
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        chirps.append(
            al.play_chirp(
                "end",
                device=config["output_device"],
                host_api=config["output_host_api"],
                channel_map=config.get("output_channel_map"),
            )
        )
        capture["chirps"] = [asdict(mark) for mark in chirps]
        time.sleep(1)
        capture["health_after"] = health(config)
        capture["sidecar_after"] = sidecar_process(config)
        capture["owner_after"] = verify_owner(owner_pid)
    except BaseException as exc:
        capture["errors"].append(repr(exc))
    finally:
        wire_stop.set()
        if thread:
            thread.join(5)
            if thread.is_alive():
                capture["errors"].append("wire thread did not stop")
        capture["errors"].extend(wire_error)
        for microphone in microphones:
            try:
                capture["microphone"] = microphone.finish(out / "microphone.wav")
            except BaseException as exc:
                capture["errors"].append(f"microphone close: {exc!r}")
        if loopback:
            try:
                capture["loopback"] = loopback.finish(out / "loopback.wav")
            except BaseException as exc:
                capture["errors"].append(f"loopback close: {exc!r}")
        before = capture.get("input_hashes_before", {})
        capture["input_hashes_after"] = {
            path: sha(path) if Path(path).is_file() else None for path in before
        }
        capture["finished_wall_ms"] = time.time_ns() / 1e6
        capture["finished_mono_ms"] = time.monotonic_ns() / 1e6
        capture["recording_complete"] = not capture["errors"]
        capture["capture_code_unchanged"] = sha(__file__) == capture["capture_code_sha256"]
        if (out / "wire.jsonl").exists():
            capture["wire_sha256"] = sha(out / "wire.jsonl")
        write_json(out / "capture.json", capture)
    return capture


def brake_events(ticks):
    """Same >.05 / >=3 samples / peak>=.35 pedal-run contract as track_reference.

    Requires a preceding pedal-off sample; a recording beginning mid-braking is censored.
    Event time is bracketed on the sidecar ingress monotonic clock, not invented simulator time.
    """
    events = []
    i = 1
    while i < len(ticks):
        previous, row = ticks[i - 1], ticks[i]
        p = row["frame"]["payload"]
        prior = previous["frame"]["payload"]
        if p["brake"] <= 0.05 or prior["brake"] > 0.05 or p["lap"] != prior["lap"]:
            i += 1
            continue
        j = i
        while (
            j < len(ticks)
            and ticks[j]["frame"]["payload"]["brake"] > 0.05
            and ticks[j]["frame"]["payload"]["lap"] == p["lap"]
        ):
            j += 1
        run = ticks[i:j]
        peak = max(r["frame"]["payload"]["brake"] for r in run)
        if len(run) >= 3 and peak >= 0.35:
            events.append(
                dict(
                    event_id=len(events),
                    lap=p["lap"],
                    spline=p["spline"],
                    end_spline=run[-1]["frame"]["payload"]["spline"],
                    onset_ms=row["mono_ms"],
                    earliest_ms=previous["mono_ms"],
                    peak=peak,
                    samples=len(run),
                    onset_tick_seq=row["frame"].get("seq"),
                )
            )
        i = max(i + 1, j)
    return events


def reference_brake_targets(config, expected_hashes):
    """Rebuild same-corner geometry from the immutable, currently eligible reference."""
    from tools.ai_sidecar.lap_dynamics import corner_signatures, lap_trace_from_archive
    from tools.ai_sidecar.track_reference import add_corpus_lap, build_references
    from tools.lap_qualification import qualify_archive, resolve_archive_provenance

    path = Path(config["reference_archive"]).resolve()
    ledger = Path(config["attribution_ledger"]).resolve()
    for source in (path, ledger):
        if expected_hashes.get(str(source)) != sha(source):
            raise ValueError("reference target input absent from immutable capture hashes")
    with attribution_path(ledger):
        raw = resolve_archive_provenance(json.loads(path.read_bytes()), source_path=path)
        qualification = qualify_archive(
            raw,
            use="live_reference",
            expected_combo=(config["car_id"], config["track_id"], config.get("layout")),
        )
    if not qualification.allowed:
        raise ValueError(f"reference target qualification failed: {qualification.reasons}")
    lap = lap_trace_from_archive(raw)
    refs = build_references(lap)
    add_corpus_lap(refs, lap)
    geometry = {s.index: s for s in corner_signatures(lap)}
    return {
        ref.index: dict(
            spline_lo=ref.spline_lo,
            spline_hi=ref.spline_hi,
            observer_marks=ref.brake_marks,
            # CoachRuntime builds PRIME anchors from these same geometry signatures.
            prime_brake_point=geometry[ref.index].brake_point_spline,
        )
        for ref in refs
        if ref.index in geometry
    }


def match_brake_target(advisory, payload, events, targets, track_m):
    """Match a unique measured run using corner geometry and its actual target mark."""
    result = dict(brake_match_count=0, brake_target_reason="corner_reference_unavailable")
    ref = targets.get(advisory.get("corner"))
    if ref is None:
        return result
    detail = advisory.get("detail") or {}
    prime = detail.get("coach") == "prime"
    mark = ref["prime_brake_point"] if prime else detail.get("brake_point_spline")
    if not finite(mark) or not 0 <= mark < 1:
        return {**result, "brake_target_reason": "target_mark_unavailable"}
    result.update(
        brake_target_spline=mark,
        brake_target_basis="reference_corner_geometry" if prime else "producer_explicit_mark",
        brake_target_reason="measured_event_missing_or_ambiguous",
    )
    matched = [
        event
        for event in events
        if event["lap"] == payload.get("lap")
        and event["spline"] <= ref["spline_hi"]
        and event["end_spline"] >= ref["spline_lo"]
        and abs((event["spline"] - mark + 0.5) % 1 - 0.5) * track_m <= 50
    ]
    result["brake_match_count"] = len(matched)
    if len(matched) == 1:
        result.update(
            brake_event_id=matched[0]["event_id"],
            brake_target_reason="unique_same_corner_measured_event",
        )
    return result


def anticipatory_assessment(cues, submissions, events, targets, config):
    """Assess observed targeted opportunities; never assume every lap corner was armed."""
    braking = [cue for cue in cues if cue.get("timing_class") == "anticipatory_brake"]
    required = config.get("reaction_ms", 1200)
    timely = {
        cue["brake_event_id"]
        for cue in braking
        if "brake_event_id" in cue and cue.get("minimum_completion_lead_ms", -math.inf) >= required
    }
    targeted = set()
    unmatched = set()
    for row in submissions:
        advisory = row.get("advisory") or {}
        producer = row.get("producer_tick")
        if cue_timing_class(advisory) != "anticipatory_brake" or not producer:
            continue
        payload = producer["frame"]["payload"]
        match = match_brake_target(advisory, payload, events, targets, config["track_length_m"])
        if "brake_event_id" in match:
            targeted.add(match["brake_event_id"])
        else:
            unmatched.add(
                (payload.get("lap"), advisory.get("corner"), match.get("brake_target_spline"))
            )
    denominator = len(targeted) + len(unmatched)
    coverage = len(timely & targeted) / denominator if denominator else None
    return dict(
        anticipatory_cue_count=len(braking),
        required_reaction_ms=required,
        reaction_gate=bool(braking)
        and all(cue.get("minimum_completion_lead_ms", -math.inf) >= required for cue in braking),
        timely_brake_coverage=coverage,
        coverage_gate=coverage is not None
        and coverage >= config.get("minimum_brake_coverage", 0.8),
        targeted_measured_events=sorted(targeted),
        unmatched_target_count=len(unmatched),
        coverage_denominator=denominator,
        coverage_scope="submitted_anticipatory_targets_only",
        all_eligible_corner_coverage="NOT_ESTABLISHED_WITHOUT_ARMED_CORNER_OPPORTUNITY_RECEIPTS",
    )


def match_audio(recording, rate, clock, dispatches, bank, time_key="t_mono_ms"):
    import numpy as np

    # Captured samples are spaced by the measured clock, not necessarily the WAV
    # nominal rate. Correct the template's time scale; do not widen match thresholds.
    effective_rate = 1000 / clock.ms_per_sample
    if not finite(effective_rate) or effective_rate <= 0:
        raise ValueError("invalid calibrated recording sample period")
    results, occupied, assigned_onsets, completed_intervals = [], {}, [], []
    for dispatch in dispatches:
        clip = bank.get(dispatch["clip_id"])
        result = dict(
            seq=dispatch["seq"],
            clip_id=dispatch["clip_id"],
            matched=False,
            complete=False,
            completion_ms=None,
            template_effective_samplerate=effective_rate,
            recording_nominal_samplerate=rate,
        )
        if clip is None:
            result["reason"] = "clip_missing_or_hash_invalid"
            results.append(result)
            continue
        template = al._resample_linear(
            np.asarray(clip, dtype=float), bank.samplerate, effective_rate, np
        )
        result["template_samples"] = len(template)
        start = max(
            0,
            clock.anchor_sample
            + int((dispatch[time_key] - 100 - clock.anchor_wall_ms) / clock.ms_per_sample),
            occupied.get(dispatch["clip_id"], 0),
        )
        end = min(len(recording), start + int(3100 / clock.ms_per_sample) + len(template))
        onset, score, prominence = al.find_onset(recording, template, np, start=start, end=end)
        result.update(match_score=score, match_prominence=prominence, onset_sample=onset)
        if onset is None:
            results.append(result)
            continue
        if any(abs(onset - assigned) <= effective_rate * 0.005 for assigned in assigned_onsets):
            result["reason"] = "acoustic_onset_already_assigned_to_another_dispatch"
            results.append(result)
            continue
        assigned_onsets.append(onset)
        occupied[dispatch["clip_id"]] = onset + len(template) // 2
        result.update(
            matched=True,
            onset_ms=clock.wall_ms(onset),
            latency_ms=clock.wall_ms(onset) - dispatch[time_key],
        )
        # Verify every energetic 40ms portion, including the final consonant. A strong prefix
        # alone is not a complete phrase. Small alignment search accommodates capture jitter.
        width, slack = max(1, int(effective_rate * 0.04)), max(1, int(effective_rate * 0.003))
        blocks = []
        for a in range(0, len(template), width):
            part = template[a : a + width]
            power = float(np.dot(part, part))
            if power / len(part) < 10 ** (-45 / 10):
                continue
            lo, hi = max(0, onset + a - slack), min(len(recording), onset + a + len(part) + slack)
            scores = al.normalized_match(recording[lo:hi], part, np)
            best = int(np.argmax(scores)) if len(scores) else 0
            corr = float(scores[best]) if len(scores) else 0
            segment = recording[lo + best : lo + best + len(part)]
            gain = abs(float(np.dot(segment, part)) / power) if len(segment) == len(part) else 0
            blocks.append(dict(start_sample=a, end_sample=a + len(part), score=corr, gain=gain))
        gain_floor = float(np.median([b["gain"] for b in blocks])) * 0.25 if blocks else math.inf
        for block in blocks:
            block["matched"] = (
                block["score"] >= 0.20 and block["gain"] >= gain_floor and block["gain"] > 0
            )
        result["phrase_blocks"] = blocks
        result["complete"] = bool(blocks) and all(b["matched"] for b in blocks)
        if result["complete"]:
            interval = (onset + blocks[0]["start_sample"], onset + blocks[-1]["end_sample"])
            if any(interval[0] < end and interval[1] > start for start, end in completed_intervals):
                result.update(complete=False, reason="acoustic_interval_already_assigned")
            else:
                completed_intervals.append(interval)
                result["completion_ms"] = clock.wall_ms(interval[1])
        else:
            result["reason"] = "truncated_or_masked_phrase"
        results.append(result)
    return results


def _fft_convolve(np, x, h):
    size = 1 << int(math.ceil(math.log2(len(x) + len(h))))
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)[: len(x) + len(h) - 1]


def reverb_aware_completeness(recording, rate, cues, bank, exclusions, *, seed, nulls=None):
    """Judge each located phrase complete only if all its new speech reached the microphone.

    ``cues`` are ``match_audio`` results (``onset_sample``, ``template_effective_samplerate``).
    ``exclusions`` are recording sample spans that may hold speech; they never feed a null.
    Returns one evaluation per cue, aligned with ``cues``. Fails closed when the room response
    cannot be estimated from enough other phrases, does not predict the phrase better than the
    local null, or the local null lacks cue-free material.
    """
    import numpy as np

    nulls = nulls or COMPLETENESS_NULL_SAMPLES
    rng = np.random.default_rng(seed)
    pre, tail = int(ROOM_RESPONSE_PRE_S * rate), int(ROOM_RESPONSE_TAIL_S * rate)
    ext = int(SEGMENT_TAIL_S * rate)
    align = int(PHRASE_ALIGNMENT_SEARCH_S * rate)
    items = {}
    for index, cue in enumerate(cues):
        clip = bank.get(cue.get("clip_id"))
        onset = cue.get("onset_sample")
        if not cue.get("matched") or clip is None or onset is None:
            continue
        eff = cue["template_effective_samplerate"]
        dry = np.concatenate(
            (np.zeros(pre), al._resample_linear(np.asarray(clip, float), bank.samplerate, eff, np))
        )
        lo = onset - pre
        if lo - align < 0 or lo + len(dry) + tail + align > len(recording):
            continue
        items[index] = dict(dry=dry, lo=lo, eff=eff, lag=0)
    size = 1 << int(
        math.ceil(math.log2(max([2 * len(i["dry"]) + tail for i in items.values()] or [2])))
    )

    def window(item):
        lo = item["lo"] + item["lag"]
        return recording[lo : lo + len(item["dry"]) + tail]

    def spectra_of():
        return {
            k: (np.fft.rfft(i["dry"], size), np.fft.rfft(window(i), size)) for k, i in items.items()
        }

    def leave_one_out(index, spectra):
        others = [k for k in items if k != index]
        num = sum(spectra[k][1] * np.conj(spectra[k][0]) for k in others)
        den = sum(np.abs(spectra[k][0]) ** 2 for k in others)
        return np.fft.irfft(num / (den + 1e-3 * den.mean()), size)[: pre + tail]

    def null_offsets(center, length):
        lo = max(0, int(center - COMPLETENESS_NULL_RADIUS_S * rate))
        hi = min(len(recording) - length, int(center + COMPLETENESS_NULL_RADIUS_S * rate))
        free = np.ones(max(0, hi - lo), dtype=bool)
        for a, b in exclusions:
            free[max(0, a - length - lo) : max(0, min(hi, b) - lo)] = False
        allowed = np.flatnonzero(free) + lo
        if len(allowed) < COMPLETENESS_MIN_NULL_MATERIAL_S * rate:
            return None
        return rng.choice(allowed, size=nulls, replace=True)

    def best(target, template):
        # Signed, unlike normalized_match: subtracting the echo of speech that was never played
        # leaves an inverted copy, which must not count as the segment being present.
        n, length = len(target), len(template)
        if length == 0 or n < length:
            return 0.0, 0
        fft = 1 << int(math.ceil(math.log2(n + length)))
        corr = np.fft.irfft(np.fft.rfft(target, fft) * np.conj(np.fft.rfft(template, fft)), fft)[
            : n - length + 1
        ]
        energy = np.concatenate(([0.0], np.cumsum(target * target)))
        window = np.sqrt(np.maximum(energy[length:] - energy[: n - length + 1], 1e-12))
        scores = corr / (window * max(float(np.linalg.norm(template)), 1e-12))
        k = int(np.argmax(scores))
        return float(scores[k]), k

    def z_against(template, observed, offsets, slack):
        width = len(template) + 2 * slack
        null = np.asarray([best(recording[o : o + width], template)[0] for o in offsets])
        return (observed - float(null.mean())) / (float(null.std()) + 1e-12), null

    def predict_and_align(item, h):
        # One signed lag per phrase, searched around the located onset (not per segment).
        predicted = _fft_convolve(np, item["dry"], h)[: len(item["dry"])]
        lo = item["lo"] - align
        observed, k = best(recording[lo : item["lo"] + len(predicted) + align], predicted)
        return predicted, observed, k - align

    if len(items) > COMPLETENESS_MIN_OTHER_PHRASES:
        initial = spectra_of()
        lags = {k: predict_and_align(i, leave_one_out(k, initial))[2] for k, i in items.items()}
        for k, lag in lags.items():
            items[k]["lag"] = lag
    spectra = spectra_of()

    results = []
    for index in range(len(cues)):
        result = dict(
            criterion="reverb_aware_new_content_segments",
            evaluated=False,
            complete=False,
            speech_start_sample=None,
            completion_sample=None,
            reason=None,
            segments=[],
        )
        results.append(result)
        if index not in items:
            result["reason"] = "phrase_not_located"
            continue
        others = [k for k in items if k != index]
        if len(others) < COMPLETENESS_MIN_OTHER_PHRASES:
            result["reason"] = "room_model_unqualified:too_few_other_phrases"
            continue
        it = items[index]
        h = leave_one_out(index, spectra)
        slack = SEGMENT_SLACK_SAMPLES
        predicted, observed, it["lag"] = predict_and_align(it, h)
        y, dry = window(it), it["dry"]
        offsets = null_offsets(it["lo"], len(predicted) + 2 * align)
        result["other_phrases"] = len(others)
        if offsets is None:
            result["reason"] = "null_material_insufficient"
            continue
        model_z, _ = z_against(predicted, observed, offsets, align)
        result["room_model_z"] = model_z
        result["alignment_lag_ms"] = it["lag"] / it["eff"] * 1000
        result["evaluated"] = True
        if model_z < COMPLETENESS_MIN_Z:
            result["reason"] = "room_model_unqualified:no_better_than_null"
            continue
        energy = np.cumsum(dry**2)
        bounds = [
            int(np.searchsorted(energy, energy[-1] * q / COMPLETENESS_SEGMENTS))
            for q in range(COMPLETENESS_SEGMENTS + 1)
        ]
        bounds[0] = pre
        last_lag = 0
        for a, b in zip(bounds[:-1], bounds[1:], strict=False):
            mask = np.zeros_like(dry)
            mask[a:b] = 1.0
            own = _fft_convolve(np, dry * mask, h)[a : b + ext]
            earlier = np.where(np.arange(len(dry)) < a, dry, 0.0)
            target = y - _fft_convolve(np, earlier, h)[: len(y)]
            start = max(0, a - slack)
            observed, k = best(target[start : a + len(own) + slack], own)
            seg_offsets = null_offsets(it["lo"] + a, len(own) + 2 * slack)
            if seg_offsets is None:
                result["reason"] = "null_material_insufficient"
                break
            z, null = z_against(own, observed, seg_offsets, slack)
            last_lag = start + k - a
            result["segments"].append(
                dict(
                    start_ms=(a - pre) / it["eff"] * 1000,
                    end_ms=(b - pre) / it["eff"] * 1000,
                    score=observed,
                    null_mean=float(null.mean()),
                    null_sd=float(null.std()),
                    z=z,
                    present=z >= COMPLETENESS_MIN_Z,
                )
            )
        if result["reason"]:
            continue
        result["complete"] = all(segment["present"] for segment in result["segments"])
        if result["complete"]:
            # Bounded by the measured end of the last detected segment, not by nominal length.
            result["speech_start_sample"] = it["lo"] + it["lag"] + pre
            result["completion_sample"] = it["lo"] + it["lag"] + bounds[-1] + last_lag
        else:
            result["reason"] = "segment_not_significant"
    return results


def apply_completeness(cues, completeness, wall_ms):
    """Make the reverb-aware evaluation each cue's completeness verdict, reason and completion.

    The dry 40 ms result stays only as ``dry_blocks_complete``. Two dispatches can never both
    claim one stretch of played speech, whichever rule judged them complete.
    """
    completed_intervals = []
    for cue, evaluation in zip(cues, completeness, strict=True):
        cue["dry_blocks_complete"] = cue["complete"]  # diagnostic only; not a pass path
        interval = (evaluation.pop("speech_start_sample"), evaluation.pop("completion_sample"))
        cue["acoustic_completeness"] = evaluation
        cue["complete"] = evaluation["complete"]
        if cue.get("matched"):
            cue["reason"] = evaluation["reason"]
        if cue["complete"] and any(
            interval[0] < end and interval[1] > start for start, end in completed_intervals
        ):
            cue.update(complete=False, reason="acoustic_interval_already_assigned")
        if cue["complete"]:
            completed_intervals.append(interval)
        cue["completion_ms"] = wall_ms(interval[1]) if cue["complete"] else None


def producer_identity(producer):
    if not isinstance(producer, dict) or not isinstance(producer.get("frame"), dict):
        return None
    if not all(finite(producer.get(key)) for key in ("wall_ms", "mono_ms")):
        return None
    return (json.dumps(producer["frame"], sort_keys=True), producer["wall_ms"], producer["mono_ms"])


def _timed_rows(capture, wire, taps, begin, finish):
    rows = list(capture.get("microphone", {}).get("callback_stamps", []))
    rows += [row for row in wire + taps if begin <= row.get("mono_ms", -math.inf) <= finish]
    return rows


def wall_clock_drift_evidence(capture, wire, taps, begin, finish):
    """Report wall/monotonic divergence (time-sync slew or steps); diagnostic, not a join basis.

    Run 03 of #815 measured 37.4 ms over seven minutes while Windows Time disciplined the
    system clock. Every cross-process join uses the monotonic clock instead.
    """
    pairs = [
        (capture.get(f"{part}_wall_ms"), capture.get(f"{part}_mono_ms"))
        for part in ("started", "finished")
    ]
    for row in _timed_rows(capture, wire, taps, begin, finish):
        pairs.append((row.get("wall_ms"), row.get("mono_ms")))
        if row.get("kind") == "voice_dispatch":
            dispatch = row["dispatch"]
            pairs.append((dispatch.get("t_wall_ms"), dispatch.get("t_mono_ms")))
        producer = row.get("producer_tick") or (row.get("correlation") or {}).get("producer_tick")
        if producer:
            pairs.append((producer.get("wall_ms"), producer.get("mono_ms")))
    complete = all(finite(wall) and finite(mono) for wall, mono in pairs)
    offsets = [wall - mono for wall, mono in pairs if finite(wall) and finite(mono)]
    spread = max(offsets) - min(offsets) if offsets else None
    return dict(
        samples=len(pairs),
        complete=complete,
        spread_ms=spread,
        gating=False,
        basis="diagnostic_wall_clock_only",
    )


def monotonic_timebase_evidence(capture, wire, taps, begin, finish):
    """Qualify the shared monotonic clock that every cross-process join uses.

    Recorder, wire tap and sidecar tap run on one host, where the monotonic clock is
    system-wide (QueryPerformanceCounter on Windows with Python >= 3.13; older Windows
    builds use 15.6 ms GetTickCount64, which the resolution check rejects).
    """
    reasons = []
    stamps = []
    for row in _timed_rows(capture, wire, taps, begin, finish):
        stamps.append(row.get("mono_ms"))
        if row.get("kind") == "voice_dispatch":
            stamps.append(row["dispatch"].get("t_mono_ms"))
        producer = row.get("producer_tick") or (row.get("correlation") or {}).get("producer_tick")
        if producer:
            stamps.append(producer.get("mono_ms"))
    if not stamps or not all(finite(value) for value in stamps):
        reasons.append("monotonic_stamp_missing")
    started, finished = capture.get("started_mono_ms"), capture.get("finished_mono_ms")
    if not (finite(started) and finite(finished) and finished > started):
        reasons.append("capture_monotonic_interval_invalid")
    wire_mono = [row.get("mono_ms") for row in wire]
    if not all(finite(value) for value in wire_mono) or any(
        b < a for a, b in zip(wire_mono, wire_mono[1:], strict=False)
    ):
        reasons.append("wire_monotonic_order_violated")
    callbacks = [
        row.get("mono_ms") for row in capture.get("microphone", {}).get("callback_stamps", [])
    ]
    # A millisecond-tick clock (GetTickCount64) only ever yields whole milliseconds.
    fractional = sum(finite(value) and abs(value - round(value)) > 1e-6 for value in callbacks)
    if not callbacks or fractional < max(1, len(callbacks) // 10):
        reasons.append("monotonic_resolution_unproven")
    info = capture.get("monotonic_clock")
    if info is not None and not (
        info.get("monotonic") is True
        and finite(info.get("resolution"))
        and info["resolution"] <= 0.001
    ):
        reasons.append("monotonic_clock_info_inadequate")
    return dict(
        stamps=len(stamps),
        sub_millisecond_callback_stamps=fractional,
        clock_info=info,
        reasons=reasons,
        passed=not reasons,
    )


def chirp_monotonic_anchor(mark, callback_stamps):
    """Express one chirp's DAC instant on the monotonic clock.

    New captures record ``t_dac_mono_ms`` directly. Older captures stored only the DAC wall
    instant, so convert it through the wall/monotonic offset that the recorder stamped
    within one second of it; the offsets' spread there is the conversion uncertainty.
    """
    if finite(mark.t_dac_mono_ms):
        return dict(
            label=mark.label, anchor_ms=mark.t_dac_mono_ms, basis="recorded", uncertainty_ms=0.0
        )
    wall = mark.t_dac_wall_ms
    nearby = [
        row["wall_ms"] - row["mono_ms"]
        for row in callback_stamps
        if finite(row.get("wall_ms"))
        and finite(row.get("mono_ms"))
        and finite(wall)
        and abs(row["wall_ms"] - wall) <= 1000
    ]
    if len(nearby) < 2:
        return dict(label=mark.label, anchor_ms=None, basis="unconvertible", uncertainty_ms=None)
    nearby.sort()
    offset = nearby[len(nearby) // 2]
    return dict(
        label=mark.label,
        anchor_ms=wall - offset,
        basis="wall_converted_with_local_offset",
        uncertainty_ms=nearby[-1] - nearby[0],
    )


def adc_time_diagnostic(rows):
    """Summarize PortAudio's input ADC estimate without treating it as a second clock.

    On Windows WASAPI, PortAudio derives ``inputBufferAdcTime`` from the callback's own
    stream time plus a whole-buffer queue estimate (run 02 of #815: always +10 or +20 ms).
    Two buffers delivered back to back therefore step it backwards by one period although
    the samples are contiguous. Its steps are reported, but only the monotonic callback
    clock is fitted as independent evidence.
    """
    values = [row.get("adc_time") for row in rows]
    if not values or not all(finite(value) for value in values):
        return dict(available=False, gating=False)
    offsets = sorted(
        {
            round((row["adc_time"] - row["stream_time"]) * 1000, 3)
            for row in rows
            if finite(row.get("stream_time"))
        }
    )
    return dict(
        available=True,
        gating=False,
        basis="host_estimate_from_callback_stream_time",
        nonincreasing_steps=sum(b <= a for a, b in zip(values, values[1:], strict=False)),
        adc_minus_stream_ms=offsets[:16],
    )


def callback_clock_evidence(microphone, frames, rate):
    """Validate every buffer and fit sample time independently of acoustic chirps.

    Alternate and first/last-half fits predict all held-out points, exposing curved or
    stepped clocks which a two-anchor fit would hide. These are measured residuals,
    not a claim that the cause of sample-rate skew is a particular hardware oscillator.
    """
    import numpy as np

    rows = microphone.get("callback_stamps", [])
    result = dict(passed=False, samples=len(rows), fits={}, reasons=[])
    expected = 0
    for row in rows:
        size = row.get("frames")
        if (
            type(row.get("sample")) is not int
            or row["sample"] != expected
            or type(size) is not int
            or size <= 0
            or not all(finite(row.get(key)) for key in ("wall_ms", "mono_ms"))
        ):
            result["reasons"].append("incomplete_or_noncontiguous_callback_buffers")
            return result
        expected += size
    if len(rows) < 8 or expected != frames or microphone.get("frames") != frames:
        result["reasons"].append("callback_count_or_recording_coverage_incomplete")
        return result
    if microphone.get("samplerate") != rate or microphone.get("statuses"):
        result["reasons"].append("recording_rate_mismatch_or_overflow")
        return result
    x = np.asarray([row["sample"] for row in rows], dtype=float)
    selections = {
        "all": np.arange(len(x)),
        "even": np.arange(0, len(x), 2),
        "odd": np.arange(1, len(x), 2),
        "first_half": np.arange(len(x) // 2),
        "last_half": np.arange(len(x) // 2, len(x)),
    }
    maximum_error = 0.0
    result["adc_time_diagnostic"] = adc_time_diagnostic(rows)
    y = np.asarray([row["mono_ms"] for row in rows])
    if not np.all(np.diff(y) > 0):
        result["reasons"].append("nonincreasing_mono_ms")
        return result
    fits = {}
    for label, selected in selections.items():
        dx, dy = x - x[selected[0]], y - y[selected[0]]
        matrix = np.column_stack((dx[selected], np.ones(len(selected))))
        period, intercept = np.linalg.lstsq(matrix, dy[selected], rcond=None)[0]
        residual = dy - (intercept + period * dx)
        error = float(np.max(np.abs(residual)))
        if not finite(float(period)) or period <= 0 or not finite(error):
            result["reasons"].append("nonfinite_or_nonpositive_clock_fit")
            return result
        fits[label] = dict(ms_per_sample=float(period), maximum_prediction_error_ms=error)
        maximum_error = max(maximum_error, error)
    result["fits"]["mono_ms"] = fits
    period = fits["all"]["ms_per_sample"]
    result.update(
        ms_per_sample=period,
        effective_samplerate=1000 / period,
        maximum_prediction_error_ms=maximum_error,
        frames_covered=expected,
    )
    if abs(period * rate / 1000 - 1) >= 0.05:
        result["reasons"].append("independent_sample_period_implausible")
    if maximum_error > BASE_CLOCK_UNCERTAINTY_MS:
        result["reasons"].append("independent_clock_prediction_error")
    result["passed"] = not result["reasons"]
    return result


def acoustic_chirp_band(chirps, rate):
    """Search band covering every chirp's sweep with a small margin, kept below Nyquist."""
    low = min(mark.f0_hz for mark in chirps) * 0.9
    high = min(max(mark.f1_hz for mark in chirps) * 1.03, rate * 0.49)
    if not low < high:
        raise ValueError("chirp sweep does not fit below the recording Nyquist frequency")
    return low, high


def microphone_clock_evidence(clock, marks, dac_anchors, independent, rate, timebase):
    """Qualify compensated sample time without relaxing nominal-drift or cue limits."""
    period_valid = finite(clock.ms_per_sample) and clock.ms_per_sample > 0
    drift = (clock.ms_per_sample * rate / 1000 - 1) * 1e6 if period_valid else None
    result = dict(
        map=clock.to_dict(),
        chirps=marks,
        independent_callbacks=independent,
        nominal_period_deviation_ppm=drift,
        nominal_drift_limit_ppm=1000,
        nominal_drift_bounded=drift is not None and abs(drift) <= 1000,
        nominal_drift_is_diagnostic_only=True,
        qualified=False,
        systematic_uncertainty_ms=None,
        reasons=[],
    )
    anchors = [mark for mark in marks if mark["onset_sample"] is not None]
    if (
        not period_valid
        or not finite(clock.anchor_wall_ms)
        or clock.anchors_used != 2
        or len(anchors) != 2
        or [mark["label"] for mark in anchors] != ["start", "end"]
        or len(dac_anchors) != 2
        or not all(finite(anchor["anchor_ms"]) for anchor in dac_anchors)
    ):
        result["reasons"].append("two_ordered_dac_anchors_required")
        return result
    if not independent["passed"] or not timebase["passed"]:
        result["reasons"].append("independent_timebase_unqualified")
        return result
    first, last = (anchor["onset_sample"] for anchor in anchors)
    if (
        type(first) is not int
        or type(last) is not int
        or first < 0
        or last >= independent["frames_covered"]
        or clock.anchor_sample != first
    ):
        result["reasons"].append("anchor_sample_bounds_invalid")
        return result
    span = last - first
    if span * clock.ms_per_sample <= 1000:
        result["reasons"].append("anchor_sample_order_invalid")
        return result
    disagreement = max(
        abs(clock.ms_per_sample - fits["all"]["ms_per_sample"]) * span
        for fits in independent["fits"].values()
    )
    components = dict(
        dac_and_acoustic_systematics=BASE_CLOCK_UNCERTAINTY_MS,
        independent_prediction_error=independent["maximum_prediction_error_ms"],
        anchor_slope_disagreement=disagreement,
        chirp_anchor_conversion=max(anchor["uncertainty_ms"] for anchor in dac_anchors),
    )
    result.update(
        calibrated_sample_interval=[first, last],
        uncertainty_components_ms=components,
        systematic_uncertainty_ms=sum(components.values()),
    )
    if disagreement > BASE_CLOCK_UNCERTAINTY_MS:
        result["reasons"].append("anchor_and_independent_clocks_disagree")
    result["qualified"] = not result["reasons"]
    return result


def analyze_bundle(directory, output):
    import numpy as np

    capture = json.loads((directory / "capture.json").read_bytes())
    config = capture["config"]
    report = dict(
        schema=1,
        evidence_kind=capture["kind"],
        run_id=capture["run_id"],
        gates={},
        limitations=[
            "Measured brake timestamps are sidecar ingress sample brackets; "
            "simulator-to-sidecar transport latency is not measured.",
            "Waveform completeness is acoustic evidence, not a new human intelligibility judgment.",
        ],
    )
    gates = report["gates"]
    gates["actual_capture_kind"] = capture.get("kind") == "windows_live"
    gates["capture_implementation_unchanged"] = capture.get(
        "capture_code_unchanged"
    ) is True and capture.get("capture_code_sha256") == sha(__file__)
    gates["recording_complete"] = capture.get("recording_complete") is True
    report["timebase"] = "monotonic"
    gates["immutable_inputs"] = bool(capture.get("input_hashes_before")) and capture[
        "input_hashes_before"
    ] == capture.get("input_hashes_after")
    gates["inputs_still_unchanged"] = all(
        Path(path).is_file() and sha(path) == digest
        for path, digest in capture.get("input_hashes_before", {}).items()
    )
    gates["wire_unchanged"] = sha(directory / "wire.jsonl") == capture.get("wire_sha256")
    wire = read_jsonl(directory / "wire.jsonl")
    taps = read_jsonl(config["instrument_tap"])
    report["instrument_tap_sha256"] = sha(config["instrument_tap"])
    starts = [row for row in taps if row["kind"] == "tap_start"]
    ends = [row for row in taps if row["kind"] == "tap_end"]
    gates["instrumentation_complete"] = (
        len(starts) == len(ends) == 1
        and ends[0].get("dropped") == 0
        and ends[0].get("writer_error") is None
        and ends[0].get("source_hashes_unchanged") is True
    )
    gates["one_instrumented_process"] = len({row["tap_run_id"] for row in taps}) == 1
    gates["sidecar_process_unchanged"] = bool(capture.get("sidecar_before")) and capture.get(
        "sidecar_before"
    ) == capture.get("sidecar_after")
    gates["tap_process_bound"] = (
        len(starts) == 1
        and starts[0].get("pid") == capture.get("sidecar_before", {}).get("pid")
        and starts[0].get("tap_run_id") == capture.get("sidecar_before", {}).get("tap_run_id")
    )
    report["instrumented_run"] = True
    report["tap_pid"] = starts[0].get("pid") if len(starts) == 1 else None
    chirps = [al.ChirpMark(**mark) for mark in capture.get("chirps", [])]
    if len(chirps) != 2:
        raise ValueError("capture lacks both calibration chirps; no timing can be analyzed")
    callback_stamps = capture.get("microphone", {}).get("callback_stamps", [])
    anchors = [chirp_monotonic_anchor(mark, callback_stamps) for mark in chirps]
    report["chirp_monotonic_anchors"] = anchors
    gates["two_dac_chirps"] = all(
        mark.t_dac_wall_ms is not None or mark.t_dac_mono_ms is not None for mark in chirps
    ) and all(finite(anchor["anchor_ms"]) for anchor in anchors)
    if not gates["two_dac_chirps"]:
        raise ValueError(
            "calibration chirps lack a monotonic DAC anchor; no timing can be analyzed"
        )
    begin, finish = [anchor["anchor_ms"] for anchor in anchors]
    report["wall_clock_drift"] = wall_clock_drift_evidence(capture, wire, taps, begin, finish)
    report["monotonic_timebase"] = monotonic_timebase_evidence(capture, wire, taps, begin, finish)
    gates["monotonic_timebase_valid"] = report["monotonic_timebase"]["passed"]
    scoped = [row for row in wire if begin <= row["mono_ms"] <= finish]
    sessions = {
        row["session"]["session_uuid"]
        for row in scoped
        if row.get("session") and row["session"].get("session_uuid")
    }
    expected = config.get("session_uuid")
    gates["one_exact_session"] = len(sessions) == 1 and (not expected or sessions == {expected})
    report["sessions"] = sorted(sessions)
    ticks = [row for row in scoped if row["frame"].get("type") == "telemetry_tick"]
    gates["session_identity_on_all_ticks"] = bool(ticks) and all(
        (row.get("session") or {}).get("session_uuid") in sessions
        and row["session"].get("car_id") == config["car_id"]
        and row["session"].get("track_id") == config["track_id"]
        for row in ticks
    )
    # Use the instrumented ingress clock only after an exact seq+payload match to the WS stream.
    ingress = {}
    for row in taps:
        if row["kind"] == "producer_tick_ingress":
            key = json.dumps(row["frame"], sort_keys=True)
            ingress.setdefault(key, []).append(row)
    missing = 0
    verified_producers = set()
    for row in ticks:
        matches = ingress.get(json.dumps(row["frame"], sort_keys=True), [])
        matches = [match for match in matches if abs(match["mono_ms"] - row["mono_ms"]) < 1000]
        if len(matches) == 1:
            identity = producer_identity(matches[0])
            if identity is not None:
                verified_producers.add(identity)
            row["wire_received_mono_ms"] = row["mono_ms"]
            row["mono_ms"] = matches[0]["mono_ms"]
        else:
            missing += 1
    gates["exact_tick_clock_join"] = missing == 0
    gates["telemetry_present"] = len(ticks) >= config.get("minimum_ticks", 100)
    valid = [
        row
        for row in ticks
        if all(
            finite(row["frame"].get("payload", {}).get(key))
            for key in ("brake", "spline", "speed_kmh", "lap")
        )
    ]
    gates["telemetry_fields_complete"] = len(valid) == len(ticks)
    sequences = [row["frame"].get("seq") for row in valid]
    gates["telemetry_advances"] = (
        bool(sequences)
        and all(isinstance(s, int) for s in sequences)
        and all(b > a for a, b in zip(sequences, sequences[1:], strict=False))
    )
    gaps = [b["mono_ms"] - a["mono_ms"] for a, b in zip(valid, valid[1:], strict=False)]
    gates["telemetry_contiguous"] = bool(gaps) and min(gaps) > 0 and max(gaps) <= 250
    report["telemetry"] = dict(
        ticks=len(ticks),
        max_ingress_gap_ms=max(gaps) if gaps else None,
        clock_basis="instrumented_sidecar_ingress_monotonic",
        ambiguous_joins=missing,
    )
    events = brake_events(valid)
    report["brake_events"] = events
    gates["measured_braking_present"] = len(events) >= config.get("minimum_brake_events", 1)
    try:
        targets = reference_brake_targets(config, capture.get("input_hashes_before", {}))
        report["reference_corner_targets"] = targets
        gates["qualified_reference_corner_targets"] = bool(targets)
    except (KeyError, ValueError, OSError) as exc:
        targets = {}
        report["reference_corner_target_error"] = str(exc)
        gates["qualified_reference_corner_targets"] = False
    wire_dispatches = [
        row["frame"]["payload"] for row in scoped if row["frame"].get("topic") == "coaching.voice"
    ]
    # VoiceDispatch stamps time.monotonic(); a payload without it is a failed gate, not a crash.
    dispatches = [d for d in wire_dispatches if finite(d.get("t_mono_ms"))]
    gates["dispatch_monotonic_stamped"] = len(dispatches) == len(wire_dispatches)
    dispatches.sort(key=lambda item: item["t_mono_ms"])
    gates["cues_present"] = len(dispatches) >= config.get("minimum_cues", 1)
    gates["dispatch_ids_unique"] = len({d["seq"] for d in dispatches}) == len(dispatches)
    voice_taps = [
        row
        for row in taps
        if row["kind"] == "voice_dispatch"
        and finite(row["dispatch"].get("t_mono_ms"))
        and begin <= row["dispatch"]["t_mono_ms"] <= finish
    ]
    gates["physical_dispatch_wire_bijection"] = bool(voice_taps) and sorted(
        json.dumps(row["dispatch"], sort_keys=True) for row in voice_taps
    ) == sorted(json.dumps(dispatch, sort_keys=True) for dispatch in dispatches)
    manifest = Manifest.load(Path(config["bank_dir"]) / "manifest.json")
    bank = Bank.from_manifest(manifest, config["bank_dir"])
    manifest_hash = hashlib.sha256(
        json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifests = [
        row for row in taps if row["kind"] == "resolver_manifest" and row["mono_ms"] <= finish
    ]
    current_manifests = [row for row in manifests if row["mono_ms"] >= begin]
    earlier_manifests = [row for row in manifests if row["mono_ms"] < begin]
    if earlier_manifests:
        current_manifests.insert(0, earlier_manifests[-1])
    gates["actual_resolver_manifest_matches_capture_bank"] = (
        len(current_manifests) == 1 and current_manifests[0]["canonical_sha256"] == manifest_hash
    )
    endpoints = [
        row for row in taps if row["kind"] == "playback_endpoint" and row["mono_ms"] <= finish
    ]
    current_endpoints = [row for row in endpoints if row["mono_ms"] >= begin]
    earlier = [row for row in endpoints if row["mono_ms"] < begin]
    if earlier:
        current_endpoints.insert(0, earlier[-1])
    report["playback_endpoints"] = current_endpoints
    report["configured_output_channel_map"] = config.get("output_channel_map")
    gates["one_matching_output_endpoint"] = (
        len(current_endpoints) == 1
        and current_endpoints[0].get("backend") in ("RtMixerPlayback", "SoundDevicePlayback")
        and current_endpoints[0]["details"].get("device_name") == config["output_device"]
        and current_endpoints[0]["details"].get("host_api") == config["output_host_api"]
        and (
            config.get("output_channel_map") is None
            or current_endpoints[0]["details"].get("channel_map") == config["output_channel_map"]
        )
    )
    microphone = capture["microphone"]
    gates["microphone_unchanged"] = sha(directory / "microphone.wav") == microphone["sha256"]
    gates["microphone_no_overflow"] = not microphone.get("statuses")
    audio, rate = load_wav(
        directory / "microphone.wav", config["microphone"].get("analysis_channel", 0)
    )
    independent = callback_clock_evidence(microphone, len(audio), rate)
    by_label = {anchor["label"]: anchor["anchor_ms"] for anchor in anchors}

    def anchor_of(mark):
        return by_label[mark.label]

    # Correct chirp-template duration using independent callback time before locating
    # anchors. No acoustic score/prominence threshold changes or fitted-on-match rate.
    template_rate = independent.get("effective_samplerate", rate) if independent["passed"] else rate
    clock, marks = al.build_clock_map(
        audio,
        template_rate,
        chirps,
        np,
        band_hz=acoustic_chirp_band(chirps, template_rate),
        min_score=ACOUSTIC_CHIRP_MIN_SCORE,
        min_prominence=ACOUSTIC_CHIRP_MIN_PROMINENCE,
        anchor_ms=anchor_of,
        timebase="monotonic",
    )
    gates["microphone_clock_calibrated"] = clock.anchors_used == 2
    clock_evidence = microphone_clock_evidence(
        clock, marks, anchors, independent, rate, report["monotonic_timebase"]
    )
    clock_evidence["chirp_template_samplerate"] = template_rate
    report["microphone_clock"] = clock_evidence
    gates["microphone_timebase_qualified"] = clock_evidence["qualified"]
    uncertainty = clock_evidence["systematic_uncertainty_ms"]
    cues = match_audio(audio, rate, clock, dispatches, bank)
    exclusions = []
    for dispatch in dispatches:
        start = clock.anchor_sample + int(
            (dispatch["t_mono_ms"] - clock.anchor_wall_ms) / clock.ms_per_sample
        )
        clip = bank.get(dispatch["clip_id"])
        speech = (len(clip) / bank.samplerate if clip is not None else 3.0) + ROOM_RESPONSE_TAIL_S
        exclusions.append((start - rate, start + int((3.1 + speech + 1.0) * rate)))
    for mark in marks:
        if mark.get("onset_sample") is not None:
            exclusions.append((mark["onset_sample"] - rate, mark["onset_sample"] + 2 * rate))
    completeness = reverb_aware_completeness(
        audio,
        rate,
        cues,
        bank,
        exclusions,
        seed=int(hashlib.sha256(str(capture["run_id"]).encode()).hexdigest()[:8], 16),
    )
    apply_completeness(cues, completeness, clock.wall_ms)
    report["completeness_criterion"] = dict(
        name="reverb_aware_new_content_segments",
        segments=COMPLETENESS_SEGMENTS,
        min_z=COMPLETENESS_MIN_Z,
        null_samples=COMPLETENESS_NULL_SAMPLES,
        null_radius_s=COMPLETENESS_NULL_RADIUS_S,
        min_other_phrases=COMPLETENESS_MIN_OTHER_PHRASES,
        room_response_s=[ROOM_RESPONSE_PRE_S, ROOM_RESPONSE_TAIL_S],
        dry_40ms_block_rule="diagnostic_only",
    )
    used_tokens = set()
    for dispatch, cue in zip(dispatches, cues, strict=True):
        bracket = clock_evidence.get("calibrated_sample_interval")
        cue["inside_calibrated_interval"] = bool(
            bracket
            and cue["matched"]
            and bracket[0] <= cue["onset_sample"]
            and cue["onset_sample"] + cue["template_samples"] <= bracket[1]
        )
        cue["timing_uncertainty_ms"] = uncertainty
        cue["timing_qualified"] = clock_evidence["qualified"] and cue["inside_calibrated_interval"]
        if cue["timing_qualified"]:
            cue["minimum_latency_ms"] = cue["latency_ms"] - uncertainty
            cue["maximum_latency_ms"] = cue["latency_ms"] + uncertainty
        matches = [row for row in voice_taps if row["dispatch"] == dispatch]
        cue["exact_correlation"] = (
            len(matches) == 1 and matches[0].get("exact_object_identity") is True
        )
        cue["dispatch"] = dispatch
        if not cue["exact_correlation"]:
            continue
        correlation = matches[0]["correlation"]
        cue["correlation"] = correlation
        token = correlation["token"]
        cue["token_reused"] = token in used_tokens
        used_tokens.add(token)
        cue["cancellations"] = [
            row for row in taps if row["kind"] == "playback_cancel" and row.get("token") == token
        ]
        cue["scheduler_decisions"] = [
            row for row in taps if row["kind"] == "scheduler_decision" and row.get("token") == token
        ]
        advisory = correlation["advisory"]
        cue["timing_class"] = cue_timing_class(advisory)
        producer = correlation.get("producer_tick")
        cue["producer_tick_present"] = producer is not None
        cue["producer_tick_verified"] = producer_identity(producer) in verified_producers
        if not cue["producer_tick_verified"]:
            continue
        payload = producer["frame"]["payload"]
        cue["lap"] = payload.get("lap")
        cue["corner"] = advisory.get("corner")
        is_brake = cue["timing_class"] == "anticipatory_brake"
        cue["brake_targeted"] = is_brake
        if is_brake:
            cue.update(
                match_brake_target(advisory, payload, events, targets, config["track_length_m"])
            )
            if "brake_event_id" in cue:
                event = next(
                    event for event in events if event["event_id"] == cue["brake_event_id"]
                )
                cue["brake_event_id"] = event["event_id"]
                if cue["completion_ms"] is not None and cue["timing_qualified"]:
                    cue["minimum_completion_lead_ms"] = (
                        event["earliest_ms"] - cue["completion_ms"] - uncertainty
                    )
                    cue["maximum_completion_lead_ms"] = (
                        event["onset_ms"] - cue["completion_ms"] + uncertainty
                    )
    report["cues"] = cues
    gates["all_cues_exactly_correlated"] = bool(cues) and all(
        cue.get("exact_correlation")
        and not cue.get("token_reused")
        and cue.get("producer_tick_present")
        and cue.get("producer_tick_verified")
        for cue in cues
    )
    gates["all_phrases_captured_complete"] = bool(cues) and all(cue["complete"] for cue in cues)
    gates["all_phrases_inside_calibration"] = bool(cues) and all(
        cue["inside_calibrated_interval"] for cue in cues
    )
    gates["no_canceled_phrases"] = bool(cues) and all(not cue.get("cancellations") for cue in cues)
    acts = [cue for cue in cues if cue["dispatch"].get("urgency") == "act"]
    report["not_exercised_gates"] = {}
    if acts:
        gates["act_latency_budget"] = all(
            cue["timing_qualified"] and 0 <= cue["maximum_latency_ms"] <= 450 for cue in acts
        )
    else:
        # Nothing to measure is not a pass: reported, and left out of the GO decision (#815).
        report["not_exercised_gates"]["act_latency_budget"] = "no_act_cues_dispatched"
    report["cue_timing_counts"] = {
        category: sum(cue.get("timing_class") == category for cue in cues)
        for category in ("anticipatory_brake", "reactive_save", "diagnostic_or_other")
    }
    submissions = [
        row
        for row in taps
        if row["kind"] == "advisory_submitted" and begin <= row["mono_ms"] <= finish
    ]
    gates["submitted_producers_verified"] = all(
        producer_identity(row.get("producer_tick")) in verified_producers
        for row in submissions
        if cue_timing_class(row.get("advisory") or {}) == "anticipatory_brake"
    )
    assessment = anticipatory_assessment(
        cues,
        submissions,
        events,
        targets,
        config,
    )
    report["anticipatory_assessment"] = assessment
    report["required_reaction_ms"] = assessment["required_reaction_ms"]
    report["timely_brake_coverage"] = assessment["timely_brake_coverage"]
    gates["brake_cues_complete_with_reaction_lead"] = assessment["reaction_gate"]
    gates["timely_brake_coverage"] = assessment["coverage_gate"]
    if "loopback" in capture:
        lb = capture["loopback"]
        gates["loopback_unchanged"] = sha(directory / "loopback.wav") == lb["sha256"]
        gates["loopback_no_discontinuities"] = (
            lb.get("warning_capture_complete") is True
            and not lb.get("statuses")
            and not lb.get("warnings")
        )
        channels = []
        for channel in range(lb["channels"]):
            signal, sr = load_wav(directory / "loopback.wav", channel)
            try:
                mapping, located = al.build_clock_map(
                    signal, sr, chirps, np, anchor_ms=anchor_of, timebase="monotonic"
                )
                channels.append(
                    dict(
                        channel_zero_based=channel,
                        clock=mapping.to_dict(),
                        chirps=located,
                        cues=match_audio(signal, sr, mapping, dispatches, bank),
                    )
                )
            except ValueError as exc:
                channels.append(dict(channel_zero_based=channel, error=str(exc)))
        report["loopback_digital_only"] = channels
        gates["loopback_phrase_proof"] = any(
            row.get("clock", {}).get("anchors_used") == 2
            and bool(row.get("cues"))
            and all(cue["complete"] for cue in row["cues"])
            for row in channels
        )
    else:
        gates["loopback_phrase_proof"] = False
    report["reference_qualification"] = capture.get("reference_qualification")
    report["failed_gates"] = [name for name, passed in gates.items() if not passed]
    report["engineering_acceptance"] = "PASS" if not report["failed_gates"] else "NO_GO"
    report["human_live_qualification"] = "NOT_ESTABLISHED_BY_THIS_ENGINEERING_CAPTURE"
    report["scheduler_decision_counts"] = {}
    for row in taps:
        if row["kind"] == "scheduler_decision" and begin <= row["mono_ms"] <= finish:
            reason = row["reason"]
            report["scheduler_decision_counts"][reason] = (
                report["scheduler_decision_counts"].get(reason, 0) + 1
            )
    write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--config", required=True, type=Path)
    rec.add_argument("--out", required=True, type=Path)
    rec.add_argument("--owner-pid", required=True, type=int)
    ana = sub.add_parser("analyze")
    ana.add_argument("--capture", required=True, type=Path)
    ana.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "record":
        result = record(json.loads(args.config.read_bytes()), args.out, args.owner_pid)
        print(
            json.dumps(
                dict(
                    capture=str(args.out),
                    complete=result["recording_complete"],
                    errors=result["errors"],
                )
            )
        )
        return 0 if result["recording_complete"] else 2
    try:
        result = analyze_bundle(args.capture, args.out)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result = dict(
            engineering_acceptance="NO_GO",
            failed_gates=["analysis_incomplete"],
            error=repr(exc),
            human_live_qualification="NOT_ESTABLISHED",
        )
        if not args.out.exists():
            write_json(args.out, result)
    print(
        json.dumps(
            dict(
                report=str(args.out),
                acceptance=result["engineering_acceptance"],
                failed_gates=result["failed_gates"],
                not_exercised_gates=sorted(result.get("not_exercised_gates") or {}),
            )
        )
    )
    return 0 if result["engineering_acceptance"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
