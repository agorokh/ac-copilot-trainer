"""Resilient AC launcher — retry past the CSP init livelock, hold a stable session (#624).

Why this exists (#619): Custom Shaders Patch hits a **stochastic infinite loop on AC's main
thread during session init** — dump-proven (thread 0 parked on an arithmetic instruction inside
a tight hash loop in CSP's ``accRenderingAdv.dll``, no wait frame, all other threads idle). It is
roughly a coin-flip per launch, and a session that *clears* init runs indefinitely stable. So the
rig is not unusable because sessions die — it is unusable because **starting one is a lottery**.

This module turns that lottery into a bounded retry: relaunch until a session sustains continuous
render progress for a stability window, then leave AC **live and drivable** for the operator (it
never hijacks car controls, unlike ``auto_drive``).

Why the existing pieces do not cover it:

* :mod:`tools.ac_harness.entry_launcher` retries, but declares success after a handful of quick
  live reads — it **misses the delayed init freeze**, which lands ~48-90 s *after* go-live.
* :mod:`tools.ac_harness.auto_drive` reaches live reliably but then drives autonomously and exits
  on a bounded window, so it cannot hand a live session to a human driver.

The launch itself reuses the proven primitives (``ContentManagerActuator`` +
``minimize_foreground_window`` + a freshly generated deterministic preset). A prototype that
hand-rolled the ``acmanager://`` URL returned ``never_live`` repeatedly because it skipped the
foreground-minimize (CM's auto-start race loses when a window holds the desktop foreground) and
CM's stale-session cold-restart (#537/#558) — both are handled here.

The verdict logic is a **pure function** over sampled ``(t, gfx_packet, acs_alive)`` traces so it
is unit-tested off-rig with no Assetto Corsa present.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_STABILITY_WINDOW = 140.0
DEFAULT_GO_LIVE_TIMEOUT = 80.0
DEFAULT_MAX_ATTEMPTS = 12
#: consecutive unchanged-packet samples (while acs is alive) that count as a wedge
DEFAULT_STALL_SAMPLES = 4
#: consecutive never_live attempts before cold-restarting Content Manager (#537/#558)
NEVER_LIVE_BEFORE_CM_RESTART = 2


class LaunchVerdict(StrEnum):
    """Outcome of watching one launch attempt."""

    PENDING = "pending"
    STABLE = "stable"
    FROZE = "froze"
    NEVER_LIVE = "never_live"


@dataclass(frozen=True)
class Sample:
    """One observation of the sim's render liveness.

    ``gfx_packet`` is ``acpmf_graphics.packetId`` — it advances once per rendered frame, so a
    frozen render loop pins it while the process stays alive. ``entry_ready`` preserves the
    graphics page's LIVE + not-in-pit predicate so an advancing pre-drive menu cannot pass as a
    drivable session. ``None`` means that field could not be read yet.
    """

    t: float
    gfx_packet: int | None
    acs_alive: bool
    entry_ready: bool | None = True


def classify(
    samples: Sequence[Sample],
    *,
    go_live_timeout: float = DEFAULT_GO_LIVE_TIMEOUT,
    stability_window: float = DEFAULT_STABILITY_WINDOW,
    stall_samples: int = DEFAULT_STALL_SAMPLES,
) -> LaunchVerdict:
    """Classify one launch attempt from its liveness trace. Pure — no I/O, no clock.

    Semantics:

    * **go-live** is the first sample whose ``gfx_packet`` advanced over the previous sample while
      ``acs_alive``. No go-live within ``go_live_timeout`` of the first sample → ``NEVER_LIVE``.
    * after go-live, ``stall_samples`` consecutive samples with an unchanged ``gfx_packet`` while
      ``acs_alive`` → ``FROZE`` (this is the delayed init livelock the other launchers miss).
    * surviving ``stability_window`` seconds past go-live without stalling → ``STABLE``.

    ``acs`` disappearing after go-live is reported as ``FROZE`` rather than ``STABLE``: the session
    did not survive, and the caller must retry either way.
    """
    if not samples:
        return LaunchVerdict.PENDING
    if go_live_timeout <= 0:
        raise ValueError("go_live_timeout must be > 0")
    if stability_window <= 0:
        raise ValueError("stability_window must be > 0")
    if stall_samples <= 0:
        raise ValueError("stall_samples must be > 0")

    t0 = samples[0].t
    live_since: float | None = None
    prev_packet: int | None = None
    stall_run = 0

    for sample in samples:
        advanced = (
            sample.acs_alive
            and sample.gfx_packet is not None
            and prev_packet is not None
            and sample.gfx_packet != prev_packet
        )
        if live_since is None:
            if sample.t - t0 >= go_live_timeout:
                return LaunchVerdict.NEVER_LIVE
            if advanced and sample.entry_ready is True:
                live_since = sample.t
        else:
            if not sample.acs_alive:
                return LaunchVerdict.FROZE
            if sample.entry_ready is False:
                return LaunchVerdict.FROZE
            if advanced:
                stall_run = 0
            elif sample.gfx_packet is not None and sample.gfx_packet == prev_packet:
                stall_run += 1
                if stall_run >= stall_samples:
                    return LaunchVerdict.FROZE
            if (
                advanced
                and sample.entry_ready is True
                and sample.t - live_since >= stability_window
            ):
                return LaunchVerdict.STABLE
        if sample.gfx_packet is not None:
            prev_packet = sample.gfx_packet

    if live_since is None:
        return LaunchVerdict.PENDING
    # The trace ended before either terminal threshold. A short hitch is not a freeze, and an
    # advancing live session is not a never-live failure merely because its window is unfinished.
    return LaunchVerdict.PENDING


@dataclass(frozen=True)
class LaunchReport:
    """Summary of a full retry run."""

    verdict: LaunchVerdict
    attempts: int
    froze: int
    never_live: int

    @property
    def succeeded(self) -> bool:
        return self.verdict is LaunchVerdict.STABLE

    def summary(self) -> str:
        if self.succeeded:
            return (
                f"stable drivable session held on attempt {self.attempts} "
                f"(froze {self.froze}, never_live {self.never_live}) — AC left LIVE"
            )
        return (
            f"no stable session in {self.attempts} attempt(s) "
            f"(froze {self.froze}, never_live {self.never_live}); "
            "a reboot lowers the per-launch freeze rate — rerun after one"
        )


def run_retry_loop(
    watch_attempt: Callable[[int], LaunchVerdict],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    on_never_live_streak: Callable[[], None] | None = None,
    never_live_before_restart: int = NEVER_LIVE_BEFORE_CM_RESTART,
) -> LaunchReport:
    """Drive attempts until one is ``STABLE`` or the budget is spent. Pure control flow.

    ``watch_attempt(attempt_number)`` performs one launch+watch and returns its verdict.
    ``on_never_live_streak`` is invoked once a run of ``never_live_before_restart`` consecutive
    ``NEVER_LIVE`` verdicts is seen — the hook the CLI uses to cold-restart a stale Content
    Manager (#537/#558) rather than pointlessly re-sending the same URL.
    """
    if max_attempts <= 0:
        raise ValueError("max_attempts must be > 0")
    if never_live_before_restart <= 0:
        raise ValueError("never_live_before_restart must be > 0")

    froze = never_live = 0
    never_live_run = 0
    last_verdict = LaunchVerdict.NEVER_LIVE
    for attempt in range(1, max_attempts + 1):
        verdict = watch_attempt(attempt)
        if verdict is LaunchVerdict.PENDING:
            raise ValueError("watch_attempt returned a non-terminal PENDING verdict")
        last_verdict = verdict
        if verdict is LaunchVerdict.STABLE:
            return LaunchReport(verdict, attempt, froze, never_live)
        if verdict is LaunchVerdict.FROZE:
            froze += 1
            never_live_run = 0
        else:
            never_live += 1
            never_live_run += 1
            if never_live_run >= never_live_before_restart and on_never_live_streak is not None:
                on_never_live_streak()
                never_live_run = 0
    return LaunchReport(last_verdict, max_attempts, froze, never_live)


# --------------------------------------------------------------------------------------
# Rig side (Windows-only; imported lazily so the pure logic above stays unit-testable).
# --------------------------------------------------------------------------------------


def _log(msg: str) -> None:  # pragma: no cover - rig-only progress trace
    print(f"[resilient-launch {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _sample_now(
    read_state: Callable[[], tuple[int | None, bool | None]], acs_alive: Callable[[], bool]
) -> Sample:  # pragma: no cover - rig-only
    packet, entry_ready = read_state()
    return Sample(
        t=time.monotonic(),
        gfx_packet=packet,
        acs_alive=acs_alive(),
        entry_ready=entry_ready,
    )


def _process_running(image: str) -> bool:  # pragma: no cover - rig-only
    from tools.ac_harness.entry_launcher import running_process_ids

    return bool(running_process_ids(image))


def _ensure_cm_running(  # pragma: no cover - rig-only
    cm_exe: Path, *, timeout: float = 45.0, settle: float = 8.0, poll: float = 1.0
) -> bool:
    """Make sure Content Manager is up **before** an ``acmanager://`` URL is sent to it.

    CM processes the quick-drive URL through **single-instance IPC** — it is handed to an
    ALREADY-RUNNING CM. Firing the URL at a cold/absent CM merely opens CM's window and never
    starts a session, so every attempt reports ``never_live`` and ``acs.exe`` never appears.

    This bit us for real: the ``never_live`` cold-restart path killed CM and then immediately sent
    the next URL into the void, so the launcher spent whole runs shooting at nothing. Any A/B
    measured through that state is invalid, not just slow.
    """
    import subprocess

    if _process_running("Content Manager.exe"):
        return True
    if not cm_exe.is_file():
        _log(f"WARNING: Content Manager executable not found: {cm_exe}")
        return False
    _log("Content Manager not running — starting it before sending the quick-drive URL")
    try:
        subprocess.Popen([str(cm_exe)])
    except OSError as exc:
        _log(f"WARNING: Content Manager failed to start: {exc}")
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _process_running("Content Manager.exe"):
            time.sleep(settle)  # let CM finish initializing its IPC listener
            return True
        time.sleep(poll)
    _log("WARNING: Content Manager did not start; the launch URL will not be honored")
    return False


def _ensure_acs_gone(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool], *, timeout: float = 15.0, poll: float = 1.0
) -> None:
    """Kill any surviving ``acs.exe`` and wait until it has really left the process table.

    A wedged sim keeps its window and shared-memory section, so launching on top of it makes
    Content Manager's next start fail to reach LIVE. ``taskkill`` returning is not sufficient —
    the process can linger — so poll (bounded) until it is actually gone.
    """
    import subprocess

    if not acs_alive():
        return
    subprocess.run(["taskkill", "/im", "acs.exe", "/f", "/t"], capture_output=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not acs_alive():
            return
        time.sleep(poll)
    _log("WARNING: acs.exe still present after kill+wait; launching anyway")


def _watch_live(  # pragma: no cover - rig-only
    read_state: Callable[[], tuple[int | None, bool | None]],
    acs_alive: Callable[[], bool],
    *,
    go_live_timeout: float,
    stability_window: float,
    poll_interval: float = 1.0,
) -> LaunchVerdict:
    """Sample until the attempt resolves, then classify. Streams samples into :func:`classify`."""
    samples: list[Sample] = []
    deadline = time.monotonic() + go_live_timeout + stability_window + 30.0
    while time.monotonic() < deadline:
        samples.append(_sample_now(read_state, acs_alive))
        verdict = classify(
            samples, go_live_timeout=go_live_timeout, stability_window=stability_window
        )
        if verdict is not LaunchVerdict.PENDING:
            return verdict
        time.sleep(poll_interval)
    return LaunchVerdict.FROZE


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be finite and >= 0")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only entrypoint
    parser = argparse.ArgumentParser(
        description="Launch AC, retry past the CSP init livelock (#619), hold a stable session"
    )
    parser.add_argument("--car", required=True, help="car id, e.g. ks_porsche_911_gt3_r_2016")
    parser.add_argument("--track", required=True, help="track id, e.g. spa")
    parser.add_argument("--layout", default=None, help="track layout for multi-layout circuits")
    parser.add_argument(
        "--stability-window", type=_positive_float, default=DEFAULT_STABILITY_WINDOW
    )
    parser.add_argument("--go-live-timeout", type=_positive_float, default=DEFAULT_GO_LIVE_TIMEOUT)
    parser.add_argument("--max-attempts", type=_positive_int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--rig-lock-timeout",
        type=_non_negative_float,
        default=0.0,
        help="seconds to wait for the machine-wide rig lock (default: fail immediately)",
    )
    args = parser.parse_args(argv)

    from tools.ac_harness.entry_launcher import ContentManagerActuator, running_process_ids
    from tools.ac_harness.preset_utils import build_practice_preset
    from tools.ac_harness.rig_lock import (
        RigSessionBusy,
        RigSessionLock,
        RigSessionOwner,
        default_rig_session_lock_path,
    )
    from tools.ac_harness.shared_memory import SharedMemoryReader, SharedMemoryUnavailable
    from tools.ac_harness.window_utils import minimize_foreground_window

    def read_state() -> tuple[int | None, bool | None]:
        """Current render packet and LIVE+not-in-pit readiness from one graphics snapshot."""
        try:
            reader = SharedMemoryReader(with_physics=False)
        except (SharedMemoryUnavailable, OSError):
            return None, None
        try:
            graphics = reader.read_graphics()
            return graphics.packet_id, graphics.is_live and not graphics.is_in_pit
        except (SharedMemoryUnavailable, OSError):
            return None, None
        finally:
            reader.close()

    def acs_alive() -> bool:
        return bool(running_process_ids("acs.exe"))

    lock_path = default_rig_session_lock_path()
    rig_lock = RigSessionLock(
        lock_path,
        owner=RigSessionOwner(
            pid=os.getpid(),
            cwd=str(Path.cwd()),
            car=args.car,
            track=args.track,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        ),
        timeout=args.rig_lock_timeout,
    )
    try:
        rig_lock.acquire()
    except RigSessionBusy as exc:
        _log(f"RIG BUSY — {exc}")
        return 3
    _log(f"rig lock acquired -> {rig_lock.path}")
    try:
        # The generated preset is application state: keep it under the same approved per-user
        # Harness root as the cross-worktree lock, and create it only after ownership is acquired.
        # A PID-scoped filename also prevents stale runs from sharing one mutable preset path.
        preset_dir = lock_path.parent / "presets"
        preset_dir.mkdir(parents=True, exist_ok=True)
        preset = preset_dir / f"resilient-launch-{os.getpid()}.cmpreset"
        preset.write_text(
            build_practice_preset(args.car, args.track, start_type="START", layout=args.layout),
            encoding="utf-8",
        )
        _log(f"preset -> {preset}")

        # cm_exe=None -> ContentManagerActuator.DEFAULT_CM_EXE (standard install path).
        actuator = ContentManagerActuator(preset=preset, cm_exe=None)

        def watch_attempt(attempt: int) -> LaunchVerdict:
            _log(f"attempt {attempt}/{args.max_attempts}: launching via Content Manager")
            # A wedged acs from the previous attempt must be GONE before relaunching.
            _ensure_acs_gone(acs_alive)
            # The quick-drive URL is IPC to a RUNNING CM. Do not spend a full attempt when its
            # executable is absent or startup failed.
            if not _ensure_cm_running(ContentManagerActuator.DEFAULT_CM_EXE):
                return LaunchVerdict.NEVER_LIVE
            minimize_foreground_window()
            actuator.launch() if attempt == 1 else actuator.relaunch()
            verdict = _watch_live(
                read_state,
                acs_alive,
                go_live_timeout=args.go_live_timeout,
                stability_window=args.stability_window,
            )
            _log(f"attempt {attempt}: {verdict}")
            return verdict

        def cold_restart_cm() -> None:
            _log("two consecutive never_live — cold-restarting Content Manager (stale preset IPC)")
            actuator.restart_content_manager()

        report = run_retry_loop(
            watch_attempt,
            max_attempts=args.max_attempts,
            on_never_live_streak=cold_restart_cm,
        )
        _log(report.summary())
        if not report.succeeded:
            return 1

        # The stable session belongs to this operator-facing launcher until AC exits. Releasing
        # the cross-worktree lock immediately after the gate would let a peer harness kill the
        # human driver's live session. Ctrl-C is an explicit ownership release and leaves AC up.
        _log(
            "stable session handed to operator; holding rig ownership until AC exits "
            "(Ctrl-C releases)"
        )
        try:
            while acs_alive():
                time.sleep(1.0)
        except KeyboardInterrupt:
            _log("operator released rig ownership; AC left LIVE")
        return 0
    finally:
        rig_lock.release()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
