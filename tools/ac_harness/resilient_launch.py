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
``_minimize_foreground_window`` + a freshly generated deterministic preset). A prototype that
hand-rolled the ``acmanager://`` URL returned ``never_live`` repeatedly because it skipped the
foreground-minimize (CM's auto-start race loses when a window holds the desktop foreground) and
CM's stale-session cold-restart (#537/#558) — both are handled here.

The verdict logic is a **pure function** over sampled ``(t, gfx_packet, acs_alive)`` traces so it
is unit-tested off-rig with no Assetto Corsa present.
"""

from __future__ import annotations

import argparse
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

    STABLE = "stable"
    FROZE = "froze"
    NEVER_LIVE = "never_live"


@dataclass(frozen=True)
class Sample:
    """One observation of the sim's render liveness.

    ``gfx_packet`` is ``acpmf_graphics.packetId`` — it advances once per rendered frame, so a
    frozen render loop pins it while the process stays alive. ``None`` means the shared-memory
    section was not mapped (sim not up yet).
    """

    t: float
    gfx_packet: int | None
    acs_alive: bool


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
        return LaunchVerdict.NEVER_LIVE

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
            if advanced:
                live_since = sample.t
            elif sample.t - t0 >= go_live_timeout:
                return LaunchVerdict.NEVER_LIVE
        else:
            if not sample.acs_alive:
                return LaunchVerdict.FROZE
            if advanced:
                stall_run = 0
            elif sample.gfx_packet is not None and sample.gfx_packet == prev_packet:
                stall_run += 1
                if stall_run >= stall_samples:
                    return LaunchVerdict.FROZE
            if sample.t - live_since >= stability_window:
                return LaunchVerdict.STABLE
        if sample.gfx_packet is not None:
            prev_packet = sample.gfx_packet

    if live_since is None:
        return LaunchVerdict.NEVER_LIVE
    # Trace ended before the window elapsed and before any stall — not yet proven stable.
    return LaunchVerdict.FROZE if stall_run else LaunchVerdict.NEVER_LIVE


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
    froze = never_live = 0
    never_live_run = 0
    for attempt in range(1, max_attempts + 1):
        verdict = watch_attempt(attempt)
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
    return LaunchReport(LaunchVerdict.NEVER_LIVE, max_attempts, froze, never_live)


# --------------------------------------------------------------------------------------
# Rig side (Windows-only; imported lazily so the pure logic above stays unit-testable).
# --------------------------------------------------------------------------------------


def _log(msg: str) -> None:  # pragma: no cover - rig-only progress trace
    print(f"[resilient-launch {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _sample_now(
    read_packet: Callable[[], int | None], acs_alive: Callable[[], bool]
) -> Sample:  # pragma: no cover - rig-only
    return Sample(t=time.monotonic(), gfx_packet=read_packet(), acs_alive=acs_alive())


def _process_running(image: str) -> bool:  # pragma: no cover - rig-only
    import subprocess

    out = subprocess.run(
        ["tasklist", "/fi", f"imagename eq {image}"], capture_output=True, text=True
    ).stdout.lower()
    return image.lower() in out


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
    _log("Content Manager not running — starting it before sending the quick-drive URL")
    subprocess.Popen([str(cm_exe)])
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
    subprocess.run(["taskkill", "/im", "acs.exe", "/f"], capture_output=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not acs_alive():
            return
        time.sleep(poll)
    _log("WARNING: acs.exe still present after kill+wait; launching anyway")


def _watch_live(  # pragma: no cover - rig-only
    read_packet: Callable[[], int | None],
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
        samples.append(_sample_now(read_packet, acs_alive))
        verdict = classify(
            samples, go_live_timeout=go_live_timeout, stability_window=stability_window
        )
        # classify() returns NEVER_LIVE for "not yet decided" traces; only trust it once the
        # go-live budget is actually spent.
        decided = verdict in (LaunchVerdict.STABLE, LaunchVerdict.FROZE) or (
            samples[-1].t - samples[0].t >= go_live_timeout
        )
        if decided:
            return verdict
        time.sleep(poll_interval)
    return LaunchVerdict.FROZE


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - rig-only entrypoint
    parser = argparse.ArgumentParser(
        description="Launch AC, retry past the CSP init livelock (#619), hold a stable session"
    )
    parser.add_argument("--car", required=True, help="car id, e.g. ks_porsche_911_gt3_r_2016")
    parser.add_argument("--track", required=True, help="track id, e.g. spa")
    parser.add_argument("--layout", default=None, help="track layout for multi-layout circuits")
    parser.add_argument("--stability-window", type=float, default=DEFAULT_STABILITY_WINDOW)
    parser.add_argument("--go-live-timeout", type=float, default=DEFAULT_GO_LIVE_TIMEOUT)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument(
        "--preset-dir",
        default=None,
        help="where to write the generated .cmpreset (default: a temp dir)",
    )
    args = parser.parse_args(argv)

    import tempfile

    from tools.ac_harness.auto_drive import _minimize_foreground_window, build_practice_preset
    from tools.ac_harness.entry_launcher import ContentManagerActuator
    from tools.ac_harness.shared_memory import SharedMemoryReader, SharedMemoryUnavailable

    preset_dir = Path(args.preset_dir) if args.preset_dir else Path(tempfile.mkdtemp())
    preset_dir.mkdir(parents=True, exist_ok=True)
    preset = preset_dir / "resilient_launch.cmpreset"
    preset.write_text(
        build_practice_preset(args.car, args.track, start_type="START", layout=args.layout),
        encoding="utf-8",
    )
    _log(f"preset -> {preset}")

    # cm_exe=None -> ContentManagerActuator.DEFAULT_CM_EXE (standard install path).
    actuator = ContentManagerActuator(preset=preset, cm_exe=None)

    def read_packet() -> int | None:
        """Current ``acpmf_graphics.packetId``; ``None`` while the sim is not mapped."""
        try:
            reader = SharedMemoryReader(with_physics=False)
        except (SharedMemoryUnavailable, OSError):
            return None
        try:
            return reader.read_graphics().packet_id
        except (SharedMemoryUnavailable, OSError):
            return None
        finally:
            reader.close()

    def acs_alive() -> bool:
        import subprocess

        return (
            subprocess.run(
                ["tasklist", "/fi", "imagename eq acs.exe"], capture_output=True, text=True
            )
            .stdout.lower()
            .count("acs.exe")
            > 0
        )

    def watch_attempt(attempt: int) -> LaunchVerdict:
        _log(f"attempt {attempt}/{args.max_attempts}: launching via Content Manager")
        # A wedged acs from the previous attempt must be GONE before relaunching. Without this
        # the next attempt burns its whole go-live budget failing to start against the corpse and
        # reports a spurious never_live — observed live as an alternating froze/never_live cadence
        # that halved the effective attempt rate.
        _ensure_acs_gone(acs_alive)
        # The quick-drive URL is IPC to a RUNNING CM — a dead CM silently swallows every launch.
        _ensure_cm_running(ContentManagerActuator.DEFAULT_CM_EXE)
        _minimize_foreground_window()  # CM's auto-start race loses if a window holds foreground
        actuator.launch() if attempt == 1 else actuator.relaunch()
        verdict = _watch_live(
            read_packet,
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
    return 0 if report.succeeded else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
