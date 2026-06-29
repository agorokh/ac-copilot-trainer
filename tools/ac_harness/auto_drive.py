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
    autonomous drive (racing_driver / ggv)     -> RACES any track: shifts gears, flat-out min-time
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
        --cm-preset "<.cmpreset>" --track spa --driver ggv --drive-seconds 360   # flat-out
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
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
    track_layout: str | None = None  # set for multi-layout tracks to match the launched layout
    ac_root: Path = field(default_factory=default_ac_root)
    cm_exe: Path | None = None
    sidecar_url: str = "ws://127.0.0.1:8765"
    # Drive. ``driver="racing"`` (default) follows fast_lane.ai's embedded speed profile with real
    # braking points + gear shifting (RacingDriver) — the car actually races (shifts through gears,
    # carries pace). ``driver="cruise"`` is the conservative ~50 km/h, 1st-gear lane-keeper
    # (LapDriver) for a guaranteed-clean slow lap when pace is not the point.
    driver: str = "racing"
    drive_seconds: float = 300.0
    pace: float = 0.9  # racing: fraction of the AI line's speed profile to target
    racing_max_speed_kmh: float = (
        240.0  # racing/ggv: cap (above any GT speed; lets it use top gears)
    )
    ggv_scale: float = 0.9  # ggv: safety margin on the min-time profile (flat-out * scale)
    target_speed_kmh: float = 55.0  # cruise only
    min_corner_speed_kmh: float = 30.0  # cruise only
    # Assertion.
    tap_seconds: float = 30.0
    wait_lap: bool = False
    strict: bool = False
    # Launch / hijack robustness (the early-LIVE race).
    max_launches: int = 3
    attempt_timeout: float = 75.0
    settle_seconds: float = 5.0
    hijack_timeout: float = 25.0
    hijack_attempts: int = 3  # recreate CarControls0 N times — beats the early-LIVE hijack race
    # Sim-death guard.
    sim_dead_seconds: float = 4.0
    skip_launch: bool = False


@dataclass
class DriveStats:
    """Outcome of the autonomous drive leg."""

    drove: bool = False
    laps: int = 0
    max_speed_kmh: float = 0.0
    max_gear_used: int = 0  # highest AC gear seen (encoding 2=1st); >2 proves real shifting
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
                f"top_gear={max(d.max_gear_used - 1, 0)} dist={d.total_distance_m:.0f}m "
                f"sim_dead={d.sim_dead}" + (f" reason={d.reason}" if d.reason else "")
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
    controller: Controller | None = None
    attempts = 1 if config.skip_launch else max(1, config.max_launches)
    launch_config = replace(config, max_launches=1)
    launched_once = config.skip_launch
    last_launch_error = ""
    for _ in range(attempts):
        if not config.skip_launch:
            ok, reason = launch(launch_config)
            if not ok:
                last_launch_error = reason
                continue
            launched_once = True
        controller = hijack(config)
        if controller is not None:
            break
        if config.skip_launch:
            break

    if controller is None:
        if not launched_once:
            return AutoDriveReport(
                ok=False,
                stage="launch",
                launched=False,
                error=last_launch_error or "sim never reached LIVE",
            )
        return AutoDriveReport(
            ok=False,
            stage="hijack",
            launched=not config.skip_launch,
            error="CSP did not accept the carcsw hijack",
        )

    stop = threading.Event()
    drive_task = asyncio.create_task(asyncio.to_thread(drive, controller, config, stop))
    stats = DriveStats(reason="drive did not run")
    seq_ok: bool | None = None
    counts: dict[str, int] = {}
    notes: list[str] = []
    error: str | None = None
    stage = "done"
    try:
        frames = await tap(
            config.sidecar_url, seconds=config.tap_seconds, wait_for_lap=config.wait_lap
        )
        result = evaluate_sequence(
            frames, strict_lifecycle=config.strict, require_lap=config.wait_lap
        )
        seq_ok = result.ok
        counts = dict(result.counts)
        notes = list(result.notes)
    except Exception as exc:  # noqa: BLE001 - surface any tap/eval failure as a FAIL report
        stage, error = "pipeline", f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        # Always stop the drive AND release the controller — even if the drive thread raised, the
        # control mmap (the carcsw hijack) must be released, or it leaks and keeps holding the car.
        try:
            stats = await drive_task
        except Exception as exc:  # noqa: BLE001 - drive thread crashed; record, don't leak
            stage = "drive"
            error = error or f"drive: {type(exc).__name__}: {exc}"
        finally:
            controller.close()

    # Success needs a clean pipeline AND a real drive that did not die mid-run: sim_dead can be set
    # after the car already passed the distance/speed thresholds (drove=True), so veto on it too.
    ok = bool(seq_ok) and stats.drove and not stats.sim_dead and error is None
    return AutoDriveReport(
        ok=ok,
        stage=stage,
        launched=not config.skip_launch,
        hijacked=True,
        drive=stats,
        sequence_ok=seq_ok,
        counts=counts,
        notes=notes,
        error=error,
    )


# ---------------------------------------------------------------------------
# Track racing-line resolution (pure).
# ---------------------------------------------------------------------------
def resolve_fast_lane(ac_root: Path, track_id: str, layout: str | None = None) -> Path:
    """Return the ``fast_lane.ai`` for ``track_id`` (optionally a specific ``layout``).

    A multi-layout track (e.g. Monza GP vs Junior) has one ``ai/fast_lane.ai`` per layout, and
    ``track_id`` alone does not say which layout the CM preset launched. Pass ``layout`` to select
    ``<track>/<layout>/ai/fast_lane.ai`` so the driven line matches the launched layout. Without it,
    a root-level ``ai/fast_lane.ai`` is used, else the first layout subdir is picked **and the
    ambiguity is the caller's to resolve** — set ``--track-layout`` for multi-layout tracks.

    Raises :class:`FileNotFoundError` if no matching fast_lane.ai exists.
    """
    root = ac_root / "content" / "tracks" / track_id
    if layout:
        chosen = root / layout / "ai" / "fast_lane.ai"
        if chosen.exists():
            return chosen
        raise FileNotFoundError(
            f"no fast_lane.ai for track {track_id!r} layout {layout!r}: {chosen}"
        )
    direct = root / "ai" / "fast_lane.ai"
    if direct.exists():
        return direct
    for found in sorted(root.glob("*/ai/fast_lane.ai")):
        return found
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
    packet_changes = 0
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
                if last_pkt is None:
                    last_pkt = p.packet_id
                elif p.packet_id != last_pkt:
                    last_pkt = p.packet_id
                    packet_changes += 1
                    last_change = now
            advancing = (
                packet_changes > 0 and last_change is not None and (now - last_change) <= 0.25
            )
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
    """Create CarControls0 and wait for CSP to create Car0 (the hijack landing), with retry.

    The early-LIVE race: CSP only creates Car0 once its Custom-AI subsystem is watching, and the
    act that triggers it is *creating* the CarControls0 section — so a creation that lands too early
    silently no-ops. We split ``hijack_timeout`` across ``hijack_attempts`` and **recreate** the
    section each attempt (close + new ``CustomAIController``) so a later creation re-triggers CSP.
    """
    from tools.ac_harness.custom_ai import CustomAIController

    attempts = max(1, config.hijack_attempts)
    per_attempt = config.hijack_timeout / attempts
    for _ in range(attempts):
        ctrl = CustomAIController(0)
        deadline = time.monotonic() + per_attempt
        while time.monotonic() < deadline:
            if ctrl.read_car_data() is not None:
                return ctrl
            time.sleep(0.1)
        ctrl.close()  # recreate the section next attempt to re-trigger the hijack
    return None


def generic_gt3_ggv():
    """The live-VERIFIED GT3 friction-circle (GGVModel), telemetry-free at call time.

    These are the values empirically fit from human GT3 laps for EPIC #154's frontier controller
    (#259, ``frontier-controller-ggv``) — the config that drove **clean AC-valid flying laps** at
    Magione (Stanley + this GGV = 95.3 s, ~216 km/h, zero teleports). They are car-representative
    for a GT3, so the QSS min-time profile sends straights flat-out and brakes on the friction
    circle, **without spinning**.

    The load-bearing correction (red-team #259, live-disproven aero-lateral): ``k_aero_lat`` MUST be
    0. Any aero-lateral grip term makes the profile carry too much speed into corners and the live
    GT3 spins out (k>=0.0003 → 96 s with teleports; even k=0.0001 spun). Braking grip RISES with
    speed instead (aero): ``ax_brake = 0.955 + 0.0214*v_ms`` g (~1.0 g @40, ~2.2 g @180 km/h) — the
    fixed ``brake_g=1.4`` it replaced braked far too early at speed.
    """
    from tools.ac_harness.ggv_profile import GGVModel

    return GGVModel(
        mu_lat_g=1.5,
        k_aero_lat=0.0,  # MUST be 0 — an aero-lateral term spins the GT3 out at speed (#259)
        brake_b0_g=0.955,
        brake_b1=0.0214,  # braking rises with speed (aero): ~1.0 g @40, ~2.2 g @180 km/h
        drive_b0_g=1.1,
        drive_b1=-0.0117,
        drive_min_g=0.35,
        ellipse_n=1.55,
        ay_cap_g=1.8,
        ax_brake_cap_g=3.4,
    )


def _build_driver(config: AutoDriveConfig, fast_line: list, speed_profile: list | None = None):
    """Construct the drive controller for ``config.driver`` (pure; CI-testable).

    ``ggv`` → flat-out: a generic-GT3 friction-circle min-time profile (``ggv_profile``) driven
    verbatim by :class:`racing_driver.RacingDriver` (``from_ggv_profile``) — sends straights in the
    top gears, brakes on the friction circle. ``racing`` → :class:`racing_driver.RacingDriver`
    following the AI line's embedded speed profile (gear shifting + pace, but only as fast as the
    stock AI line). ``cruise`` → :class:`lap_driver.LapDriver`, the ~50 km/h 1st-gear lane-keeper.
    All three expose the same ``step()``/``on_recovery()`` contract, so the rig loop is agnostic.
    """
    from tools.ac_harness.lap_driver import LapDriver

    if config.driver == "cruise":
        return LapDriver(
            fast_line,
            target_speed_kmh=config.target_speed_kmh,
            min_corner_speed_kmh=config.min_corner_speed_kmh,
        )
    if config.driver == "racing":
        from tools.ac_harness.racing_driver import RacingDriver

        if speed_profile is None:
            raise ValueError("racing driver requires a speed_profile from the track's fast_lane.ai")
        return RacingDriver(
            fast_line,
            speed_profile,
            pace=config.pace,
            max_speed_kmh=config.racing_max_speed_kmh,
        )
    if config.driver == "ggv":
        from tools.ac_harness.ggv_profile import ggv_speed_profile_from_model
        from tools.ac_harness.racing_driver import RacingDriver

        v_target, _summ = ggv_speed_profile_from_model(
            fast_line, generic_gt3_ggv(), v_top_kmh=config.racing_max_speed_kmh
        )
        v_target = [v * config.ggv_scale for v in v_target]
        return RacingDriver.from_ggv_profile(fast_line, v_target)
    raise ValueError(f"unknown driver {config.driver!r} (expected 'ggv', 'racing', or 'cruise')")


def rig_drive(  # pragma: no cover - rig-only
    controller: Controller, config: AutoDriveConfig, stop: threading.Event
) -> DriveStats:
    """Drive the selected controller over the track's fast_lane.ai until ``stop`` or sim-death.

    ``config.driver`` picks RacingDriver (default — shifts gears, carries pace) or the cruise
    LapDriver. Adds the sim-death guard: a frozen Car0 ``packet_id`` for ``sim_dead_seconds`` means
    ``acs.exe`` died, so we stop instead of spinning on stale telemetry and reporting a false drive.
    """
    from tools.ac_harness.ai_line import _horizontal, load_ai_line

    fast_path = resolve_fast_lane(config.ac_root, config.track_id, config.track_layout)
    line = load_ai_line(fast_path)
    speed_profile = None
    if config.driver == "racing":
        from tools.ac_harness.racing_driver import load_speed_profile

        speed_profile = load_speed_profile(fast_path)
    driver = _build_driver(config, line, speed_profile)
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
            stats.max_gear_used = max(stats.max_gear_used, int(cd["gear"]))
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
    p.add_argument(
        "--track-layout",
        default=None,
        help="layout subdir for multi-layout tracks (e.g. layout_gp)",
    )
    p.add_argument("--ac-root", type=Path, default=None, help="AC content root (Steam install)")
    p.add_argument("--cm-exe", type=Path, default=None, help="Content Manager.exe path")
    p.add_argument("--sidecar-url", default="ws://127.0.0.1:8765")
    p.add_argument(
        "--driver",
        choices=("ggv", "racing", "cruise"),
        default="racing",
        help="ggv = flat-out min-time (top gears, 200+); racing = AI-line pace (default); "
        "cruise = slow 1st-gear lane-keeper",
    )
    p.add_argument("--pace", type=float, default=0.9, help="racing: fraction of AI-line speed")
    p.add_argument("--ggv-scale", type=float, default=0.9, help="ggv: safety margin on min-time")
    p.add_argument("--max-speed", type=float, default=240.0, help="racing/ggv: speed cap (km/h)")
    p.add_argument("--drive-seconds", type=float, default=300.0)
    p.add_argument("--target-speed", type=float, default=55.0, help="cruise target speed (km/h)")
    p.add_argument("--min-corner", type=float, default=30.0, help="cruise min corner speed (km/h)")
    p.add_argument("--tap-seconds", type=float, default=30.0)
    p.add_argument("--wait-lap", action="store_true", help="assert a completed lap (real motion)")
    p.add_argument("--strict", action="store_true", help="require session+lap, enforce ordering")
    p.add_argument("--skip-launch", action="store_true", help="AC already LIVE; only hijack+drive")
    return p


def _config_from_args(args: argparse.Namespace) -> AutoDriveConfig:
    kwargs: dict[str, Any] = dict(
        cm_preset=args.cm_preset,
        track_id=args.track,
        track_layout=args.track_layout,
        cm_exe=args.cm_exe,
        sidecar_url=args.sidecar_url,
        driver=args.driver,
        pace=args.pace,
        ggv_scale=args.ggv_scale,
        racing_max_speed_kmh=args.max_speed,
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
