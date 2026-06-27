"""One-command **autonomous** self-test (EPIC #154 Part G — the ``--drive`` composition).

``self_test.py`` (#236) asserts the live WS producer contract but does **not** itself drive the
car — its own docstring calls the carcsw lap "an optional follow-up step". So the only assertion
that needs real motion (``--wait-lap``) was never wired to anything that produces motion, and the
"hands-off L2" loop was only ever exercised by a human at the wheel or a throwaway ``.scratch``
script (Magione + Porsche only). This module closes that gap: it **composes the shipped harness
modules into the loop the EPIC claimed** —

    CM-URL launch (entry_launcher)            -> AC on track, non-elevated
    wait LIVE + settle                        -> CSP ready to accept the Custom-AI hijack
    carcsw hijack of car 0 (custom_ai)        -> retry / relaunch on the early-LIVE race
    autonomous drive (lap_driver + ai_line)   -> a real lap of ANY track, no human, in a thread
    tap the sidecar WS (sequence_probe)        -> assert the live coaching producer contract
    teardown

— **parametrized by car/track/preset**, so the same command drives any combo (the anti-overfit
property the EPIC needed and Magione-only verification never showed).

Two pieces of hard-won rig robustness are baked in (live-found 2026-06-27 on Imola/Mugello):

* **Hijack retry/relaunch.** CSP only creates the ``Car<N>`` read section once its Custom-AI
  subsystem is watching; creating ``CarControls0`` too soon after ``AC_STATUS`` flips LIVE loses
  the race and the hijack silently no-ops. We settle, retry the hijack, and relaunch on failure.
* **Sim-death detection (anti-false-green).** When ``acs.exe`` crashes the Car0 mmap freezes and
  ``read_car_data()`` returns the last frame forever — a parked car reported as "still driving".
  The drive loop watches the Car0 ``packet_id`` and stops on stagnation rather than spinning on
  stale data and reporting a false success.

Design split mirrors the rest of ``ac_harness``: :func:`run_auto_drive` is **pure orchestration**
with injectable ``launch`` / ``hijack`` / ``drive`` / ``tap`` seams, unit-tested off-sim with fakes
(no AC, no Windows); the rig wiring (:func:`rig_launch`, :func:`rig_hijack`, :func:`rig_drive`) is
``pragma: no cover`` and validated on the rig.

Run on the rig (loopback to a sidecar started by the daemon or by hand)::

    python -m tools.ac_harness.auto_drive \
        --cm-preset "<.cmpreset>" --track imola --wait-lap --drive-seconds 360
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tools.ac_harness.sequence_probe import evaluate_sequence, tap_frames


def default_ac_root() -> Path:
    """Default Steam Assetto Corsa content root (override with ``--ac-root``).

    Mirrors the hardcoded path :mod:`tools.ac_harness.daemon` already uses for ``acs.exe`` so
    programmatic and CLI callers agree; a non-standard Steam library is handled via ``--ac-root``.
    """
    return Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa")


@dataclass
class AutoDriveConfig:
    """Inputs for one autonomous drive+assert run, parametrized by car/track/preset."""

    cm_preset: Path
    track_id: str
    ac_root: Path = field(default_factory=default_ac_root)
    cm_exe: Path | None = None
    sidecar_url: str = "ws://127.0.0.1:8765"
    # Drive.
    drive_seconds: float = 300.0
    target_speed_kmh: float = 55.0
    min_corner_speed_kmh: float = 30.0
    # Assertion.
    tap_seconds: float = 30.0
    wait_lap: bool = False
    strict: bool = False
    # Launch / hijack robustness (the early-LIVE race).
    max_launches: int = 3
    attempt_timeout: float = 75.0
    settle_seconds: float = 5.0
    hijack_timeout: float = 25.0
    # Sim-death guard.
    sim_dead_seconds: float = 4.0
    skip_launch: bool = False


@dataclass
class DriveStats:
    """Outcome of the autonomous drive leg."""

    drove: bool = False
    laps: int = 0
    max_speed_kmh: float = 0.0
    total_distance_m: float = 0.0
    samples: int = 0
    sim_dead: bool = False
    reason: str = ""


@dataclass
class AutoDriveReport:
    """Structured result of one composed autonomous self-test run."""

    ok: bool
    stage: str  # launch | hijack | pipeline | done
    launched: bool = False
    hijacked: bool = False
    drive: DriveStats | None = None
    sequence_ok: bool | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        lines = [f"auto-drive: {'PASS' if self.ok else 'FAIL'} (stage={self.stage})"]
        lines.append(f"  launched: {self.launched}  hijacked: {self.hijacked}")
        if self.drive is not None:
            d = self.drive
            lines.append(
                f"  drive: drove={d.drove} laps={d.laps} max_speed={d.max_speed_kmh:.1f}km/h "
                f"dist={d.total_distance_m:.0f}m sim_dead={d.sim_dead}"
                + (f" reason={d.reason}" if d.reason else "")
            )
        if self.sequence_ok is not None:
            lines.append(f"  pipeline: {'ok' if self.sequence_ok else 'FAILED'}")
            if self.counts:
                lines.append(
                    "  frames: " + ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
                )
            for note in self.notes:
                lines.append(f"  note: {note}")
        if self.error:
            lines.append(f"  error: {self.error}")
        return "\n".join(lines)


class Controller(Protocol):
    """The subset of :class:`custom_ai.CustomAIController` the drive loop needs (test seam)."""

    def write_controls(self, gas: float, brake: float, steer: float, **kwargs: Any) -> None: ...
    def read_car_data(self) -> dict[str, object] | None: ...
    def teleport_to_pits(self) -> None: ...
    def close(self) -> None: ...


LaunchFn = Callable[[AutoDriveConfig], "tuple[bool, str]"]
HijackFn = Callable[[AutoDriveConfig], "Controller | None"]
DriveFn = Callable[[Controller, AutoDriveConfig, threading.Event], DriveStats]
TapFn = Callable[..., Awaitable[list[dict]]]


async def run_auto_drive(
    config: AutoDriveConfig,
    *,
    launch: LaunchFn,
    hijack: HijackFn,
    drive: DriveFn,
    tap: TapFn = tap_frames,
) -> AutoDriveReport:
    """Compose launch → hijack → (background drive) → WS assert → teardown into one report.

    The four legs are injectable so the orchestration is unit-testable with fakes — no AC, no
    Windows, no real sidecar. On the rig the defaults (:func:`rig_launch`, :func:`rig_hijack`,
    :func:`rig_drive`, :func:`tap_frames`) wire it to the live game.
    """
    if not config.skip_launch:
        ok, reason = launch(config)
        if not ok:
            return AutoDriveReport(ok=False, stage="launch", error=reason)

    controller = hijack(config)
    if controller is None:
        return AutoDriveReport(
            ok=False, stage="hijack", launched=True, error="CSP did not accept the carcsw hijack"
        )

    stop = threading.Event()
    drive_task = asyncio.create_task(asyncio.to_thread(drive, controller, config, stop))
    try:
        frames = await tap(
            config.sidecar_url, seconds=config.tap_seconds, wait_for_lap=config.wait_lap
        )
        result = evaluate_sequence(
            frames, strict_lifecycle=config.strict, require_lap=config.wait_lap
        )
        seq_ok: bool | None = result.ok
        counts = dict(result.counts)
        notes = list(result.notes)
        tap_error: str | None = None
    except Exception as exc:  # noqa: BLE001 - surface any tap/eval failure as a FAIL report
        seq_ok, counts, notes, tap_error = None, {}, [], f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        stats = await drive_task
        controller.close()

    ok = bool(seq_ok) and stats.drove and tap_error is None
    return AutoDriveReport(
        ok=ok,
        stage="done" if tap_error is None else "pipeline",
        launched=not config.skip_launch,
        hijacked=True,
        drive=stats,
        sequence_ok=seq_ok,
        counts=counts,
        notes=notes,
        error=tap_error,
    )


# ---------------------------------------------------------------------------
# Track racing-line resolution (pure).
# ---------------------------------------------------------------------------
def resolve_fast_lane(ac_root: Path, track_id: str) -> Path:
    """Return ``<ac_root>/content/tracks/<track>/ai/fast_lane.ai`` (root or first layout subdir).

    Raises :class:`FileNotFoundError` if no fast_lane.ai exists for the track.
    """
    root = ac_root / "content" / "tracks" / track_id
    direct = root / "ai" / "fast_lane.ai"
    if direct.exists():
        return direct
    for layout in sorted(root.glob("*/ai/fast_lane.ai")):
        return layout
    raise FileNotFoundError(f"no fast_lane.ai for track {track_id!r} under {root}")


# ---------------------------------------------------------------------------
# Rig wiring (Windows/AC only; not exercised by CI — validated on the rig).
# ---------------------------------------------------------------------------
def rig_launch(config: AutoDriveConfig) -> tuple[bool, str]:  # pragma: no cover - rig-only
    """Launch AC via the de-elevated Content-Manager URL and wait for the sim to go LIVE.

    Unlike the daemon's strict ``driving`` gate (which needs the car already moving — a
    chicken-and-egg for an autonomous launch), this waits only for LIVE + advancing physics, then
    the hijack+drive supplies the motion. Relaunches on the menu-skip race up to ``max_launches``.
    """
    from tools.ac_harness.entry_launcher import ContentManagerActuator

    actuator = ContentManagerActuator(preset=config.cm_preset, cm_exe=config.cm_exe)
    actuator.normalize_prior_state()
    for attempt in range(1, config.max_launches + 1):
        actuator.launch() if attempt == 1 else actuator.relaunch()
        if _wait_live(config.attempt_timeout):
            time.sleep(config.settle_seconds)  # let CSP arm Custom-AI before the hijack
            return True, f"LIVE after {attempt} launch attempt(s)"
    return False, f"sim never reached LIVE after {config.max_launches} attempt(s)"


def _wait_live(timeout: float) -> bool:  # pragma: no cover - rig-only
    """Poll AC shared memory until status is LIVE with advancing physics."""
    from tools.ac_harness.shared_memory import (
        AcGameStatus,
        SharedMemoryReader,
        SharedMemoryUnavailable,
    )

    deadline = time.monotonic() + timeout
    reader: SharedMemoryReader | None = None
    last_pkt: int | None = None
    last_change: float | None = None
    advancing_reads = 0
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if reader is None:
                try:
                    reader = SharedMemoryReader()
                except SharedMemoryUnavailable:
                    time.sleep(0.2)
                    continue
            try:
                g = reader.read_graphics()
                p = reader.read_physics()
            except SharedMemoryUnavailable:
                reader.close()
                reader = None
                time.sleep(0.2)
                continue
            if p is not None:
                if last_pkt is None or p.packet_id != last_pkt:
                    last_pkt = p.packet_id
                    last_change = now
            advancing = last_change is not None and (now - last_change) <= 0.25
            if g.status == AcGameStatus.LIVE and advancing:
                advancing_reads += 1
                if advancing_reads >= 5:
                    return True
            else:
                advancing_reads = 0
            time.sleep(0.05)
    finally:
        if reader is not None:
            reader.close()
    return False


def rig_hijack(config: AutoDriveConfig) -> Controller | None:  # pragma: no cover - rig-only
    """Create the CarControls0 section and wait for CSP to create Car0 (the hijack landing)."""
    from tools.ac_harness.custom_ai import CustomAIController

    ctrl = CustomAIController(0)
    deadline = time.monotonic() + config.hijack_timeout
    while time.monotonic() < deadline:
        if ctrl.read_car_data() is not None:
            return ctrl
        time.sleep(0.1)
    ctrl.close()
    return None


def rig_drive(  # pragma: no cover - rig-only
    controller: Controller, config: AutoDriveConfig, stop: threading.Event
) -> DriveStats:
    """Drive ``lap_driver`` over the track's fast_lane.ai until ``stop`` or sim-death.

    Mirrors :meth:`lap_driver.LapDriver.run` but adds the sim-death guard: a frozen Car0
    ``packet_id`` for ``sim_dead_seconds`` means ``acs.exe`` died, so we stop instead of spinning
    on stale telemetry and reporting a false drive.
    """
    from tools.ac_harness.ai_line import _horizontal, load_ai_line
    from tools.ac_harness.lap_driver import LapDriver

    line = load_ai_line(resolve_fast_lane(config.ac_root, config.track_id))
    driver = LapDriver(
        line,
        target_speed_kmh=config.target_speed_kmh,
        min_corner_speed_kmh=config.min_corner_speed_kmh,
    )
    stats = DriveStats()
    prev_plane: tuple[float, float] | None = None
    last_pkt: int | None = None
    last_pkt_change = time.monotonic()
    t0 = time.monotonic()
    try:
        while not stop.is_set() and time.monotonic() - t0 < config.drive_seconds:
            cd = controller.read_car_data()
            if not cd:
                time.sleep(0.02)
                continue
            pkt = cd.get("packet_id")
            if last_pkt is None or pkt != last_pkt:
                last_pkt = pkt  # type: ignore[assignment]
                last_pkt_change = time.monotonic()
            elif time.monotonic() - last_pkt_change > config.sim_dead_seconds:
                stats.sim_dead = True
                stats.reason = "Car0 packet_id stagnant (acs.exe died)"
                break
            frame = driver.step(
                cd["position"],
                cd["look"],
                cd["speed_kmh"],
                cd["rpm"],
                cd["gear"],
                time.monotonic() - t0,
            )
            if frame.needs_recovery:
                for _ in range(5):
                    controller.teleport_to_pits()
                    time.sleep(0.1)
                time.sleep(0.8)
                driver.on_recovery()
                continue
            controller.write_controls(
                frame.gas,
                frame.brake,
                frame.steer,
                gear_up=frame.gear_up,
                gear_dn=frame.gear_dn,
                autoclutch_on_start=True,
                autoclutch_on_change=True,
            )
            stats.samples += 1
            stats.max_speed_kmh = max(stats.max_speed_kmh, cd["speed_kmh"])
            plane = _horizontal(cd["position"])
            if prev_plane is not None:
                d = ((plane[0] - prev_plane[0]) ** 2 + (plane[1] - prev_plane[1]) ** 2) ** 0.5
                if d < 50:  # ignore teleport jumps
                    stats.total_distance_m += d
            prev_plane = plane
            if frame.lap_completed:
                stats.laps += 1
            time.sleep(0.012)
    finally:
        for _ in range(20):
            try:
                controller.write_controls(0.0, 0.6, 0.0)
            except Exception:  # noqa: BLE001 - sim may already be gone
                break
            time.sleep(0.03)
    stats.drove = stats.total_distance_m > 200 and stats.max_speed_kmh > 25
    return stats


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Composed autonomous self-test (#154 Part G): drive any car/track + assert"
    )
    p.add_argument("--cm-preset", required=True, type=Path, help="Quick Drive .cmpreset")
    p.add_argument("--track", required=True, help="AC track id (for the fast_lane.ai racing line)")
    p.add_argument("--ac-root", type=Path, default=None, help="AC content root (Steam install)")
    p.add_argument("--cm-exe", type=Path, default=None, help="Content Manager.exe path")
    p.add_argument("--sidecar-url", default="ws://127.0.0.1:8765")
    p.add_argument("--drive-seconds", type=float, default=300.0)
    p.add_argument("--target-speed", type=float, default=55.0)
    p.add_argument("--min-corner", type=float, default=30.0)
    p.add_argument("--tap-seconds", type=float, default=30.0)
    p.add_argument("--wait-lap", action="store_true", help="assert a completed lap (real motion)")
    p.add_argument("--strict", action="store_true", help="require session+lap, enforce ordering")
    p.add_argument("--skip-launch", action="store_true", help="AC already LIVE; only hijack+drive")
    return p


def _config_from_args(args: argparse.Namespace) -> AutoDriveConfig:
    kwargs: dict[str, Any] = dict(
        cm_preset=args.cm_preset,
        track_id=args.track,
        cm_exe=args.cm_exe,
        sidecar_url=args.sidecar_url,
        drive_seconds=args.drive_seconds,
        target_speed_kmh=args.target_speed,
        min_corner_speed_kmh=args.min_corner,
        tap_seconds=args.tap_seconds,
        wait_lap=args.wait_lap,
        strict=args.strict,
        skip_launch=args.skip_launch,
    )
    if args.ac_root is not None:
        kwargs["ac_root"] = args.ac_root
    return AutoDriveConfig(**kwargs)


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig-only CLI wiring
    args = _build_arg_parser().parse_args(argv)
    config = _config_from_args(args)
    report = asyncio.run(
        run_auto_drive(config, launch=rig_launch, hijack=rig_hijack, drive=rig_drive)
    )
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    import sys
    from pathlib import Path as _Path

    _repo_root = str(_Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
