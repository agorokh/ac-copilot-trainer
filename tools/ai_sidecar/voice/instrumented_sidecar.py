"""Optional exact-identity diagnostic tap around unchanged sidecar seams.

Run only by the rig owner. No alternate producer, scheduler, resolver or playback.
Normally launched by tools.ac_harness.live_voice through the canonical Game Point UI.
Usage: python -B -m tools.ai_sidecar.voice.instrumented_sidecar --tap NEW.jsonl -- <sidecar args>
"""

from __future__ import annotations

import _thread
import argparse
import contextvars
import dataclasses
import hashlib
import json
import os
import queue
import runpy
import sys
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path


class Tap:
    def __init__(self, path: Path):
        self.file = path.open("x", encoding="utf-8")
        self.queue = queue.Queue(maxsize=65536)
        self.dropped = 0
        self.error = None
        self.run_id = str(uuid.uuid4())
        self.source_hashes = {
            str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        }
        self.thread = threading.Thread(target=self._writer, name="acceptance-tap", daemon=True)
        self.thread.start()
        self.emit(
            "tap_start",
            pid=os.getpid(),
            instrumented=True,
            wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        )

    def emit(self, kind, **data):
        row = dict(
            kind=kind,
            tap_run_id=self.run_id,
            wall_ms=time.time_ns() / 1e6,
            mono_ms=time.monotonic_ns() / 1e6,
        )
        row.update(data)
        try:
            self.queue.put_nowait(row)
        except queue.Full:
            self.dropped += 1

    def _writer(self):
        try:
            while True:
                row = self.queue.get()
                if row is None:
                    break
                self.file.write(json.dumps(row, allow_nan=False) + "\n")
                self.file.flush()
        except BaseException as exc:
            self.error = repr(exc)

    def close(self):
        unchanged = all(
            Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
            for path, digest in self.source_hashes.items()
        )
        self.emit(
            "tap_end",
            dropped=self.dropped,
            writer_error=self.error,
            source_hashes_unchanged=unchanged,
        )
        self.queue.put(None, timeout=5)
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("tap writer did not stop")
        self.file.close()
        if self.error or self.dropped:
            raise RuntimeError(f"tap incomplete: dropped={self.dropped}, error={self.error}")


def install(tap):
    """Patch diagnostics only, returning an undo function for tests/owned teardown."""
    from tools.ai_sidecar import coaching_runtime, realtime_observer, server
    from tools.ai_sidecar.voice import playback
    from tools.ai_sidecar.voice.dispatch import DispatchTapPlayback
    from tools.ai_sidecar.voice.resolver import Resolver
    from tools.ai_sidecar.voice.scheduler import Scheduler

    sources = {
        str(Path(module.__file__).resolve()): hashlib.sha256(
            Path(module.__file__).read_bytes()
        ).hexdigest()
        for module in (
            sys.modules[Resolver.__module__],
            sys.modules[Scheduler.__module__],
            sys.modules[DispatchTapPlayback.__module__],
            playback,
            realtime_observer,
            coaching_runtime,
            server,
        )
    }
    if hasattr(tap, "source_hashes"):
        tap.source_hashes.update(sources)
    tap.emit("instrumentation_sources", sources=sources)

    originals = []
    resolved = OrderedDict()
    submitted = OrderedDict()
    context = threading.local()
    producer_tick = contextvars.ContextVar("acceptance_producer_tick", default=None)
    counter = 0

    def remember(mapping, key, value):
        mapping[key] = value
        while len(mapping) > 16384:
            mapping.popitem(last=False)

    def patch(cls, name, wrapper):
        original = getattr(cls, name)
        originals.append((cls, name, original))
        setattr(cls, name, wrapper(original))

    def data(value):
        return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else None

    def resolver_init_wrapper(original):
        def wrapped(self, manifest):
            digest = hashlib.sha256(
                json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            tap.emit("resolver_manifest", canonical_sha256=digest)
            return original(self, manifest)

        return wrapped

    patch(Resolver, "__init__", resolver_init_wrapper)

    # Capture the actual input used by the observer, not a second replay producer.
    def publish_wrapper(original):
        async def wrapped(frame, *, exclude):
            tick = {
                "frame": frame,
                "wall_ms": time.time_ns() / 1e6,
                "mono_ms": time.monotonic_ns() / 1e6,
            }
            tap.emit("producer_tick_ingress", **tick)
            token = producer_tick.set(tick)
            try:
                return await original(frame, exclude=exclude)
            finally:
                producer_tick.reset(token)

        return wrapped

    patch(server, "_publish_coaching_cues", publish_wrapper)

    def submit_wrapper(original):
        def wrapped(self, advisory):
            nonlocal counter
            counter += 1
            token = f"{tap.run_id}:{counter}"
            event = dict(token=token, advisory=data(advisory), producer_tick=producer_tick.get())
            remember(submitted, id(advisory), (advisory, event))
            tap.emit("advisory_submitted", **event)
            return original(self, advisory)

        return wrapped

    patch(Scheduler, "submit", submit_wrapper)

    def resolve_wrapper(original):
        def wrapped(self, advisory):
            utterance = original(self, advisory)
            item = submitted.get(id(advisory))
            event = item[1] if item and item[0] is advisory else None
            if utterance is not None and event is not None:
                remember(resolved, id(utterance), (utterance, event))
                tap.emit("advisory_resolved", **event, utterance=data(utterance))
            return utterance

        return wrapped

    patch(Resolver, "resolve", resolve_wrapper)

    def token_for(utterance):
        item = resolved.get(id(utterance))
        return item[1] if item and item[0] is utterance else None

    def decision_wrapper(original):
        def wrapped(self, reason, now, enqueued_at, *, advisory=None, utterance=None):
            item = token_for(utterance)
            if item is None and advisory is not None:
                raw = submitted.get(id(advisory))
                item = raw[1] if raw and raw[0] is advisory else None
            tap.emit(
                "scheduler_decision",
                reason=reason,
                scheduler_now=now,
                enqueued_at=enqueued_at,
                token=item["token"] if item else None,
                utterance=data(utterance),
                advisory=data(advisory),
            )
            return original(self, reason, now, enqueued_at, advisory=advisory, utterance=utterance)

        return wrapped

    patch(Scheduler, "_decision", decision_wrapper)

    def init_wrapper(original):
        def wrapped(self, inner, listener, **kwargs):
            tap.emit(
                "playback_endpoint",
                backend=type(inner).__name__,
                details=dict(inner.output_details),
            )

            def observed(dispatch):
                item = getattr(context, "playing", None)
                tap.emit(
                    "voice_dispatch",
                    dispatch=dispatch.to_payload(),
                    correlation=item,
                    exact_object_identity=item is not None,
                )
                return listener(dispatch)

            return original(self, inner, observed, **kwargs)

        return wrapped

    patch(DispatchTapPlayback, "__init__", init_wrapper)

    def play_wrapper(original):
        def wrapped(self, utterance):
            context.playing = token_for(utterance)
            try:
                return original(self, utterance)
            finally:
                context.playing = None

        return wrapped

    patch(DispatchTapPlayback, "play", play_wrapper)

    def cancel_wrapper(original):
        def wrapped(self):
            utterance = self.current
            item = token_for(utterance)
            tap.emit(
                "playback_cancel", token=item["token"] if item else None, utterance=data(utterance)
            )
            return original(self)

        return wrapped

    patch(DispatchTapPlayback, "cancel", cancel_wrapper)

    def undo():
        for cls, name, original in reversed(originals):
            setattr(cls, name, original)

    return undo


def validate_stop_file(path):
    """A fresh owner-selected signal, never created or removed by this wrapper."""
    path = path.absolute()
    if os.path.lexists(path):
        raise ValueError(f"stop file must not exist at startup: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"stop file parent must already exist: {path.parent}")
    return path


class StopFileWatcher:
    """Deliver one ordinary SIGINT on the sidecar loop, preserving its teardown."""

    def __init__(self, path, tap):
        self.path = validate_stop_file(path)
        self.tap = tap
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._watch, name="acceptance-stop", daemon=True)

    def start(self):
        self.tap.emit("stop_file_armed", path=str(self.path))
        self.thread.start()

    def _watch(self):
        from tools.ai_sidecar import server

        requested = False
        while not self.done.wait(0.1):
            if not requested and self.path.is_file():
                requested = True
                self.tap.emit("stop_requested", path=str(self.path), mechanism="SIGINT")
            # Wait through startup until asyncio owns SIGINT. Scheduling on this
            # loop also wakes Windows' otherwise indefinitely blocked selector.
            loop = server._event_loop
            if requested and loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._interrupt)
                except RuntimeError:  # Loop closed between the check and scheduling.
                    continue
                return

    def _interrupt(self):
        if not self.done.is_set():
            self.tap.emit("stop_signal_delivered", mechanism="SIGINT")
            _thread.interrupt_main()

    def close(self):
        self.done.set()
        if self.thread.ident is not None:
            self.thread.join(2)
            if self.thread.is_alive():
                raise RuntimeError("stop-file watcher did not stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tap", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, help="fresh owner-created graceful-stop signal")
    args, remainder = parser.parse_known_args()
    if remainder[:1] == ["--"]:
        remainder = remainder[1:]
    if args.stop_file is not None:
        validate_stop_file(args.stop_file)
    tap = Tap(args.tap)

    def undo():
        return None

    watcher = None
    try:
        undo = install(tap)
        if args.stop_file is not None:
            watcher = StopFileWatcher(args.stop_file, tap)
            watcher.start()
        sys.argv = ["tools.ai_sidecar", *remainder]
        runpy.run_module("tools.ai_sidecar", run_name="__main__")
    finally:
        if watcher is not None:
            watcher.close()
        undo()
        tap.close()


if __name__ == "__main__":
    main()
