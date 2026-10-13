"""Game Point's opt-in worker, including automatic validated profile reload."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from tools.rig_controls.controller import Controller
from tools.rig_controls.ownership import Ownership, SimulatedOwnership
from tools.rig_controls.profiles import Context, load_config
from tools.rig_controls.protocol import open_device
from tools.rig_controls.windows import Actions, foreground_context


class Worker:
    def __init__(
        self,
        path: Path,
        *,
        opener=open_device,
        actions=None,
        context_provider=None,
        owner_factory=None,
    ):
        self.path = path
        self.controller = Controller(load_config(path), opener, actions or Actions())
        self.context_provider = context_provider
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = self.controller.status()
        self._thread = None
        self.reload_at = 0.0
        self.owner_factory = owner_factory or (
            Ownership if opener is open_device else SimulatedOwnership
        )
        self.owner = None
        self._running = frozenset()
        self._running_at = 0.0

    def status(self):
        with self._lock:
            snapshot = dict(self._status)
        if self._stop.is_set() and self._thread and self._thread.is_alive():
            snapshot.update(
                state="stopping", profile=None, error="shutdown pending; ownership retained"
            )
        return snapshot

    def tick(self, now: float):
        if now >= self.reload_at:
            self.controller.reload(self.path)
            self.reload_at = now + 0.5
        try:
            if self.owner is None:
                if now < self.controller.retry_at:
                    return
                self.owner = self.owner_factory()
            if self.context_provider:
                context = self.context_provider()
            else:
                sample_running = (
                    any(p.running for p in self.controller.config.profiles)
                    and now >= self._running_at
                )
                context = foreground_context(sample_running)
                now = time.monotonic()
                if sample_running:
                    self._running = context.running
                    self._running_at = now + 0.5
                context = Context(context.foreground_process, context.title, self._running)
            self.controller.step(context, now)
        except (OSError, ValueError, RuntimeError) as exc:
            self.controller.error = str(exc)
            self.controller.close()
            self.controller.retry_at = now + 1.0
        self._publish()

    def _publish(self):
        snapshot = self.controller.status()
        snapshot["action_error"] = getattr(self.controller.actions, "last_error", "")
        snapshot["action_unavailable"] = getattr(self.controller.actions, "last_unavailable", "")
        with self._lock:
            self._status = snapshot

    def _run(self):
        try:
            while not self._stop.is_set():
                self.tick(time.monotonic())
                self._stop.wait(0.02)
        finally:
            self._close()

    def _close(self):
        self.controller.close()
        if self.owner:
            self.owner.close()
            self.owner = None
        self._publish()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="GamePoint-keypad", daemon=True)
            self._thread.start()

    def stop(self) -> bool:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            # The mutex belongs to the worker thread. Only its finally block may
            # release it; another controller must not race a still-running worker.
            return not self._thread.is_alive()
        else:
            self._close()
            return True
