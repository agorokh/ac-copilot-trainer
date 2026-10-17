"""Bounded model admission and the rig's supervised inference profile (#854).

This is client policy. GPU isolation is enforced and attested by the host service;
putting CUDA variables on this HTTP client would not constrain that service.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from typing import Any

# Retained as the attestation fixture a health endpoint must match when the operator
# configures AC_COPILOT_INFERENCE_GPU_UUID; it is no longer seeded as a default (the
# matching RTX3050 inference rig was removed 2026-10-16, issue #854).
RIG_GPU_UUID = "GPU-1b2968de-307e-8a39-093d-24ebdc1366dc"
RIG_DEFAULTS = {
    # RTX3050 inference rig removed 2026-10-16 (#854); no qualified replacement exists.
    # Default is rules-only / deterministic CPU brain. Re-enabling model coaching is an
    # explicit operator decision that must also supply a separately approved backend
    # contract (provider, loopback base/health URL, model, and GPU attestation); we do
    # not bake the retired localhost:11435/3050 service back in, and inference must
    # never silently fall back onto the main RTX3060.
    "AC_COPILOT_INFERENCE_ENABLE": "0",
    # Bounded generation profile a future qualified backend must honour (finite caps).
    "AC_COPILOT_OLLAMA_TEMPERATURE": "0",
    "AC_COPILOT_OLLAMA_NUM_PREDICT": "64",
    "AC_COPILOT_OLLAMA_TIMEOUT_SEC": "8",
    "AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC": "8",
}


def apply_rig_inference_defaults(env: MutableMapping[str, str]) -> None:
    """Seed child-only defaults (rules-only unless the operator opts in).

    An explicit operator ``AC_COPILOT_INFERENCE_ENABLE`` — or the legacy
    ``AC_COPILOT_OLLAMA_ENABLE`` alias — stays authoritative, as does any explicit
    backend endpoint/model the operator provides. We no longer seed the retired
    localhost:11435/RTX3050 endpoint, so a bare re-enable makes no retry against it.
    """
    if "AC_COPILOT_INFERENCE_ENABLE" not in env and "AC_COPILOT_OLLAMA_ENABLE" in env:
        env["AC_COPILOT_INFERENCE_ENABLE"] = env["AC_COPILOT_OLLAMA_ENABLE"]
    for key, value in RIG_DEFAULTS.items():
        env.setdefault(key, value)


@dataclass
class _Request:
    call: Callable[[], Any]
    deadline: float
    priority: int
    future: asyncio.Future[Any]


class LatestGenerationQueue:
    """One active blocking job and one replaceable pending job per event loop.

    Cancellation of a submitter never cancels the worker or releases its slot.
    urllib timeout still cannot certify backend cancellation: the supervised
    host must retain its own admission slot until its upstream request ends.
    """

    def __init__(self) -> None:
        self._pending: _Request | None = None
        self._worker: asyncio.Task[None] | None = None
        self.active = False
        self.discarded = 0

    async def submit(self, call: Callable[[], Any], *, deadline: float, priority: int = 0) -> Any:
        if not math.isfinite(deadline) or time.monotonic() >= deadline:
            self.discarded += 1
            return None
        future = asyncio.get_running_loop().create_future()
        if self._pending is not None and self._pending.priority > priority:
            self.discarded += 1
            return None
        if self._pending is not None:
            self.discarded += 1
            self._pending.future.set_result(None)
        self._pending = _Request(call, deadline, priority, future)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())
        # Shield also leaves the future readable by _drain after caller cancellation.
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # A disconnected client no longer reads this outcome. Keep the work
            # owned, but consume a later exception so it is not lost to asyncio.
            future.add_done_callback(
                lambda done: done.exception() if not done.cancelled() else None
            )
            raise

    async def _drain(self) -> None:
        while self._pending is not None:
            request, self._pending = self._pending, None
            if time.monotonic() >= request.deadline:
                self.discarded += 1
                request.future.set_result(None)
                continue
            self.active = True
            try:
                result = await asyncio.to_thread(request.call)
                if time.monotonic() >= request.deadline:
                    self.discarded += 1
                    result = None
                request.future.set_result(result)
            except Exception as exc:
                request.future.set_exception(exc)
            finally:
                self.active = False

    def status(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "pending": int(self._pending is not None),
            "discarded": self.discarded,
        }
