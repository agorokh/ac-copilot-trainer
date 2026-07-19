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


class _ContentManagerRestartTimeout(RuntimeError):
    """A killed Content Manager never released its process/IPC identity."""


class _AcsCleanupTimeout(RuntimeError):
    """A killed Assetto Corsa process remained alive past the cleanup deadline."""


class _Car0ProbeCleanupError(RuntimeError):
    """The temporary Custom-AI drivability mapping could not be released safely."""

    def __init__(self, message: str, controller: object) -> None:
        super().__init__(message)
        self.controller = controller


class _Car0NotDrivable(RuntimeError):
    """The one bounded Car0 handshake completed without a drivable car."""


class _OperatorRelease(RuntimeError):
    """Game Point explicitly requested release of resilient rig ownership."""


@dataclass(frozen=True)
class Sample:
    """One observation of the sim's render liveness.

    ``gfx_packet`` is ``acpmf_graphics.packetId`` — it advances once per rendered frame, so a
    frozen render loop pins it while the process stays alive. ``entry_ready`` preserves the
    graphics page's LIVE + not-in-pit predicate. ``drivable`` is the stronger, rig-proven Car0
    handshake: the CSP pre-drive overlay can report LIVE + not-in-pit while remaining non-drivable.
    ``None`` means that field could not be read yet.
    """

    t: float
    gfx_packet: int | None
    acs_alive: bool
    entry_ready: bool | None = True
    drivable: bool | None = True


def classify(
    samples: Sequence[Sample],
    *,
    go_live_timeout: float = DEFAULT_GO_LIVE_TIMEOUT,
    stability_window: float = DEFAULT_STABILITY_WINDOW,
    stall_samples: int = DEFAULT_STALL_SAMPLES,
    started_at: float | None = None,
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

    # ``_watch_live`` supplies its pre-probe start so a blocking readiness handshake consumes the
    # go-live budget. Pure/unit callers may omit it and retain the trace-relative behavior.
    t0 = samples[0].t if started_at is None else started_at
    live_since: float | None = None
    prev_packet: int | None = None
    stall_run = 0
    not_ready_run = 0
    seen_acs_alive = False

    for sample in samples:
        ready = sample.entry_ready is True and sample.drivable is True
        not_ready = sample.entry_ready is False or sample.drivable is False
        advanced = (
            sample.acs_alive
            and sample.gfx_packet is not None
            and prev_packet is not None
            and sample.gfx_packet > prev_packet
        )
        regressed = (
            sample.gfx_packet is not None
            and prev_packet is not None
            and sample.gfx_packet < prev_packet
        )
        if live_since is None:
            if seen_acs_alive and not sample.acs_alive:
                return LaunchVerdict.NEVER_LIVE
            seen_acs_alive = seen_acs_alive or sample.acs_alive
            if sample.t - t0 >= go_live_timeout:
                return LaunchVerdict.NEVER_LIVE
            if regressed:
                return LaunchVerdict.NEVER_LIVE
            if advanced and ready:
                live_since = sample.t
        else:
            if not sample.acs_alive:
                return LaunchVerdict.FROZE
            if regressed:
                # packetId reset means the render stream/session was replaced; never let a new
                # acs.exe inherit stability time accumulated by its predecessor.
                return LaunchVerdict.FROZE
            if not_ready:
                not_ready_run += 1
                if not_ready_run >= stall_samples:
                    return LaunchVerdict.FROZE
            elif ready:
                not_ready_run = 0
            else:
                # An unavailable graphics observation cannot extend a consecutive run.
                not_ready_run = 0
            if advanced:
                stall_run = 0
            elif sample.gfx_packet is not None and sample.gfx_packet == prev_packet:
                stall_run += 1
                if stall_run >= stall_samples:
                    return LaunchVerdict.FROZE
            else:
                # Missing shared memory is unknown, not another observation of the same packet.
                stall_run = 0
            if advanced and ready and sample.t - live_since >= stability_window:
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
    read_state: Callable[
        [],
        tuple[int | None, bool | None] | tuple[int | None, bool | None, bool | None],
    ],
    acs_alive: Callable[[], bool],
) -> Sample:  # pragma: no cover - rig-only
    # The Car0 handshake can block for up to five seconds. Read it first, then stamp process
    # liveness and time together: readiness is proven only when that handshake returns, so an
    # observation that completes after the go-live budget cannot be backdated into the budget or
    # shorten the stability window by the probe duration.
    state = read_state()
    observed_alive = acs_alive()
    observed_at = time.monotonic()
    if len(state) == 2:
        packet, entry_ready = state
        drivable = entry_ready
    else:
        packet, entry_ready, drivable = state
    return Sample(
        t=observed_at,
        gfx_packet=packet,
        acs_alive=observed_alive,
        entry_ready=entry_ready,
        drivable=drivable,
    )


def _process_running(image: str) -> bool:  # pragma: no cover - rig-only
    from tools.ac_harness.entry_launcher import running_process_ids

    try:
        return bool(running_process_ids(image, strict=True))
    except OSError as exc:
        _log(f"WARNING: process enumeration failed for {image}; treating it as running: {exc}")
        return True


def _strict_process_running(image: str) -> bool:  # pragma: no cover - rig-only
    """Return process presence without converting enumeration failure into a boolean."""
    from tools.ac_harness.entry_launcher import running_process_ids

    return bool(running_process_ids(image, strict=True))


def _make_process_liveness_probe(
    image: str,
    *,
    absent_confirmations: int = 2,
    process_ids: Callable[[str], Sequence[int]] | None = None,
) -> Callable[[], bool]:
    """Return a fail-closed process probe with consecutive absence confirmation."""
    if absent_confirmations < 1:
        raise ValueError("absent_confirmations must be >= 1")
    list_process_ids = process_ids
    if list_process_ids is None:
        from tools.ac_harness.entry_launcher import running_process_ids

        def strict_process_ids(name: str) -> Sequence[int]:
            return running_process_ids(name, strict=True)

        list_process_ids = strict_process_ids
    absent_run = 0
    seen_present = False

    def is_alive() -> bool:
        nonlocal absent_run, seen_present
        try:
            found = list_process_ids(image)
        except OSError as exc:
            absent_run = 0
            _log(f"WARNING: process enumeration failed for {image}; retaining ownership: {exc}")
            # Fail closed only after this probe has observed the process. Before the first real
            # sighting, inventing presence turns the next ordinary startup absence into a false
            # process-exit edge and makes classify() report NEVER_LIVE immediately.
            return seen_present
        if found:
            absent_run = 0
            seen_present = True
            return True
        if not seen_present:
            # Before the process has appeared, absence is ordinary launch startup—not a synthetic
            # one-sample "alive" grace that classify() could mistake for an early process exit.
            return False
        absent_run += 1
        return absent_run < absent_confirmations

    return is_alive


class _ResettableProcessLivenessProbe:
    """A process probe whose sighting/absence history can be scoped to one launch attempt."""

    def __init__(
        self,
        image: str,
        *,
        absent_confirmations: int = 2,
        process_ids: Callable[[str], Sequence[int]] | None = None,
    ) -> None:
        self.image = image
        self.absent_confirmations = absent_confirmations
        self.process_ids = process_ids
        self._probe: Callable[[], bool]
        self.reset()

    def reset(self) -> None:
        self._probe = _make_process_liveness_probe(
            self.image,
            absent_confirmations=self.absent_confirmations,
            process_ids=self.process_ids,
        )

    def __call__(self) -> bool:
        return self._probe()


def _ensure_cm_running(  # pragma: no cover - rig-only
    cm_exe: Path,
    *,
    timeout: float = 45.0,
    settle: float = 8.0,
    poll: float = 1.0,
    release_requested: Callable[[], bool] | None = None,
    process_running: Callable[[str], bool] | None = None,
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

    if release_requested is not None and release_requested():
        raise _OperatorRelease
    if not cm_exe.is_file():
        _log(f"WARNING: Content Manager executable not found: {cm_exe}")
        return False
    process_name = cm_exe.name
    probe = process_running or _strict_process_running
    try:
        already_running = probe(process_name)
    except OSError as exc:
        _log(f"WARNING: Content Manager process enumeration failed: {exc}")
        return False
    if already_running:
        return True
    _log("Content Manager not running — starting it before sending the quick-drive URL")
    if release_requested is not None and release_requested():
        raise _OperatorRelease
    try:
        subprocess.Popen([str(cm_exe)])
    except OSError as exc:
        _log(f"WARNING: Content Manager failed to start: {exc}")
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        try:
            observed_running = probe(process_name)
        except OSError as exc:
            _log(f"WARNING: Content Manager process enumeration failed after start: {exc}")
            return False
        if observed_running:
            settle_deadline = time.monotonic() + settle
            while time.monotonic() < settle_deadline:
                if release_requested is not None and release_requested():
                    raise _OperatorRelease
                remaining = settle_deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(poll, remaining))
            try:
                survived_settle = probe(process_name)
            except OSError as exc:
                _log(f"WARNING: Content Manager settle verification failed: {exc}")
                return False
            if survived_settle:
                return True
            _log("WARNING: Content Manager exited during startup settle")
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll, remaining))
    _log("WARNING: Content Manager did not start; the launch URL will not be honored")
    return False


def _wait_process_exit(  # pragma: no cover - rig-only
    image: str,
    *,
    timeout: float = 15.0,
    poll: float = 0.25,
    release_requested: Callable[[], bool] | None = None,
) -> bool:
    """Wait until a killed Windows process has left the table before reusing its IPC name."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        if not _process_running(image):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll, remaining))
    if release_requested is not None and release_requested():
        raise _OperatorRelease
    return not _process_running(image)


def _ensure_acs_gone(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    *,
    timeout: float = 15.0,
    poll: float = 1.0,
    release_requested: Callable[[], bool] | None = None,
) -> bool:
    """Kill any surviving ``acs.exe`` and wait until it has really left the process table.

    A wedged sim keeps its window and shared-memory section, so launching on top of it makes
    Content Manager's next start fail to reach LIVE. ``taskkill`` returning is not sufficient —
    the process can linger — so poll (bounded) until it is actually gone. The caller must abort
    rather than relaunch when this returns ``False``.
    """
    from tools.ac_harness.entry_launcher import terminate_process_tree_confirmed_absent

    if release_requested is not None and release_requested():
        raise _OperatorRelease

    def observe() -> bool:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        return acs_alive()

    safe = terminate_process_tree_confirmed_absent(
        "acs.exe",
        is_running=observe,
        timeout=timeout,
        poll=poll,
        absent_confirmations=2,
        clock=time.monotonic,
        sleep=time.sleep,
        log=lambda message: _log(f"acs.exe cleanup: {message}"),
    )
    if not safe:
        _log("ERROR: acs.exe absence could not be confirmed; relaunch aborted")
    return safe


def _hold_rig_until_acs_gone(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    *,
    retry_cleanup: Callable[[Callable[[], bool]], bool] | None = None,
    release_requested: Callable[[], bool] | None = None,
    poll: float = 1.0,
    allow_operator_release: bool = True,
    timeout: float | None = None,
) -> bool:
    """Keep machine-wide ownership after cleanup fails until the unsafe sim is gone.

    Returning from the launcher would release the OS lock and let a peer inherit a known-wedged
    ``acs.exe``. Keep retrying teardown while ownership is held. Ctrl-C is the only explicit
    operator escape hatch; as elsewhere in this launcher, it deliberately releases ownership.
    """
    _log(
        "UNSAFE RIG: acs.exe survived cleanup; retaining ownership and retrying "
        "(Ctrl-C explicitly releases)"
    )

    def cleanup() -> bool:
        if retry_cleanup is not None:
            return retry_cleanup(acs_alive)
        return _ensure_acs_gone(
            acs_alive,
            release_requested=release_requested if allow_operator_release else None,
        )

    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            _log("FATAL cleanup hold timed out; forcing process exit with rig lock retained")
            return False
        try:
            alive = acs_alive()
        except OSError as exc:
            _log(f"WARNING: acs.exe enumeration failed during cleanup hold: {exc}")
            alive = True
        if not alive:
            return True
        if allow_operator_release and release_requested is not None and release_requested():
            _log("Game Point explicitly released unsafe rig ownership; acs.exe may still be alive")
            return False
        try:
            cleaned = cleanup()
            if cleaned:
                try:
                    still_alive = acs_alive()
                except OSError as exc:
                    _log(f"WARNING: acs.exe cleanup confirmation failed: {exc}")
                    still_alive = True
                if not still_alive:
                    return True
            time.sleep(poll)
        except _OperatorRelease:
            if allow_operator_release:
                _log(
                    "Game Point explicitly released unsafe rig ownership; "
                    "acs.exe may still be alive"
                )
                return False
            _log("ignoring release during fatal controller cleanup; acs.exe must exit first")
            time.sleep(poll)
        except KeyboardInterrupt:
            if allow_operator_release:
                _log(
                    "operator explicitly released unsafe rig ownership; acs.exe may still be alive"
                )
                return False
            _log("ignoring Ctrl-C during fatal controller cleanup; acs.exe must exit first")
            time.sleep(poll)


def _hold_stable_session(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    release_requested: Callable[[], bool],
    *,
    poll: float = 1.0,
) -> bool:
    """Hold rig ownership for a stable session and report whether release was intentional."""
    try:
        while acs_alive() and not release_requested():
            time.sleep(poll)
    except KeyboardInterrupt:
        _log("operator released rig ownership; AC left LIVE")
        return True
    if release_requested():
        _log("Game Point explicitly released rig ownership; AC left LIVE")
        return True
    _log("ERROR: stable AC session exited without an operator release")
    return False


def _make_rig_safe(  # pragma: no cover - rig-only
    acs_alive: Callable[[], bool],
    *,
    release_requested: Callable[[], bool] | None = None,
    allow_operator_release: bool = True,
    hold_timeout: float | None = None,
) -> bool:
    """Attempt cleanup before allowing a release to drop machine-wide ownership."""
    # A pre-stability release reaches this path with its durable sentinel still present. Do not
    # pass that callback into the first cleanup: _ensure_acs_gone would raise before taskkill and
    # let a live/wedged acs.exe outlast the rig lock. Only the subsequent unsafe-hold loop treats
    # the sentinel as the operator's explicit escape hatch after one real teardown attempt.
    try:
        initially_alive = acs_alive()
    except OSError:
        initially_alive = True
    if not initially_alive:
        return True
    try:
        safe = _ensure_acs_gone(acs_alive)
    except (KeyboardInterrupt, _OperatorRelease):
        if allow_operator_release:
            raise
        _log("ignoring operator interrupt during fatal controller cleanup")
        safe = False
    if not safe:
        return _hold_rig_until_acs_gone(
            acs_alive,
            release_requested=release_requested,
            allow_operator_release=allow_operator_release,
            timeout=hold_timeout,
        )
    return True


def _run_with_safe_release(
    run: Callable[[], LaunchReport],
    acs_alive: Callable[[], bool],
    *,
    release_requested: Callable[[], bool] | None = None,
) -> LaunchReport:
    """Run the retry engine and make the rig safe before propagating any abnormal exit."""
    try:
        return run()
    except _OperatorRelease:
        # Release is only a safe "leave AC live" operation after the stability gate. During
        # retries, attempt cleanup first. The durable callback remains the no-console operator's
        # explicit escape hatch if taskkill cannot remove a wedged process.
        _make_rig_safe(acs_alive, release_requested=release_requested)
        raise
    except BaseException:
        _make_rig_safe(acs_alive, release_requested=release_requested)
        raise


def _probe_car0_drivable(  # pragma: no cover - Windows/rig-only
    *,
    timeout: float = 5.0,
    poll: float = 0.1,
    controller_factory: Callable[[], object] | None = None,
    release_requested: Callable[[], bool] | None = None,
) -> bool:
    """Briefly handshake CSP Car0, the established oracle for a drivable session (#466).

    Creating ``CarControls0`` asks CSP to expose ``Car0``. The known pre-drive overlay never does,
    despite LIVE/not-in-pit and advancing packets. Close immediately after the probe so control is
    returned to the human driver before the stability window continues.
    """
    from tools.ac_harness.shared_memory import SharedMemoryUnavailable

    controller: object | None = None
    drivable = False
    try:
        if release_requested is not None and release_requested():
            raise _OperatorRelease
        if controller_factory is None:
            from tools.ac_harness.custom_ai import CustomAIController

            controller = CustomAIController(0)
        else:
            controller = controller_factory()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if release_requested is not None and release_requested():
                raise _OperatorRelease
            if controller.read_car_data() is not None:  # type: ignore[attr-defined]
                drivable = True
                break
            if release_requested is not None and release_requested():
                raise _OperatorRelease
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(poll, remaining))
        else:
            if release_requested is not None and release_requested():
                raise _OperatorRelease
            drivable = controller.read_car_data() is not None  # type: ignore[attr-defined]
    except (SharedMemoryUnavailable, OSError) as exc:
        _log(f"Car0 drivability probe unavailable: {exc}")
        drivable = False
    finally:
        if controller is not None:
            try:
                controller.close()  # type: ignore[attr-defined]
            except (SharedMemoryUnavailable, OSError) as exc:
                raise _Car0ProbeCleanupError(
                    f"could not close Car0 drivability probe: {exc}",
                    controller,
                ) from exc
    return drivable


def _watch_live(  # pragma: no cover - rig-only
    read_state: Callable[
        [],
        tuple[int | None, bool | None] | tuple[int | None, bool | None, bool | None],
    ],
    acs_alive: Callable[[], bool],
    *,
    go_live_timeout: float,
    stability_window: float,
    poll_interval: float = 1.0,
) -> LaunchVerdict:
    """Sample until the attempt resolves, then classify. Streams samples into :func:`classify`."""
    samples: list[Sample] = []
    started_at = time.monotonic()
    deadline = started_at + go_live_timeout + stability_window + 30.0
    while time.monotonic() < deadline:
        samples.append(_sample_now(read_state, acs_alive))
        verdict = classify(
            samples,
            go_live_timeout=go_live_timeout,
            stability_window=stability_window,
            started_at=started_at,
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


def _publish_stable_phase(set_phase: Callable[[str], None]) -> bool:
    """Publish READY metadata without destroying an already-proven live session on I/O failure."""
    try:
        set_phase("stable")
    except OSError as exc:
        _log(
            "WARNING: could not publish stable rig phase; retaining the proven live session "
            f"under stabilizing ownership: {exc}"
        )
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only entrypoint
    parser = argparse.ArgumentParser(
        description="Launch AC, retry past the CSP init livelock (#619), hold a stable session"
    )
    parser.add_argument("--car", required=True, help="car id, e.g. ks_porsche_911_gt3_r_2016")
    parser.add_argument("--track", required=True, help="track id, e.g. spa")
    parser.add_argument("--layout", default=None, help="track layout for multi-layout circuits")
    parser.add_argument(
        "--cm-exe",
        type=Path,
        default=None,
        help="Content Manager.exe path (default: standard Program Files install)",
    )
    parser.add_argument(
        "--stability-window", type=_positive_float, default=DEFAULT_STABILITY_WINDOW
    )
    parser.add_argument("--go-live-timeout", type=_positive_float, default=DEFAULT_GO_LIVE_TIMEOUT)
    parser.add_argument("--max-attempts", type=_positive_int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--rig-lock-timeout",
        type=_non_negative_float,
        default=1.0,
        help="seconds to wait for the machine-wide rig lock (default: 1.0)",
    )
    parser.add_argument("--rig-lock-path", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--rig-release-path", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    from tools.ac_harness.entry_launcher import (
        ContentManagerActuator,
        EntryLaunchUnsupported,
    )
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

    acs_alive = _ResettableProcessLivenessProbe("acs.exe")

    def acs_present() -> bool:
        return _strict_process_running("acs.exe")

    lock_path = args.rig_lock_path or default_rig_session_lock_path()
    release_path = args.rig_release_path or (lock_path.parent / "rig-session.release")

    def release_requested() -> bool:
        return release_path.exists()

    rig_lock = RigSessionLock(
        lock_path,
        owner=RigSessionOwner(
            pid=os.getpid(),
            cwd=str(Path.cwd()),
            car=args.car,
            track=args.track,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            session_kind="resilient_launch",
            phase="stabilizing",
        ),
        timeout=args.rig_lock_timeout,
    )
    try:
        rig_lock.acquire()
    except RigSessionBusy as exc:
        _log(f"RIG BUSY — {exc}")
        return 3
    _log(f"rig lock acquired -> {rig_lock.path}")
    preset: Path | None = None
    try:
        if args.rig_release_path is None:
            try:
                release_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"WARNING: could not clear stale release request {release_path}: {exc}")
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

        cm_exe = args.cm_exe or ContentManagerActuator.DEFAULT_CM_EXE
        actuator = ContentManagerActuator(preset=preset, cm_exe=cm_exe)
        if not actuator.cm_exe.is_file():
            _log(f"launch aborted: Content Manager executable not found: {actuator.cm_exe}")
            return 1

        def watch_attempt(attempt: int) -> LaunchVerdict:
            if release_requested():
                raise _OperatorRelease
            _log(f"attempt {attempt}/{args.max_attempts}: launching via Content Manager")
            # A wedged acs from the previous attempt must be GONE before relaunching.
            if not _ensure_acs_gone(acs_present, release_requested=release_requested):
                raise _AcsCleanupTimeout("acs.exe remained alive after the bounded cleanup wait")
            # The previous attempt's real process sighting must not leak into the next attempt's
            # pre-spawn absence. Reset only AFTER cleanup has used that history to confirm the old
            # process is gone; this attempt then earns its own first real acs.exe sighting.
            acs_alive.reset()
            # The quick-drive URL is IPC to a RUNNING CM. Do not spend a full attempt when its
            # executable is absent or startup failed.
            if not _ensure_cm_running(
                actuator.cm_exe,
                release_requested=release_requested,
            ):
                return LaunchVerdict.NEVER_LIVE
            if release_requested():
                raise _OperatorRelease
            minimize_foreground_window()
            if release_requested():
                raise _OperatorRelease
            try:
                # Cleanup already normalized acs.exe above. Calling relaunch() here would add a
                # second uninterruptible taskkill window between the final release check and launch.
                actuator.launch()
            except (OSError, EntryLaunchUnsupported) as exc:
                _log(f"attempt {attempt}: Content Manager launch failed: {exc}")
                return LaunchVerdict.NEVER_LIVE
            car0_ready: bool | None = None

            def read_attempt_state() -> tuple[int | None, bool | None, bool | None]:
                nonlocal car0_ready
                if release_requested():
                    raise _OperatorRelease
                packet, entry_ready = read_state()
                if entry_ready is True and car0_ready is None:
                    car0_ready = _probe_car0_drivable(release_requested=release_requested)
                    if not car0_ready:
                        raise _Car0NotDrivable
                return packet, entry_ready, car0_ready if entry_ready is True else None

            try:
                verdict = _watch_live(
                    read_attempt_state,
                    acs_alive,
                    go_live_timeout=args.go_live_timeout,
                    stability_window=args.stability_window,
                )
            except _Car0NotDrivable:
                # CM did start a LIVE session; only the Car0 handoff failed. Treat this as a bad
                # rendered attempt so it cannot advance the stale-CM/never-live restart streak.
                verdict = LaunchVerdict.FROZE
            _log(f"attempt {attempt}: {verdict}")
            return verdict

        def cold_restart_cm() -> None:
            _log("two consecutive never_live — cold-restarting Content Manager (stale preset IPC)")
            if release_requested():
                raise _OperatorRelease
            actuator.restart_content_manager()
            if not _wait_process_exit(
                actuator.cm_exe.name,
                release_requested=release_requested,
            ):
                raise _ContentManagerRestartTimeout(
                    "Content Manager remained alive after the bounded shutdown wait"
                )

        try:
            report = _run_with_safe_release(
                lambda: run_retry_loop(
                    watch_attempt,
                    max_attempts=args.max_attempts,
                    on_never_live_streak=cold_restart_cm,
                ),
                acs_present,
                release_requested=release_requested,
            )
        except _OperatorRelease:
            _log("Game Point release interrupted launch; AC was made safe before ownership release")
            return 1
        except _Car0ProbeCleanupError as exc:
            _log(f"launch aborted: {exc}")
            # close() retained a native CarControls mapping. Normal return would run the finally
            # block and release the machine lock first; terminate the process so Windows closes
            # mapping and lock together. The exception retains the controller until that boundary.
            # Re-confirm AC teardown here even though _run_with_safe_release already attempted it:
            # this fatal boundary ignores both Game Point release and Ctrl-C, and cannot make
            # ownership available while a surviving acs.exe could inherit the stale mapping.
            _make_rig_safe(
                acs_present,
                allow_operator_release=False,
                hold_timeout=30.0,
            )
            os._exit(1)
        except _AcsCleanupTimeout as exc:
            _log(f"launch aborted: {exc}")
            return 1
        except _ContentManagerRestartTimeout as exc:
            _log(f"restart aborted: {exc}")
            return 1
        _log(report.summary())
        if not report.succeeded:
            # A FROZE terminal verdict deliberately leaves acs.exe alive so the watcher can
            # diagnose it. Once the attempt budget is exhausted, kill that corpse while the
            # machine-wide lock is still held; peers must never inherit a wedged sim.
            _make_rig_safe(acs_present, release_requested=release_requested)
            return 1

        phase_published = _publish_stable_phase(rig_lock.set_phase)

        # The stable session belongs to this operator-facing launcher until AC exits. Releasing
        # the cross-worktree lock immediately after the gate would let a peer harness kill the
        # human driver's live session. Ctrl-C is an explicit ownership release and leaves AC up.
        _log(
            "stable session handed to operator; holding rig ownership until AC exits "
            f"(Ctrl-C releases; phase={'stable' if phase_published else 'stabilizing'})"
        )
        return 0 if _hold_stable_session(acs_alive, release_requested) else 1
    finally:
        if preset is not None:
            try:
                preset.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(f"WARNING: could not remove generated preset {preset}: {exc}")
        try:
            release_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _log(f"WARNING: could not remove release request {release_path}: {exc}")
        rig_lock.release()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
