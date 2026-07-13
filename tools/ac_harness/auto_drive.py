"""One-command **autonomous** self-test (EPIC #154 Part G — the ``--drive`` composition).

``self_test.py`` (#236) asserts the live WS producer contract but does **not** itself drive the
car — its own docstring calls the carcsw lap "an optional follow-up step". So the only assertion
that needs real motion (``--wait-lap``) was never wired to anything that produces motion, and the
"hands-off L2" loop was only ever exercised by a human at the wheel or a throwaway ``.scratch``
script (Magione + Porsche only). This module closes that gap: it **composes the shipped harness
modules into the loop the EPIC claimed** —

    preflight (content / CSP / CM / setup asserts)  -> fail fast, actionably (#459 Part B)
    CM-URL launch (entry_launcher)            -> AC on track, non-elevated
    wait LIVE + settle                        -> CSP ready to accept the Custom-AI hijack
    apply + verify car setup (sidecar WS)     -> the run drives the setup you asked for (#459 A)
    carcsw hijack of car 0 (custom_ai)        -> retry / relaunch on the early-LIVE race
    autonomous drive (racing_driver / ggv)     -> RACES any track: shifts gears, flat-out min-time
    tap the sidecar WS (sequence_probe)        -> assert the live coaching producer contract
    evidence bundle (report.json + HUD png)    -> proof any downstream task can point at (#459 C)
    teardown

— **parametrized by car/track/preset/setup**, so the same command drives any combo (the
anti-overfit property the EPIC needed and Magione-only verification never showed). With ``--car``
the Quick Drive ``.cmpreset`` is generated deterministically (fixed weather/time/track state — the
#154 Part-G determinism-lock preset); hand-authored presets remain supported via ``--cm-preset``.

Rig robustness baked in (live-found 2026-06-27 on Imola/Mugello; #459 Part D):

* **Hijack retry/relaunch.** CSP only creates the ``Car<N>`` read section once its Custom-AI
  subsystem is watching; creating ``CarControls0`` too soon after ``AC_STATUS`` flips LIVE loses
  the race and the hijack silently no-ops. We settle, retry the hijack, and relaunch on failure.
* **Sim-death detection (anti-false-green).** When ``acs.exe`` crashes the mmap freezes and reads
  return the last frame forever — a parked car reported as "still driving". The drive loop watches
  the **main ``acpmf_physics`` packet_id** (which advances every frame while the sim runs) and stops
  on stagnation. It deliberately does NOT watch the Car0 (Custom-AI) packet_id: CSP does not bump
  that every frame — it holds constant for a stationary car — so watching it falsely declared death
  4 s into a start-line spawn before the car ever moved (#459 review).
* **No-progress watchdog + recovery cap.** The drivers' own stuck detector requires commanded
  throttle above a floor, so a low-throttle stall never trips it (the 450–580 m practice-start
  stall, #459). A driver-agnostic watchdog recovers on "no forward progress for N seconds"
  regardless of throttle, recoveries are counted and capped, and a capped-out run FAILS honestly
  with the stall location instead of teleport-looping until the clock runs out.

Design split mirrors the rest of ``ac_harness``: :func:`run_auto_drive` is **pure orchestration**
with injectable ``launch`` / ``hijack`` / ``apply_setup`` / ``drive`` / ``tap`` seams, unit-tested
off-sim with fakes (no AC, no Windows); the rig wiring (:func:`rig_launch`, :func:`rig_hijack`,
:func:`rig_apply_setup`, :func:`rig_drive`) is ``pragma: no cover`` and validated on the rig.

Run on the rig (sidecar auto-started when none is listening)::

    python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track spa \
        --setup Realistic_BB_v3 --driver ggv --wait-lap
"""

from __future__ import annotations

import argparse
import asyncio
import configparser
import json
import math
import re
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC
from pathlib import Path
from typing import Any, Protocol

from tools.ac_harness.sequence_probe import evaluate_sequence, tap_frames


def default_ac_root() -> Path:
    """Default Steam Assetto Corsa content root (override with ``--ac-root``).

    Mirrors the hardcoded path :mod:`tools.ac_harness.daemon` already uses for ``acs.exe`` so
    programmatic and CLI callers agree; a non-standard Steam library is handled via ``--ac-root``.
    """
    return Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa")


def resolve_ac_user_dir(explicit: Path | None = None, *, home: Path | None = None) -> Path:
    """Resolve the AC user-data root (``Documents/Assetto Corsa``), OneDrive-redirect aware.

    On rigs with OneDrive Documents redirection the real folder is
    ``<home>/OneDrive/Documents/Assetto Corsa`` and the plain ``Documents`` variant does not exist
    (see the vault ``install-paths`` glossary node). Returns ``explicit`` verbatim when given;
    otherwise the first existing candidate, else the plain-Documents path (so the error message a
    later existence check produces names the conventional location).
    """
    if explicit is not None:
        return Path(explicit)
    base = home if home is not None else Path.home()
    candidates = (
        base / "Documents" / "Assetto Corsa",
        base / "OneDrive" / "Documents" / "Assetto Corsa",
    )
    for cand in candidates:
        if cand.is_dir():
            return cand
    return candidates[0]


@dataclass
class AutoDriveConfig:
    """Inputs for one autonomous drive+assert run, parametrized by car/track/preset/setup."""

    cm_preset: Path | None = None  # hand-authored preset; generated from --car/--track when None
    track_id: str = ""
    track_layout: str | None = None  # set for multi-layout tracks to match the launched layout
    car_id: str | None = None  # AC car id; enables preset generation + content preflight
    ac_root: Path = field(default_factory=default_ac_root)
    ac_user_dir: Path | None = None  # Documents/Assetto Corsa (auto-resolved when None)
    cm_exe: Path | None = None
    sidecar_url: str = "ws://127.0.0.1:8765"
    # Setup selection (#459 Part A). ``setup`` is a setup name (basename, no ``.ini``) or a path
    # under the user setups folder; ``setup_ini`` is the resolved absolute INI (filled by the CLI
    # via resolve_setup_ini). AC applies a car setup ONLY at car spawn, from ``race.ini`` — the
    # in-sim WS ``setup.load`` path is gated by ``ac.isCarResetAllowed()``, which is false for a
    # freshly-spawned autonomous car (live-found "must be in pits", Spa 2026-07-02). So the harness
    # BAKES the setup into ``race.ini`` (``_EXT_SETUP_FILENAME`` — CM's own key) and relaunches, and
    # VERIFIES it via ``acpmf_physics.fuel`` matching the setup's ``[FUEL] VALUE``. A verified setup
    # is required; otherwise the run FAILS at stage="setup" — no half-done run on the wrong setup.
    setup: str | None = None
    setup_ini: Path | None = None
    setup_fuel_tolerance_l: float = 2.5  # observed fuel within this of the setup's FUEL => applied
    setup_timeout: float = 20.0  # seconds to wait for acpmf_physics.fuel to confirm the bake
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
    # Stall recovery (#459 Part D).
    progress_stall_seconds: float = 10.0  # no forward progress for this long => recover
    max_recoveries: int = 6  # then FAIL honestly instead of teleport-looping
    # Keep driving this long past S/F after the lap frame so the trainer's async lap-archive writer
    # (#246/#249) finalizes lap 1's trace over the following frames before teardown; stopping at the
    # exact boundary loses the archive (#515 / the #305 "not followed by another lap" class).
    lap_finalize_grace_s: float = 8.0
    spawn_to_line: bool = True  # teleport onto the racing line when spawned off it (pit box)
    # Keep race.ini setup keys present during the CM launch window. CM regenerates race.ini while
    # launching; a short-lived Documents-only re-bake loop preserves the selected setup without
    # touching the AC/CSP install tree (#461 review). Must stay positive to avoid hot disk loops.
    setup_rebake_interval: float = 0.05
    # Assertion.
    tap_seconds: float = 30.0
    wait_lap: bool = False
    strict: bool = False
    # Launch / hijack robustness (the early-LIVE race plus CM's setup race.ini regeneration).
    # A setup run keeps race.ini re-baked through the CM launch window; if the session still fails
    # to become hijackable, the only recovery is a fresh launch cycle.
    max_launches: int = 5
    attempt_timeout: float = 75.0
    settle_seconds: float = 7.0  # let CSP arm Custom-AI before hijacking
    # Overlay fast-fail (#466). `_wait_live` reports LIVE the moment status==LIVE + physics advance,
    # but AC can sit at the NEW-UI "0 seconds" pre-drive overlay WITH LIVE status and advancing
    # physics when CM's auto-start race loses — LIVE but NOT drivable. The carcsw hijack (CSP
    # creating Car0) is the only deterministic "session is actually drivable" signal, so each hijack
    # attempt is a SHORT probe: a stalled overlay is detected in `hijack_probe_seconds` and the
    # cycle recycles a fresh launch instead of burning one long ~25 s dead-wait. 5 s is generous for
    # a hijackable session: in-sim (#482), Car0 lands within ~1-2 s of creating CarControls0 on a
    # non-overlay launch (probe 1/3), so a shorter probe does not tear down healthy rigs. CLI-
    # validated finite & > 0 (a non-finite probe would never expire — see `_positive_float`).
    hijack_probe_seconds: float = 5.0
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
    recoveries: int = 0  # stuck/no-progress recoveries taken (capped by max_recoveries)
    recovery_capped: bool = False  # True when max_recoveries was exhausted (vetoes success)
    spawn_teleport: str = ""  # "" (not attempted) | "ok" | "failed" | "skipped (on line)"
    reason: str = ""


def drive_leg_succeeded(stats: DriveStats | None) -> bool:
    """Pure verdict on the drive leg — the motion half of :func:`run_auto_drive`'s success gate.

    True only when the car really drove and no veto fired. Each False case is a real #528-class
    failure that MUST stay caught (never leaked into a green report):

    * ``stats is None`` — the hijack never landed, so no drive leg ran at all.
    * ``not stats.drove`` — the car never cleared the distance/speed floor (a pit-start stall that
      never moves reads ``drove=False`` at 0 m).
    * ``stats.sim_dead`` — ``acs.exe`` died mid-run; the totals are stale (#459/#460).
    * ``stats.recovery_capped`` — the car kept stalling until the recovery cap; it never sustained
      progress whatever the totals say (the pit-start recovery-cap stall, #528).

    :func:`run_auto_drive` composes this with the pipeline verdict and error state; the false-green
    KPI corpus (`false_green_kpi.py`) exercises it directly, so dropping a veto here surfaces as a
    leaked broken scenario rather than a silent false green.
    """
    return bool(stats) and stats.drove and not stats.sim_dead and not stats.recovery_capped


def should_try_line_teleport_on_recovery(
    *, spawn_to_line_enabled: bool, car_off_line: bool, line_teleport_known_good: bool
) -> bool:
    """Whether a no-progress recovery should attempt the racing-line teleport before falling back
    to ``teleport_to_pits``.

    ``spawn_to_line_enabled`` is ``config.spawn_to_line``: ``--no-spawn-line`` opts out of
    racing-line teleports entirely (use the OUT-phase pit exit), so recovery must NEVER teleport
    onto the line when it is false — regardless of off-line state (codex on #539).

    Otherwise: a car that is OFF the racing line is stuck *because* it is off the line —
    ``teleport_to_pits`` returns it to (or leaves it in) the pit box, so every recovery is spent
    at 0 m and the run caps out honestly but needlessly (the pit-start stall, #528).
    ``car_off_line`` is true at an off-line spawn (pit box / offset grid slot) AND after any
    recovery that teleported the car back to the pits — itself off-line, so a mid-lap spin
    recovered to the pits would otherwise re-enter the same loop. Attempt the line teleport
    whenever the car is off-line — even if an earlier attempt missed the 25 m read-back, because
    :func:`_teleport_onto_line` re-reads position and retargets each call so a later one can
    land — or whenever a prior line teleport is known to have landed. Only when the car is on the
    line and no line teleport is known good is ``teleport_to_pits`` the correct reset.
    """
    if not spawn_to_line_enabled:
        return False
    return line_teleport_known_good or car_off_line


@dataclass
class AutoDriveReport:
    """Structured result of one composed autonomous self-test run."""

    ok: bool
    stage: str  # preflight | launch | hijack | setup | pipeline | drive | done
    launched: bool = False
    hijacked: bool = False
    drive: DriveStats | None = None
    sequence_ok: bool | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    # Whether the post-lap grace-drive ran (drove past S/F so the async writer finalizes the lap
    # archive). The single source of truth the evidence-bundle poll gates on, so the grace condition
    # and the poll condition can never diverge (#515/#516 review).
    lap_grace_applied: bool = False
    # Combo identity + setup verification (#459 Parts A/C) — evidence consumers key on these.
    car_id: str | None = None
    track_id: str | None = None
    setup_requested: str | None = None
    setup_applied: bool | None = None  # None = no setup requested
    setup_ack: dict | None = None  # the in-sim `setup.load.ack` (name/path/error)

    def summary(self) -> str:
        lines = [f"auto-drive: {'PASS' if self.ok else 'FAIL'} (stage={self.stage})"]
        combo = " ".join(
            part
            for part in (
                f"car={self.car_id}" if self.car_id else "",
                f"track={self.track_id}" if self.track_id else "",
            )
            if part
        )
        if combo:
            lines.append(f"  combo: {combo}")
        lines.append(f"  launched: {self.launched}  hijacked: {self.hijacked}")
        if self.setup_requested is not None:
            ack_path = (self.setup_ack or {}).get("path")
            ack_err = (self.setup_ack or {}).get("error")
            detail = f" path={ack_path}" if ack_path else (f" error={ack_err}" if ack_err else "")
            lines.append(
                f"  setup: requested={self.setup_requested} applied={self.setup_applied}{detail}"
            )
        if self.drive is not None:
            d = self.drive
            lines.append(
                f"  drive: drove={d.drove} laps={d.laps} max_speed={d.max_speed_kmh:.1f}km/h "
                f"top_gear={max(d.max_gear_used - 1, 0)} dist={d.total_distance_m:.0f}m "
                f"recoveries={d.recoveries} sim_dead={d.sim_dead}"
                + (f" spawn_teleport={d.spawn_teleport}" if d.spawn_teleport else "")
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

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the evidence bundle (``report.json``)."""
        return asdict(self)


class Controller(Protocol):
    """The subset of :class:`custom_ai.CustomAIController` the drive loop needs (test seam)."""

    def write_controls(self, gas: float, brake: float, steer: float, **kwargs: Any) -> None: ...
    def read_car_data(self) -> dict[str, object] | None: ...
    def teleport_to_pits(self) -> None: ...
    def close(self) -> None: ...


LaunchFn = Callable[[AutoDriveConfig], "tuple[bool, str]"]
HijackFn = Callable[[AutoDriveConfig], "Controller | None"]
ApplySetupFn = Callable[[AutoDriveConfig], Awaitable[dict]]
DriveFn = Callable[[Controller, AutoDriveConfig, threading.Event], DriveStats]
TapFn = Callable[..., Awaitable[list[dict]]]


def verify_setup_ack(ack: dict | None, requested: str) -> tuple[bool, str]:
    """Pure check that a setup ack confirms the requested setup was applied AND verified.

    ``requested`` is the setup stem (basename without ``.ini``). The ack must carry ``ok=true``
    (the rig leg sets this only when the observed fuel matched the setup's ``FUEL``) AND name (or
    the ack path's basename) matching the request — an ``ok`` for a *different* setup (same-basename
    collision across folders) must not verify.
    """
    if not isinstance(ack, dict):
        return False, "no setup ack received"
    if ack.get("ok") is not True:
        return False, str(ack.get("error") or "setup not applied")
    want = requested.lower()
    name = str(ack.get("name") or "").lower()
    path = str(ack.get("path") or "")
    path_stem = re.sub(r"\.ini$", "", path.replace("\\", "/").rsplit("/", 1)[-1]).lower()
    if name == want or path_stem == want:
        detail = ack.get("detail") or f"applied {ack.get('path') or ack.get('name')}"
        return True, str(detail)
    return False, f"ack names a different setup: name={ack.get('name')!r} path={path!r}"


class ProgressWatchdog:
    """No-forward-progress detector — driver-agnostic stall recovery trigger (#459 Part D).

    The drivers' own stuck detectors require ``gas > stuck_throttle`` (they mean "spinning against
    a wall"), so a stall where the controller commands near-zero throttle — over-slowed corner,
    neutral-drop, geometry trap — never recovers. This watchdog only asks "did the car move?":
    fewer than ``min_progress_m`` metres of accumulated distance for ``stall_seconds`` seconds
    means stalled, regardless of what the controller thinks it is doing. Pure and CI-tested.
    """

    def __init__(self, *, stall_seconds: float, min_progress_m: float = 1.0) -> None:
        if stall_seconds <= 0:
            raise ValueError("stall_seconds must be > 0")
        if min_progress_m <= 0:
            raise ValueError("min_progress_m must be > 0")
        self.stall_seconds = stall_seconds
        self.min_progress_m = min_progress_m
        self._anchor_distance_m: float | None = None
        self._anchor_time: float | None = None

    def update(self, total_distance_m: float, now: float) -> bool:
        """Feed the accumulated drive distance; True when the car has stalled."""
        if (
            self._anchor_distance_m is None
            or self._anchor_time is None
            or total_distance_m - self._anchor_distance_m >= self.min_progress_m
        ):
            self._anchor_distance_m = total_distance_m
            self._anchor_time = now
            return False
        return now - self._anchor_time >= self.stall_seconds

    def reset(self, now: float, total_distance_m: float) -> None:
        """Re-anchor after a recovery so the teleport itself is not read as a second stall."""
        self._anchor_distance_m = total_distance_m
        self._anchor_time = now


def _has_timed_lap(frames: list[dict]) -> bool:
    """True if a produced ``lap`` snapshot carries a positive time (``payload.last_lap_ms > 0``).

    An out-lap / teleport boundary still emits a ``lap`` frame but with no time, and the trainer
    only archives a TIMED lap (``lastMs > 0``). So the post-lap grace-drive + archive poll must fire
    on a timed lap, not merely on a ``lap`` frame, or an unarchiveable boundary wastes the grace and
    then times out the poll (#516 review).
    """
    for frame in frames:
        if (
            not isinstance(frame, dict)
            or frame.get("type") != "state.snapshot"
            or frame.get("topic") != "lap"
        ):
            continue
        payload = frame.get("payload")
        ms = payload.get("last_lap_ms") if isinstance(payload, dict) else None
        try:
            if ms is not None and float(ms) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


async def run_auto_drive(
    config: AutoDriveConfig,
    *,
    launch: LaunchFn,
    hijack: HijackFn,
    drive: DriveFn,
    tap: TapFn = tap_frames,
    apply_setup: ApplySetupFn | None = None,
) -> AutoDriveReport:
    """Compose launch → setup → hijack → (background drive) → WS assert → teardown into one report.

    The legs are injectable so the orchestration is unit-testable with fakes — no AC, no
    Windows, no real sidecar. On the rig the defaults (:func:`rig_launch`, :func:`rig_hijack`,
    :func:`rig_apply_setup`, :func:`rig_drive`, :func:`tap_frames`) wire it to the live game.

    When ``config.setup`` is set and ``apply_setup`` is provided, the setup is applied and
    verified **before the carcsw hijack**: live-observed (Spa, 2026-07-02) that CSP keeps
    ``ac.isCarResetAllowed()`` false while a Custom-AI controller holds the car, so a
    post-hijack ``setup.load`` is refused with "must be in pits" even in the pit box. The
    setup re-applies on every relaunch (a relaunch is a fresh session). An unverified setup
    FAILS the run at ``stage="setup"`` — driving with the wrong setup is the "half-done run"
    this exists to prevent (#459 Part A).
    """
    identity = dict(car_id=config.car_id, track_id=config.track_id or None)
    setup_requested = Path(config.setup).stem if config.setup else None
    setup_ack: dict | None = None
    setup_applied: bool | None = None
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
        # The setup is BAKED at launch (AC only applies setups at spawn; the WS load is gated shut
        # for an autonomous car). Verify it BEFORE the hijack — the fuel read needs no hijack, and
        # a wrong setup must fail the run before it drives (#459 Part A). On a relaunch the launch
        # leg re-bakes, so this re-verifies each attempt.
        if config.setup:
            if apply_setup is None:
                return AutoDriveReport(
                    ok=False,
                    stage="setup",
                    launched=not config.skip_launch,
                    setup_requested=setup_requested,
                    setup_applied=False,
                    error="setup requested but no apply_setup leg wired",
                    **identity,
                )
            try:
                setup_ack = await apply_setup(config)
            except Exception as exc:  # noqa: BLE001 - a setup-leg crash is a run FAIL
                return AutoDriveReport(
                    ok=False,
                    stage="setup",
                    launched=not config.skip_launch,
                    setup_requested=setup_requested,
                    setup_applied=False,
                    error=f"setup verify failed: {type(exc).__name__}: {exc}",
                    **identity,
                )
            ok_setup, detail = verify_setup_ack(setup_ack, setup_requested)
            setup_applied = ok_setup
            if not ok_setup:
                return AutoDriveReport(
                    ok=False,
                    stage="setup",
                    launched=not config.skip_launch,
                    setup_requested=setup_requested,
                    setup_applied=False,
                    setup_ack=setup_ack,
                    error=f"setup not applied: {detail}",
                    **identity,
                )
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
                **identity,
            )
        return AutoDriveReport(
            ok=False,
            stage="hijack",
            launched=not config.skip_launch,
            setup_requested=setup_requested,
            setup_applied=setup_applied,
            setup_ack=setup_ack,
            error="CSP did not accept the carcsw hijack",
            **identity,
        )

    stop = threading.Event()
    # The tap waits up to `lap_deadline` for the lap (a full lap at harness pace can exceed 180s /
    # drive_seconds — Spa ~7km). The drive thread self-terminates on its own drive_seconds budget
    # and BRAKES the car on exit, so to keep it driving through the post-lap grace it must outlive
    # the LATEST lap the tap accepts PLUS the grace — not merely drive_seconds (which can be < the
    # tap deadline, breaking headroom for a late lap; #515/#516). One `lap_deadline` feeds both the
    # tap timeout and the drive budget so they cannot diverge.
    # tap_frames waits in TWO phases: up to `tap_settle_s` for the car-on-track (any continuous
    # topic), THEN up to lap_deadline for the lap. So the tap can accept a lap as late as
    # tap_settle_s + lap_deadline, and the drive thread must outlive that whole window + grace (it
    # brakes on budget exit; a premature stop leaves the tap hanging on a stopped car, #515/#516).
    # One tap_settle_s + lap_deadline feeds BOTH the tap and the budget so they cannot diverge.
    tap_settle_s = 120.0  # matches tap_frames' default settle_timeout
    lap_deadline = max(180.0, config.drive_seconds)
    drive_config = config
    if config.wait_lap:
        drive_config = replace(
            config,
            drive_seconds=tap_settle_s + lap_deadline + config.lap_finalize_grace_s,
        )
    drive_task = asyncio.create_task(asyncio.to_thread(drive, controller, drive_config, stop))
    stats = DriveStats(reason="drive did not run")
    seq_ok: bool | None = None
    counts: dict[str, int] = {}
    notes: list[str] = []
    grace_applied = False
    # A fuel-less setup is baked but not fuel-confirmed — surface that in the report so a setup
    # A/B run does not read `setup_applied=True` as "independently verified" (#460 review).
    if setup_ack is not None and setup_applied and setup_ack.get("expected_fuel") is None:
        notes.append(f"setup baked but UNCONFIRMED: {setup_ack.get('detail', 'no fuel key')}")
    error: str | None = None
    stage = "done"
    try:
        tap_kwargs: dict[str, Any] = dict(seconds=config.tap_seconds, wait_for_lap=config.wait_lap)
        if config.wait_lap:
            # The SAME settle + lap deadline the drive budget is sized to (above), so the tap never
            # waits past what the drive thread can still drive (a full lap at pace can exceed
            # the 180 s default, Spa ~7 km); #459 F / #516.
            tap_kwargs["settle_timeout"] = tap_settle_s
            tap_kwargs["lap_timeout"] = lap_deadline
        frames = await tap(config.sidecar_url, **tap_kwargs)
        result = evaluate_sequence(
            frames, strict_lifecycle=config.strict, require_lap=config.wait_lap
        )
        seq_ok = result.ok
        counts = dict(result.counts)
        notes = list(result.notes)
        grace_applied = bool(
            config.wait_lap and _has_timed_lap(frames) and config.lap_finalize_grace_s > 0
        )
        if grace_applied:
            # The drive thread is still running here (stop not yet set), so the car keeps driving
            # past S/F while the trainer's async writer (#246/#249) streams + finalizes lap 1's
            # archive over the following frames. Without this, stopping at the exact lap boundary
            # loses the trace (#515 / the #305 "not followed by another lap" class). The evidence
            # poll gates on report.lap_grace_applied, this exact boolean, so the two never diverge.
            await asyncio.sleep(config.lap_finalize_grace_s)
    except Exception as exc:  # noqa: BLE001 - surface any tap/eval failure as a FAIL report
        stage, error = "pipeline", f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        # Always stop the drive AND release the controller — even if the drive thread raised, the
        # control mmap (the carcsw hijack) must be released, or it leaks and keeps holding the car.
        try:
            stats = await drive_task
        except Exception as exc:  # noqa: BLE001 - drive thread crashed; record, don't leak
            drive_error = f"drive: {type(exc).__name__}: {exc}"
            if error is None:
                stage, error = "drive", drive_error
            else:
                # Dual failure (tap AND drive both raised): keep the first stage/error pair
                # coherent and surface the drive crash in notes instead of dropping it.
                notes.append(drive_error)
        finally:
            controller.close()

    # Success needs a clean pipeline AND a real drive that did not die mid-run or stall out. The
    # drive-leg vetoes (drove / sim_dead / recovery_capped) live in drive_leg_succeeded so this gate
    # and the false-green KPI corpus that exercises them cannot drift apart (#528).
    ok = bool(seq_ok) and drive_leg_succeeded(stats) and error is None
    return AutoDriveReport(
        ok=ok,
        stage=stage,
        launched=not config.skip_launch,
        hijacked=True,
        drive=stats,
        sequence_ok=seq_ok,
        lap_grace_applied=grace_applied,
        counts=counts,
        notes=notes,
        error=error,
        setup_requested=setup_requested,
        setup_applied=setup_applied,
        setup_ack=setup_ack,
        **identity,
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
# Setup resolution (pure; #459 Part A).
# ---------------------------------------------------------------------------
# Setup names become filesystem paths under the user setups root — allow only benign filename
# characters and reject traversal outright (this repo already shipped one path-injection bug;
# see the #459 pitfall list).
_SETUP_NAME_RE = re.compile(r"^[A-Za-z0-9 ._()\[\]-]+$")
# AC content ids (car/track/layout) are folder basenames; they also become path segments under
# the setups root and the evidence-dir name, so reject anything that is not a plain id.
_AC_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_ac_id(kind: str, value: str) -> str:
    """Reject a car/track/layout id that could act as a path (separator, ``..``, drive colon)."""
    if not value or ".." in value or not _AC_ID_RE.match(value):
        raise ValueError(f"unsafe {kind} id {value!r} (allowed: letters/digits/._-)")
    return value


def resolve_setup_ini(
    user_dir: Path,
    car_id: str,
    track_id: str,
    setup: str,
    *,
    layout: str | None = None,
) -> Path:
    """Resolve a setup name (or user-setups-relative path) to the setup INI on disk.

    Name resolution mirrors AC's own picker precedence for the active combo:
    ``<setups>/<car>/<track>/<layout>/<name>.ini`` (when ``layout``), then
    ``<setups>/<car>/<track>/<name>.ini``, then the track-agnostic ``<car>/generic/`` and
    ``<car>/`` folders. An input containing a path separator (or ending in ``.ini``) is treated
    as a path and must resolve **inside** the user setups root (containment check — no traversal).

    Raises :class:`FileNotFoundError` naming every location searched, or :class:`ValueError` for
    an unsafe name/path.
    """
    setups_root = (user_dir / "setups").resolve()
    validate_ac_id("car", car_id)
    validate_ac_id("track", track_id)
    if layout:
        validate_ac_id("layout", layout)
    raw = setup.strip()
    if not raw:
        raise ValueError("setup name is empty")

    # Only a string with a path SEPARATOR is treated as a path — a bare ``Foo.ini`` basename (which
    # an operator naturally copies from disk) goes through the same car/track/generic name search
    # as ``Foo``, not a setups-root-relative path that skips the combo folders (#460 review).
    looks_like_path = any(sep in raw for sep in ("/", "\\"))
    if looks_like_path:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = setups_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(setups_root)
        except ValueError:
            raise ValueError(
                f"setup path must live under the user setups folder {setups_root}: {resolved}"
            ) from None
        if not resolved.is_file():
            raise FileNotFoundError(f"setup ini not found: {resolved}")
        return resolved

    if ".." in raw or not _SETUP_NAME_RE.match(raw):
        raise ValueError(f"unsafe setup name {raw!r} (allowed: letters/digits/space/._()[]-)")
    name = raw if raw.lower().endswith(".ini") else f"{raw}.ini"
    car_root = setups_root / car_id
    candidates: list[Path] = []
    if layout:
        candidates.append(car_root / track_id / layout / name)
    candidates.append(car_root / track_id / name)
    candidates.append(car_root / "generic" / name)
    candidates.append(car_root / name)
    for cand in candidates:
        if cand.is_file():
            return cand
    searched = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"setup {raw!r} not found for {car_id} @ {track_id}; searched:\n  {searched}"
    )


# ---------------------------------------------------------------------------
# Launch-time setup baking + fuel verification (pure; #459 Part A — the mechanism that
# actually applies a setup to an autonomous car, since AC only applies setups at spawn).
# ---------------------------------------------------------------------------
def bake_setup_into_race_ini(
    race_ini_text: str, setup_ini: Path, *, spawn_set: str = "START"
) -> str:
    """Return ``race_ini_text`` with the setup baked under ``[CAR_0]`` and the spawn set.

    Writes both ``_EXT_SETUP_FILENAME=<abs path>`` (Content Manager's own key; what CM writes when
    a setup is chosen) and vanilla ``SETUP=<name>.ini`` so either code path in acs applies it, plus
    ``[SESSION_0] SPAWN_SET`` (``START`` puts the car on the racing line where the drivers work; a
    pit-box spawn is not needed because the setup applies at spawn regardless). Pure text transform
    via ``configparser`` — the caller writes the result and relaunches acs so the car spawns with
    the setup. Live-verified (Spa 2026-07-02): AC logs ``Setup change ... SPRING_RATE_RR ...`` and
    ``acpmf_physics.fuel`` reads the setup's ``FUEL`` value.
    """
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str  # preserve AC's uppercase keys
    parser.read_string(race_ini_text)
    if not parser.has_section("CAR_0"):
        parser.add_section("CAR_0")
    parser.set("CAR_0", "SETUP", setup_ini.name)
    parser.set("CAR_0", "_EXT_SETUP_FILENAME", str(setup_ini))
    if not parser.has_section("SESSION_0"):
        parser.add_section("SESSION_0")
    parser.set("SESSION_0", "SPAWN_SET", spawn_set)
    from io import StringIO

    out = StringIO()
    parser.write(out, space_around_delimiters=False)
    return out.getvalue()


@dataclass
class RaceIniBakeState:
    """Mutable status for the short-lived setup re-bake loop."""

    ready: int = 0
    writes: int = 0
    unstable: int = 0  # #466 B3: ticks skipped because race.ini was mid-write (torn/locked read)
    last_error: str | None = None


def validate_race_ini_write_target(race_ini: Path) -> Path:
    """Return logical ``race.ini`` path only when it is the AC Documents config file."""
    logical = race_ini.absolute()
    if (
        logical.name.lower() != "race.ini"
        or logical.parent.name.lower() != "cfg"
        or logical.parent.parent.name.lower() != "assetto corsa"
    ):
        raise ValueError(
            f"race.ini write target must be <AC Documents>/Assetto Corsa/cfg/race.ini: {logical}"
        )
    return logical


def write_setup_baked_race_ini(race_ini: Path, setup_ini: Path) -> str:
    """Bake ``setup_ini`` into ``race.ini`` with an atomic same-directory replace.

    Returns ``"missing"`` when ``race.ini`` is not present yet, ``"unstable"`` when the file is
    being rewritten by CM right now (see torn-read safety), ``"unchanged"`` when it already names
    the requested setup/spawn, and ``"written"`` after an atomic replace. The only accepted target
    is ``Documents/Assetto Corsa/cfg/race.ini``.

    Torn-read safety (#466 B3): the 50 ms re-bake loop runs concurrently with CM, which rewrites
    ``race.ini`` non-atomically during launch. A single ``read_text`` can capture a truncated file;
    baking that back through ``configparser`` and atomically replacing it would make the truncation
    permanent — silently dropping the CM-owned sections/keys that were cut off. Two guards prevent
    that: (1) require a STABLE snapshot — two identical back-to-back reads — before trusting the
    content, and (2) treat an unparseable snapshot as a no-op. Either guard failing returns
    ``"unstable"`` and writes nothing; the loop retries on its next tick once CM's write settles.
    """
    race_ini = validate_race_ini_write_target(race_ini)
    if not race_ini.is_file():
        return "missing"
    try:
        first = race_ini.read_text(encoding="utf-8", errors="surrogateescape")
        second = race_ini.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        # Momentarily unreadable (locked) mid-write; retry next tick rather than write a
        # partial file.
        return "unstable"
    if first != second:
        # The file changed between two back-to-back reads → CM is writing it now. Skip this tick.
        return "unstable"
    original = first
    try:
        baked = bake_setup_into_race_ini(original, setup_ini)
    except configparser.Error:
        # A stable but unparseable snapshot (e.g. a torn read halted mid-section). Never atomically
        # replace race.ini with a bake derived from it — that would drop CM's sections/keys.
        return "unstable"
    if baked == original:
        return "unchanged"
    tmp = race_ini.with_name(f".{race_ini.name}.ac_copilot_setup.tmp")
    try:
        tmp.write_text(baked, encoding="utf-8", errors="surrogateescape", newline="\n")
        tmp.replace(race_ini)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return "written"


@contextmanager
def race_ini_setup_bake_loop(
    race_ini: Path, setup_ini: Path, *, interval: float = 0.05
) -> Iterator[RaceIniBakeState]:
    """Continuously re-bake setup keys while CM regenerates ``race.ini``.

    CM's launch path provides the reliable overlay skip, but it also rewrites ``race.ini``. Keeping
    ``_EXT_SETUP_FILENAME`` present during that short window lets the setup apply at spawn while
    respecting the repo rule that the harness only writes under AC Documents.
    """
    if interval <= 0:
        raise ValueError(f"setup re-bake interval must be positive, got {interval!r}")
    state = RaceIniBakeState()
    stop = threading.Event()

    def _worker() -> None:
        while not stop.is_set():
            try:
                result = write_setup_baked_race_ini(race_ini, setup_ini)
                if result not in ("missing", "unstable"):
                    state.ready += 1
                if result == "written":
                    state.writes += 1
                elif result == "unstable":
                    state.unstable += 1  # #466 B3: torn/locked read dodged (no partial write)
            except Exception as exc:  # noqa: BLE001 - CM can expose half-written race.ini briefly.
                state.last_error = f"{type(exc).__name__}: {exc}"
            stop.wait(interval)

    worker = threading.Thread(target=_worker, name="race-ini-setup-bake")
    worker.start()
    try:
        yield state
    finally:
        stop.set()
        worker.join()


def parse_setup_fuel(setup_ini_text: str) -> float | None:
    """Parse ``[FUEL] VALUE`` (litres) from a setup INI, or ``None`` when the setup omits fuel.

    Fuel is the universal, cheap verification discriminator: nearly every race setup pins it, and
    it reads back directly from ``acpmf_physics.fuel`` after spawn. A setup without a ``[FUEL]``
    section cannot be fuel-verified (the caller then reports the setup as baked-but-unconfirmed).
    """
    parser = configparser.ConfigParser(strict=False, inline_comment_prefixes=(";", "#"))
    parser.optionxform = str
    try:
        parser.read_string(setup_ini_text)
    except configparser.Error:
        return None
    if not parser.has_option("FUEL", "VALUE"):
        return None
    try:
        return float(parser.get("FUEL", "VALUE").strip())
    except (ValueError, TypeError):
        return None


def fuel_matches(expected_l: float | None, observed_l: float | None, tolerance_l: float) -> bool:
    """True when ``observed`` fuel is within ``tolerance`` of the setup's ``expected`` fuel."""
    if expected_l is None or observed_l is None:
        return False
    return abs(observed_l - expected_l) <= tolerance_l


# ---------------------------------------------------------------------------
# Deterministic Quick Drive preset generation (pure; #459 Part B — the #154 Part-G
# determinism-lock preset).
# ---------------------------------------------------------------------------
def build_practice_preset(
    car_id: str, track_id: str, *, start_type: str = "START", layout: str | None = None
) -> str:
    """Render a deterministic Content Manager Quick Drive practice preset (JSON string).

    Field shapes mirror a CM-exported ``.cmpreset`` proven live on this rig (Imola/Mugello/Spa
    runs, 2026-06-27): clear weather, 26 °C, 12:00, optimum static track state, no penalties, all
    driving assists off except factory ABS/TC and tyre blankets. Every field is pinned so two runs
    of the same combo launch the same session — the determinism-lock preset from #154 Part G.

    ``start_type`` is CM's ``ModeData.StartType``: ``"START"`` spawns at the start line (proven
    for plain drive runs), ``"PIT"`` in the pit box. ``layout`` (for multi-layout tracks) is folded
    into CM's ``TrackId`` as ``<track>/<layout>`` so the launched circuit matches the racing line
    ``rig_drive`` follows — else CM launches the base circuit while the driver steers a different
    layout's ``fast_lane.ai`` (#460 review).
    """
    if start_type not in ("START", "PIT"):
        raise ValueError(f"start_type must be 'START' or 'PIT', got {start_type!r}")
    track_field = f"{track_id}/{layout}" if layout else track_id
    mode_data = {
        "StartType": start_type,
        "Penalties": False,
        "PlayerBallast": 0,
        "PlayerRestrictor": 0,
    }
    assists = {
        "IdealLine": False,
        "AutoBlip": True,
        "StabilityControl": 0.0,
        "AutoBrake": False,
        "AutoShifter": False,
        "SlipSteam": 1.0,
        "AutoClutch": False,
        "Abs": 1,
        "TractionControl": 1,
        "VisualDamage": True,
        "Damage": 0.0,
        "TyreWear": 0.0,
        "FuelConsumption": 0.0,
        "TyreBlankets": True,
    }
    track_state = {
        "s": 1.0,
        "t": 1.0,
        "r": 0.0,
        "g": 1,
        "d": "Perfect track for hotlapping.",
        "w": False,
    }
    preset = {
        "Mode": "/Pages/Drive/QuickDrive_Practice.xaml",
        "ModeData": json.dumps(mode_data, separators=(",", ":")),
        "CarId": car_id,
        "TrackId": track_field,
        "WeatherId": "3_clear",
        "RealConditions": False,
        "Temperature": 26.0,
        "Time": 43200,
        "TimeMultipler": 1,
        "tpc": False,
        "TrackPropertiesData": json.dumps(track_state, separators=(",", ":")),
        "asc": False,
        "AssistsData": json.dumps(assists, separators=(",", ":")),
        "ico": True,
    }
    return json.dumps(preset, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Preflight (pure over the filesystem; #459 Part B — fail fast, actionably).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PreflightIssue:
    """One failed preflight assertion, with an actionable message."""

    check: str
    message: str


def custom_ai_enabled(ac_root: Path, user_dir: Path) -> tuple[bool | None, str]:
    """Report whether CSP's Custom AI subsystem is enabled (``[CUSTOM_AI] ENABLED=1``).

    The user-level ``cfg/extension/new_behaviour.ini`` overrides when it carries the key; else the
    AC-root ``extension/config/new_behaviour.ini`` decides. Returns ``(None, detail)`` when
    neither file carries the key — the hijack precondition cannot be confirmed.
    """
    candidates = (
        user_dir / "cfg" / "extension" / "new_behaviour.ini",
        ac_root / "extension" / "config" / "new_behaviour.ini",
    )
    for path in candidates:
        if not path.is_file():
            continue
        parser = configparser.ConfigParser(strict=False, inline_comment_prefixes=(";", "#"))
        parser.optionxform = str  # preserve CSP's uppercase keys
        try:
            # utf-8-sig: CM/CSP tooling writes these files with a BOM on some installs, and a
            # BOM'd first section header otherwise raises MissingSectionHeaderError (review #460).
            parser.read(path, encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError, configparser.Error) as exc:
            return None, f"could not parse {path}: {exc}"
        if parser.has_option("CUSTOM_AI", "ENABLED"):
            raw = parser.get("CUSTOM_AI", "ENABLED").strip().lower()
            return raw in ("1", "true"), f"[CUSTOM_AI] ENABLED={raw} in {path}"
    return None, "no [CUSTOM_AI] ENABLED key in " + " or ".join(str(c) for c in candidates)


def preflight(config: AutoDriveConfig) -> list[PreflightIssue]:
    """Assert every launch precondition with an actionable message (empty list = go).

    Covers the tribal-lore failure modes that used to surface as mid-run mysteries: missing
    content, a preset whose CarId/TrackId disagree with the CLI, CSP Custom AI disabled (the
    hijack silently no-ops), a missing Content Manager, and an unresolvable setup.
    """
    issues: list[PreflightIssue] = []
    user_dir = resolve_ac_user_dir(config.ac_user_dir)

    if not config.ac_root.is_dir():
        issues.append(
            PreflightIssue(
                "ac_root", f"Assetto Corsa root not found: {config.ac_root} (pass --ac-root)"
            )
        )
        return issues  # everything below depends on the root

    if config.track_id:
        try:
            resolve_fast_lane(config.ac_root, config.track_id, config.track_layout)
        except FileNotFoundError as exc:
            issues.append(PreflightIssue("track", str(exc)))
    else:
        issues.append(PreflightIssue("track", "no track id (pass --track)"))

    if config.car_id:
        car_dir = config.ac_root / "content" / "cars" / config.car_id
        if not car_dir.is_dir():
            issues.append(
                PreflightIssue("car", f"car content not installed: {car_dir} (check --car id)")
            )

    if config.cm_preset is not None and not Path(config.cm_preset).is_file():
        # A missing --cm-preset must fail here, not later as an uncaught FileNotFoundError from
        # the CM launch — that would bypass the actionable-preflight/evidence path (#460 review).
        issues.append(
            PreflightIssue(
                "preset_missing",
                f"Quick Drive preset not found: {config.cm_preset} (check --cm-preset)",
            )
        )
    elif config.cm_preset is not None and Path(config.cm_preset).is_file():
        try:
            preset = json.loads(Path(config.cm_preset).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(
                PreflightIssue("preset", f"unreadable Quick Drive preset {config.cm_preset}: {exc}")
            )
        else:
            preset_track = str(preset.get("TrackId") or "")
            preset_car = str(preset.get("CarId") or "")
            # Compare the FULL TrackId incl. layout: on a multi-layout track a preset launching a
            # different layout than --track-layout would drive the wrong fast_lane.ai (#460 review).
            want_track = config.track_id.lower()
            if config.track_layout:
                want_track = f"{config.track_id}/{config.track_layout}".lower()
            if config.track_id and preset_track and preset_track.lower() != want_track:
                issues.append(
                    PreflightIssue(
                        "preset_track_mismatch",
                        f"--track {config.track_id!r}"
                        + (
                            f" --track-layout {config.track_layout!r}"
                            if config.track_layout
                            else ""
                        )
                        + f" but preset launches TrackId {preset_track!r} — the driven racing line "
                        "would not match the launched circuit",
                    )
                )
            if config.car_id and preset_car and preset_car.lower() != config.car_id.lower():
                issues.append(
                    PreflightIssue(
                        "preset_car_mismatch",
                        f"--car {config.car_id!r} but preset launches CarId {preset_car!r}",
                    )
                )

    enabled, detail = custom_ai_enabled(config.ac_root, user_dir)
    if enabled is not True:
        issues.append(
            PreflightIssue(
                "custom_ai",
                "CSP Custom AI is not confirmed enabled — the carcsw hijack will silently "
                f"no-op. Set [CUSTOM_AI] ENABLED=1 in extension/config/new_behaviour.ini "
                f"({detail})",
            )
        )

    if not config.skip_launch:
        from tools.ac_harness.entry_launcher import ContentManagerActuator

        cm = (
            Path(config.cm_exe)
            if config.cm_exe is not None
            else ContentManagerActuator.DEFAULT_CM_EXE
        )
        if not cm.is_file():
            issues.append(
                PreflightIssue(
                    "content_manager", f"Content Manager not found: {cm} (pass --cm-exe)"
                )
            )

    if config.setup:
        if config.skip_launch:
            # --skip-launch does not launch (rig_launch is the ONLY code path that bakes the
            # setup into race.ini), so on a pre-existing session the setup would be un-baked and
            # rig_apply_setup's fuel read could spuriously match a different same-fuel setup —
            # false evidence. Reject the combination (#460 review).
            issues.append(
                PreflightIssue(
                    "setup",
                    "--setup cannot combine with --skip-launch: the setup is baked at launch, "
                    "which --skip-launch bypasses. Drop one of the flags.",
                )
            )
        if not config.car_id:
            issues.append(
                PreflightIssue("setup", "--setup needs --car (setups live per car id on disk)")
            )
        elif config.car_id:
            try:
                resolve_setup_ini(
                    user_dir,
                    config.car_id,
                    config.track_id,
                    config.setup,
                    layout=config.track_layout,
                )
            except (FileNotFoundError, ValueError) as exc:
                issues.append(PreflightIssue("setup", str(exc)))
        # A hand-authored preset for a setup run must spawn where the setup can apply; the bake
        # forces SPAWN_SET=START on the relaunch, so this is only advisory for a preset that would
        # otherwise be launched as-is. (Generated presets already use START.)

    # A generated preset (no --cm-preset) for a multi-layout track needs the layout in its TrackId,
    # or CM launches the base circuit while rig_drive follows --track-layout's line (#460 review).
    # _main now bakes the layout into the generated preset; guard the hand-authored-omission case:
    if config.track_layout and config.cm_preset is None and not config.car_id:
        issues.append(
            PreflightIssue(
                "layout", "--track-layout needs --car (to generate a layout-correct preset)"
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Evidence bundle (pure writer; #459 Part C).
# ---------------------------------------------------------------------------
def write_evidence(
    evidence_dir: Path,
    report: AutoDriveReport,
    *,
    extras: dict[str, Any] | None = None,
) -> Path:
    """Write ``report.json`` (the full report + run extras) into ``evidence_dir``.

    The bundle is the proof artifact downstream tasks point at (setup A/B, dashboard checks,
    voice-coaching runs): one directory holding the machine-readable report, the generated
    preset, the HUD capture, and pointers to lap archives written during the run. Bundles default
    under ``.scratch/`` — session ephemera; a consuming task promotes what it must keep (see the
    scratch-dir disposability pitfall).
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"report": report.to_dict()}
    if extras:
        payload.update(extras)
    out = evidence_dir / "report.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def known_journal_laps_dir(user_dir: Path) -> Path:
    """The trainer's canonical per-lap archive dir (may not exist yet on a fresh profile).

    The Lua app writes to ``ac.FolderID.ScriptConfig``/…/``journal/laps`` — on disk:
    ``<user_dir>/cfg/extension/state/lua/app/AC_Copilot_Trainer/ac_copilot_trainer/journal/laps``
    (verified on the rig). The async writer creates it lazily when it opens the first temp file, so
    the directory can be absent right after a lap — poll this path so the archive is found once it
    appears (#515 review).
    """
    return (
        user_dir
        / "cfg"
        / "extension"
        / "state"
        / "lua"
        / "app"
        / "AC_Copilot_Trainer"
        / "ac_copilot_trainer"
        / "journal"
        / "laps"
    )


def discover_journal_laps_dir(user_dir: Path) -> Path | None:
    """Locate the EXISTING per-lap archive dir; bounded-glob fallback for renamed installs."""
    known = known_journal_laps_dir(user_dir)
    if known.is_dir():
        return known
    state_root = user_dir / "cfg" / "extension" / "state" / "lua"
    if not state_root.is_dir():
        return None
    for cand in sorted(state_root.glob("app/*/*/journal/laps")):
        if cand.is_dir():
            return cand
    return None


def candidate_journal_laps_dirs(user_dir: Path) -> list[Path]:
    """ALL existing per-lap archive dirs: the canonical path plus any ``app/*/*/journal/laps``.

    CSP does not delete an app's old state dir on rename/move, so the canonical (default) dir can
    persist as a STALE leftover while the active writer uses a renamed dir. Preferring the canonical
    (`discover_journal_laps_dir`) then shadows the renamed one and the poll watches the wrong path
    (#516 review). Scanning EVERY candidate + filtering by mtime finds the fresh archive wherever
    the active writer put it, regardless of stale leftovers.
    """
    dirs: list[Path] = []
    known = known_journal_laps_dir(user_dir)
    if known.is_dir():
        dirs.append(known)
    state_root = user_dir / "cfg" / "extension" / "state" / "lua"
    if state_root.is_dir():
        for cand in sorted(state_root.glob("app/*/*/journal/laps")):
            if cand.is_dir() and cand not in dirs:
                dirs.append(cand)
    return dirs


def _scan_lap_archives(dirs: list[Path], since_epoch: float) -> list[str]:
    """List ``lap_*.json`` across all ``dirs`` at/after ``since_epoch`` (mtime), newest first."""
    hits: list[tuple[float, str]] = []
    for journal_dir in dirs:
        if journal_dir is None or not journal_dir.is_dir():
            continue
        for path in journal_dir.glob("lap_*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= since_epoch:
                hits.append((mtime, str(path)))
    return [p for _, p in sorted(hits, reverse=True)]


def collect_lap_archives(
    journal_dir: Path | None,
    since_epoch: float,
    *,
    resolve: Callable[[], list[Path]] | None = None,
    wait_for_first: bool = False,
    timeout_s: float = 8.0,
    poll_s: float = 0.5,
    _clock: Callable[[], float] = time.monotonic,
    _sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """List lap-archive JSONs written at/after ``since_epoch`` (mtime), newest first.

    The trainer finalizes each lap trace with an **async deferred writer** (#246/#249): it streams
    to a temp file and atomically renames to ``lap_*.json`` *after* the ``lap`` WS frame the harness
    waits on. So immediately after a ``--wait-lap`` drive the finalized archive frequently does not
    exist yet (only a mid-stream temp file, which the ``lap_*.json`` glob correctly ignores) — a
    naive single scan then reports an empty list even though a lap was produced (#515).

    With ``wait_for_first`` (set when the run produced a lap) this polls up to ``timeout_s`` for the
    first archive to appear instead of racing the writer; it returns as soon as one exists, and
    returns immediately with no wait when ``wait_for_first`` is false (a run that produced no lap).

    When ``journal_dir`` is ``None`` and ``resolve`` is given, the candidate dirs are **re-resolved
    each scan** via ``resolve()`` (which returns ALL candidate dirs) — so a fresh-profile dir the
    writer creates mid-poll is found at its actual path, and a stale default dir cannot shadow a
    renamed-install dir (every candidate is scanned; mtime filters stale files; #516 review).

    A single ``journal_dir`` is for **tests / a known-good dir only**. Production MUST pass
    ``journal_dir=None`` + a ``resolve`` returning every candidate (`candidate_journal_laps_dirs`);
    passing one resolved dir would bypass the multi-dir scan and re-open the stale-shadowing bug.
    ``_clock``/``_sleep`` are injectable so the poll is deterministic in off-sim tests.
    """

    def _current() -> list[Path]:
        if journal_dir is not None:
            return [journal_dir]
        return resolve() if resolve else []

    found = _scan_lap_archives(_current(), since_epoch)
    if found or not wait_for_first:
        return found
    deadline = _clock() + max(0.0, timeout_s)
    while _clock() < deadline:
        _sleep(max(0.0, poll_s))
        found = _scan_lap_archives(_current(), since_epoch)
        if found:
            return found
    return found


# ---------------------------------------------------------------------------
# Rig wiring (Windows/AC only; not exercised by CI — validated on the rig).
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:  # pragma: no cover - rig-only progress trace
    """Print a timestamped harness progress line so per-cycle launch/hijack timing is visible.

    #466 acceptance requires proving a stalled cycle is *recycled within a few seconds* rather than
    burning a full-timeout dead-wait; these lines (with their wall-clock stamps) are that proof.
    """
    print(f"[auto-drive {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _minimize_foreground_window() -> None:  # pragma: no cover - rig-only
    """Best-effort: minimize whatever window holds the foreground before a CM launch.

    Live-found on the rig (2026-06-22 vault note; re-confirmed 2026-07-02 with the agent's own
    window in the attempt-3 HUD capture): a foreground window that is not CM/AC makes CM's
    auto-start race lose almost every time — AC sits at the pre-drive screen with LIVE status and
    advancing physics. Never minimizes AC or Content Manager themselves.
    """
    import ctypes

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 255)
        title = (buf.value or "").lower()
        if "assetto corsa" in title or "content manager" in title:
            return
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    except Exception:  # noqa: BLE001 - purely best-effort; a launch retry covers a miss
        return


def _race_ini_path(config: AutoDriveConfig) -> Path:  # pragma: no cover - rig-only
    """``<AC user data>/cfg/race.ini`` — the file CM regenerates and acs reads at spawn."""
    return resolve_ac_user_dir(config.ac_user_dir) / "cfg" / "race.ini"


def rig_launch(config: AutoDriveConfig) -> tuple[bool, str]:  # pragma: no cover - rig-only
    """Launch AC via the de-elevated Content-Manager URL and wait for the sim to go LIVE.

    Unlike the daemon's strict ``driving`` gate (which needs the car already moving — a
    chicken-and-egg for an autonomous launch), this waits only for LIVE + advancing physics, then
    the hijack+drive supplies the motion. Relaunches on the CM auto-start race up to
    ``max_launches``.

    For a setup run (``config.setup_ini`` set): keep CM's own launch path, but continuously re-bake
    ``race.ini`` while CM regenerates it. That keeps the setup in the spawn file without mutating
    the AC/CSP install tree.
    """
    from tools.ac_harness.entry_launcher import ContentManagerActuator

    actuator = ContentManagerActuator(preset=config.cm_preset, cm_exe=config.cm_exe)
    actuator.normalize_prior_state()
    for attempt in range(1, config.max_launches + 1):
        _log(
            "launching AC via Content Manager"
            + (" (setup baked into race.ini)" if config.setup_ini is not None else "")
        )
        _minimize_foreground_window()  # the CM auto-start race needs the desktop foreground free
        if config.setup_ini is not None:
            race_ini = _race_ini_path(config)
            with race_ini_setup_bake_loop(
                race_ini, config.setup_ini, interval=config.setup_rebake_interval
            ) as bake:
                actuator.launch() if attempt == 1 else actuator.relaunch()
                live = _wait_live(config.attempt_timeout)
            if live:
                _log(
                    f"LIVE reached; setup re-bake ready={bake.ready}x writes={bake.writes} "
                    f"(interval={config.setup_rebake_interval}s)"
                )
                time.sleep(config.settle_seconds)  # let CSP arm Custom-AI before the hijack
                if bake.ready > 0:
                    return (
                        True,
                        f"LIVE with setup after {attempt} launch attempt(s) — race.ini ready "
                        f"{bake.ready}x during CM launch ({bake.writes} rewrite(s))",
                    )
                detail = f"; last error: {bake.last_error}" if bake.last_error else ""
                return (
                    True,
                    "LIVE with setup verification deferred after "
                    f"{attempt} launch attempt(s) — race.ini readiness was not observed at "
                    f"{race_ini}{detail}",
                )
            continue
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
    """Create CarControls0 and briefly wait for CSP to create Car0 — the hijack landing.

    Two coupled problems this handles (#154, #466):

    * **The early-LIVE race.** CSP only creates Car0 once its Custom-AI subsystem is watching, and
      the act that triggers it is *creating* the CarControls0 section — a creation that lands too
      early silently no-ops. We **recreate** the section each attempt (close + new
      ``CustomAIController``) so a later creation re-triggers CSP.
    * **The pre-drive overlay stall.** ``_wait_live`` reports LIVE even when AC is frozen at the
      NEW-UI "0 seconds" pre-drive overlay (not drivable), so Car0 never appears no matter how long
      we wait. Each attempt is therefore a SHORT ``hijack_probe_seconds`` probe: a stalled overlay
      is detected in seconds and ``rig_hijack`` returns ``None`` fast, so the outer loop recycles a
      fresh launch instead of burning one long dead-wait. (A keypress nudge to clear the overlay
      in place was implemented and verified in-sim NOT to dismiss the CSP overlay — #466/#482 — so
      it was removed; the relaunch is the only working recovery.)
    """
    from tools.ac_harness.custom_ai import CustomAIController

    attempts = max(1, config.hijack_attempts)
    probe = config.hijack_probe_seconds  # CLI-validated finite & > 0 (single source of truth)
    for attempt in range(1, attempts + 1):
        ctrl = CustomAIController(0)
        deadline = time.monotonic() + probe
        while time.monotonic() < deadline:
            if ctrl.read_car_data() is not None:
                _log(f"hijack landed (Car0) on probe {attempt}/{attempts}")
                return ctrl
            time.sleep(0.1)
        ctrl.close()  # recreate the section next attempt to re-trigger the hijack
        # ASCII-only message: the harness prints to a Windows cp1252 console (cf. #475/#476).
        _log(
            f"hijack probe {attempt}/{attempts}: no Car0 in {probe:.1f}s "
            "(LIVE but not drivable - pre-drive overlay stall?)"
        )
    return None


def _read_physics_fuel() -> float | None:  # pragma: no cover - rig-only
    """Read ``acpmf_physics.fuel`` (litres, offset 12), or None when the sim did not publish it.

    Uses the shared-memory reader's **open-existing** opener (``OpenFileMappingW``), NOT
    ``mmap.mmap(-1, …, tag)``: the latter CREATES a zero-filled named section when AC has not
    published one, and a spurious ``fuel=0.0`` could fall within tolerance of a low-fuel setup and
    falsely verify a dead sim (#460 review). Open-existing returns None when the section is absent.
    """
    import struct

    from tools.ac_harness.shared_memory import open_shared_memory

    try:
        section = open_shared_memory("acpmf_physics", 64)
    except Exception:  # noqa: BLE001 - SharedMemoryUnavailable or platform error → treat as absent
        return None
    if section is None:
        return None
    try:
        return struct.unpack_from("<f", section.read(16), 12)[0]
    finally:
        section.close()


async def rig_apply_setup(config: AutoDriveConfig) -> dict:  # pragma: no cover - rig-only
    """VERIFY the launch-baked setup by reading ``acpmf_physics.fuel`` (setup is applied in launch).

    ``rig_launch`` already baked ``config.setup_ini`` into race.ini and respawned the car, so the
    setup is applied at this point. This leg proves it independently: it parses the setup's
    ``[FUEL] VALUE`` and reads the live ``acpmf_physics.fuel``; a match within
    ``setup_fuel_tolerance_l`` confirms the setup took (nearly every race setup pins fuel). A setup
    with no ``[FUEL]`` section is reported baked-but-unconfirmed (``ok=True`` with a note) rather
    than failing a real launch on a missing discriminator.
    """
    setup_ini = config.setup_ini
    if setup_ini is None:
        return {"ok": False, "error": "setup_ini not resolved (CLI wiring bug)"}
    name = setup_ini.stem
    path = str(setup_ini)
    try:
        expected_fuel = parse_setup_fuel(setup_ini.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return {"ok": False, "name": name, "path": path, "error": f"setup ini unreadable: {exc}"}

    if expected_fuel is None:
        return {
            "ok": True,
            "name": name,
            "path": path,
            "detail": "setup baked at launch; no [FUEL] key to fuel-verify (unconfirmed)",
            "expected_fuel": None,
        }

    # Give the sim a moment; read a few samples so a transient 0 during load does not false-fail.
    deadline = time.monotonic() + max(5.0, config.setup_timeout)
    observed: float | None = None
    while time.monotonic() < deadline:
        observed = await asyncio.to_thread(_read_physics_fuel)
        if observed is not None and fuel_matches(
            expected_fuel, observed, config.setup_fuel_tolerance_l
        ):
            return {
                "ok": True,
                "name": name,
                "path": path,
                "detail": f"fuel {observed:.1f}L matches setup FUEL {expected_fuel:.1f}L",
                "expected_fuel": expected_fuel,
                "observed_fuel": observed,
            }
        await asyncio.sleep(1.0)
    return {
        "ok": False,
        "name": name,
        "path": path,
        "error": (
            f"fuel {observed if observed is None else round(observed, 1)}L != setup FUEL "
            f"{expected_fuel:.1f}L (±{config.setup_fuel_tolerance_l})"
        ),
        "expected_fuel": expected_fuel,
        "observed_fuel": observed,
    }


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


def _teleport_onto_line(  # pragma: no cover - rig-only
    controller: Controller,
    line: list[tuple[float, float, float]],
    *,
    ahead_m: float = 40.0,
) -> bool:
    """Teleport the car onto the racing line (custom teleport), verified by position read-back.

    Targets the line point ~``ahead_m`` past the nearest one so the car lands pointing down a
    stretch it can immediately drive. The custom-teleport offsets are doc-extracted (VERIFY LIVE),
    so success is **observed, never assumed**: the car must read back within 25 m of the target,
    else the caller falls back to the pit-exit path / teleport-to-pits.
    """
    from tools.ac_harness.ai_line import PurePursuit, _horizontal

    teleport = getattr(controller, "teleport_to_custom", None)
    if teleport is None:
        return False
    cd = controller.read_car_data()
    if not cd:
        return False
    pursuit = PurePursuit(line)
    idx = pursuit.nearest_index(_horizontal(cd["position"]))
    target_idx = pursuit.advance_index(idx, ahead_m)
    next_idx = pursuit.advance_index(target_idx, 5.0)
    tx, ty, tz = line[target_idx]
    nx, _, nz = line[next_idx]
    dx, dz = nx - tx, nz - tz
    norm = (dx * dx + dz * dz) ** 0.5 or 1.0
    direction = (dx / norm, 0.0, dz / norm)
    for _ in range(5):
        teleport((tx, ty + 0.3, tz), direction)
        time.sleep(0.1)
    controller.write_controls(0.0, 0.0, 0.0)  # clear the teleport flag
    time.sleep(0.6)
    cd = controller.read_car_data()
    if not cd:
        return False
    px, _, pz = cd["position"]
    landed = ((px - tx) ** 2 + (pz - tz) ** 2) ** 0.5
    return landed <= 25.0


class PhysicsStallDetector:
    """Sim-death detector: the main ``acpmf_physics`` packet_id stagnant for
    ``sim_dead_seconds`` means ``acs.exe`` died (#459/#460).

    Feed one ``(monotonic now, main packet_id)`` sample per frame via :meth:`update`.
    A real packet advance resets the death timer; a ``None`` packet (physics mmap
    gone) does **not** — sustained ``None`` or a frozen packet both trip, which is
    exactly the crash/freeze case the watchdog exists to catch (resetting on every
    ``None`` would disable it, #460 review). The Car0 (Custom-AI) packet is *not*
    used: CSP holds it constant for a stationary car, so it false-fired at the start
    line (#459 review).

    Extracted from :func:`rig_drive` so the rule is one source of truth and is
    unit-testable off-rig — it is the sim-death oracle the EPIC #154 Part-G
    false-green KPI (``false_green_kpi.py``) exercises.
    """

    def __init__(self, sim_dead_seconds: float, *, now: float | None = None) -> None:
        self.sim_dead_seconds = sim_dead_seconds
        self._last_pkt: int | None = None
        # Anchor the death timer at construction when ``now`` is given (the drive-loop start), so a
        # sim already dead before the first packet sample still trips after sim_dead_seconds — the
        # inline watchdog's behaviour. Without ``now`` the timer anchors on the first update sample.
        self._last_change: float | None = now

    def update(self, now: float, packet_id: int | None) -> bool:
        """Record one sample; return ``True`` once the packet has been stagnant
        longer than ``sim_dead_seconds`` (sim-death), else ``False``."""
        if self._last_change is None:
            self._last_change = now
        if packet_id is not None and (self._last_pkt is None or packet_id != self._last_pkt):
            self._last_pkt = packet_id
            self._last_change = now
            return False
        return (now - self._last_change) > self.sim_dead_seconds


def rig_drive(  # pragma: no cover - rig-only
    controller: Controller, config: AutoDriveConfig, stop: threading.Event
) -> DriveStats:
    """Drive the selected controller over the track's fast_lane.ai until ``stop`` or sim-death.

    ``config.driver`` picks RacingDriver (default — shifts gears, carries pace) or the cruise
    LapDriver. Guards (#459 Part D):

    * **sim-death** — a frozen **main ``acpmf_physics`` packet_id** for ``sim_dead_seconds`` means
      ``acs.exe`` died; stop instead of spinning on stale telemetry. (Not the Car0 packet, which
      CSP holds constant for a stationary car — that false-fired at the start line, #459 review.)
    * **no-progress watchdog** — recovers a stalled car regardless of commanded throttle (the
      drivers' own stuck detectors are gas-gated and miss low-throttle stalls).
    * **recovery cap** — a car that keeps stalling stops with an honest FAIL naming the stall
      distance instead of teleport-looping until the clock runs out.
    * **spawn-to-line** — an off-line spawn (pit box) starts behind geometry the controllers are
      blind to; a verified custom teleport onto the line skips the trap. Recovery RETRIES the line
      teleport whenever the car is off the line — at an off-line spawn OR after a prior recovery
      teleported it into the pits — instead of looping teleport-to-pits (which leaves the car
      off-line and burns every recovery at 0 m, incl. a mid-lap spin recovered to pits — the
      pit-start stall, #528); teleport-to-pits is the fallback when the line teleport cannot land
      (offsets are VERIFY LIVE).
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
    watchdog = ProgressWatchdog(stall_seconds=config.progress_stall_seconds)
    line_teleport_works: bool | None = None
    # Whether the car is currently OFF the racing line — set at an off-line spawn (pit box / offset
    # grid slot) AND whenever a recovery teleports it back to the pits (itself off-line). Recovery
    # reads this to retry the line teleport vs. loop in the pits (#528).
    off_line = False

    if config.spawn_to_line:
        from tools.ac_harness.ai_line import PurePursuit

        cd0 = controller.read_car_data()
        if cd0:
            pursuit0 = PurePursuit(line)
            idx0 = pursuit0.nearest_index(_horizontal(cd0["position"]))
            p0 = pursuit0.plane_position(idx0)
            car0 = _horizontal(cd0["position"])
            off_line_m = ((p0[0] - car0[0]) ** 2 + (p0[1] - car0[1]) ** 2) ** 0.5
            if off_line_m > 12.0:  # pit box / off-line spawn
                off_line = True
                line_teleport_works = _teleport_onto_line(controller, line)
                if line_teleport_works:
                    off_line = False  # spawn teleport landed → back on the racing line
                stats.spawn_teleport = "ok" if line_teleport_works else "failed"
            else:
                stats.spawn_teleport = "skipped (on line)"

    def _recover(now: float) -> bool:
        """Shared recovery for driver-flagged stuck AND watchdog stalls. False = cap exceeded."""
        nonlocal line_teleport_works, off_line
        stats.recoveries += 1
        if stats.recoveries > config.max_recoveries:
            stats.recovery_capped = True
            stats.reason = (
                f"recovery cap ({config.max_recoveries}) exceeded at {stats.total_distance_m:.0f}m"
            )
            return False
        recovered_to_line = False
        # Retry the racing-line teleport whenever the car is off the line — an off-line spawn OR a
        # prior recovery that teleported it into the pits — or a prior line teleport is known good.
        # teleport_to_pits itself PLACES the car off-line, so latching only the spawn state and
        # looping to pits burns every recovery at 0 m (#528, incl. a mid-lap spin recovered to
        # pits). _teleport_onto_line re-reads position + retargets each call, so a later one lands.
        if should_try_line_teleport_on_recovery(
            spawn_to_line_enabled=config.spawn_to_line,
            car_off_line=off_line,
            line_teleport_known_good=bool(line_teleport_works),
        ):
            recovered_to_line = _teleport_onto_line(controller, line)
            if recovered_to_line:
                line_teleport_works = True
                off_line = False  # back on the racing line
        if not recovered_to_line:
            for _ in range(5):
                controller.teleport_to_pits()
                time.sleep(0.1)
            time.sleep(0.8)
            off_line = True  # teleport_to_pits leaves the car off-line (in the pits)
        driver.on_recovery()
        watchdog.reset(time.monotonic() - t0, stats.total_distance_m)
        return True

    # Sim-death keys on the MAIN acpmf_physics packet_id, NOT the Car0 (Custom-AI) one: live-found
    # (Spa 2026-07-02) that CSP does NOT bump Car0.packet_id every frame — it stays constant while a
    # car is stationary — so watching Car0 falsely declared "acs.exe died" 4 s into a start-line
    # spawn, before the driver could even shift out of neutral. The main physics packet advances
    # every frame while the sim runs and freezes only when acs actually dies (#459 review).
    from tools.ac_harness.shared_memory import SharedMemoryReader, SharedMemoryUnavailable

    phys_reader: SharedMemoryReader | None = None
    try:
        phys_reader = SharedMemoryReader()
    except SharedMemoryUnavailable:
        phys_reader = None

    def _main_packet_id() -> int | None:
        nonlocal phys_reader
        if phys_reader is None:
            try:
                phys_reader = SharedMemoryReader()
            except SharedMemoryUnavailable:
                return None
        try:
            p = phys_reader.read_physics()
        except SharedMemoryUnavailable:
            phys_reader.close()
            phys_reader = None
            return None
        return p.packet_id if p is not None else None

    prev_plane: tuple[float, float] | None = None
    t0 = time.monotonic()
    # Anchor the sim-death timer at the loop start (not the first packet sample) so a sim that is
    # already dead trips once stale car data appears, even on a short/ending run (codex on #513).
    stall = PhysicsStallDetector(config.sim_dead_seconds, now=t0)
    try:
        while not stop.is_set() and time.monotonic() - t0 < config.drive_seconds:
            cd = controller.read_car_data()
            if not cd:
                time.sleep(0.02)
                continue
            # Sim-death: the main acpmf_physics packet_id stagnant for sim_dead_seconds means
            # acs.exe died. A None (physics mmap gone) does NOT reset the timer (#460 review) —
            # sustained None or a frozen packet both trip. Rule owned by PhysicsStallDetector.
            if stall.update(time.monotonic(), _main_packet_id()):
                stats.sim_dead = True
                stats.reason = "acpmf_physics packet_id stagnant (acs.exe died)"
                break
            now = time.monotonic() - t0
            frame = driver.step(
                cd["position"],
                cd["look"],
                cd["speed_kmh"],
                cd["rpm"],
                cd["gear"],
                now,
            )
            stalled = watchdog.update(stats.total_distance_m, now)
            if frame.needs_recovery or stalled:
                if not _recover(now):
                    break
                prev_plane = None  # do not count the teleport as travelled distance
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
        if phys_reader is not None:
            phys_reader.close()
        for _ in range(20):
            try:
                controller.write_controls(0.0, 0.6, 0.0)
            except Exception:  # noqa: BLE001 - sim may already be gone
                break
            time.sleep(0.03)
    stats.drove = stats.total_distance_m > 200 and stats.max_speed_kmh > 25
    return stats


def ensure_sidecar(  # pragma: no cover - rig-only
    sidecar_url: str, *, autostart: bool, startup_timeout: float = 20.0
):
    """Make sure a sidecar is listening at ``sidecar_url``; auto-start one when none is.

    Returns ``(ok, detail, proc)`` — ``proc`` is the harness-spawned subprocess (terminate it at
    teardown unless the operator asked to keep it) or ``None`` when a sidecar was already up
    (e.g. the Game Point launcher's supervised child; never spawn a second against it).
    """
    import socket
    import subprocess
    import sys
    import urllib.parse

    parsed = urllib.parse.urlparse(sidecar_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765

    def _up() -> bool:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            return False

    if _up():
        return True, f"sidecar already listening on {host}:{port}", None
    if not autostart:
        return False, f"no sidecar on {host}:{port} and --no-sidecar-autostart given", None
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.ai_sidecar", "--host", host, "--port", str(port)],
        cwd=str(repo_root),
    )
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        if _up():
            return True, f"sidecar auto-started on {host}:{port} (pid {proc.pid})", proc
        if proc.poll() is not None:
            return False, f"sidecar exited immediately (code {proc.returncode})", None
        time.sleep(0.5)
    # Kill the half-started child here: the failure path in _main returns before its
    # terminate-at-teardown, and an orphan would squat the port forever (review #460).
    proc.terminate()
    return False, f"sidecar did not open {host}:{port} within {startup_timeout:.0f}s", None


def _capture_hud_evidence(evidence_dir: Path, region: str) -> dict:  # pragma: no cover - rig-only
    """Best-effort HUD capture into the evidence bundle; returns the liveness verdict."""
    try:
        from tools.ac_harness.hud_capture import capture_region, liveness_score, save_png

        w, h, bgra = capture_region(region)
        score = liveness_score(bgra)
        out = evidence_dir / "hud.png"
        save_png(str(out), w, h, bgra)
        return {
            "path": str(out),
            "region": region,
            "mean": round(score.mean, 2),
            "distinct": score.distinct,
            "rendering": score.is_rendering(),
        }
    except Exception as exc:  # noqa: BLE001 - evidence capture must not mask the run result
        return {"error": f"{type(exc).__name__}: {exc}"}


def _utc_stamp() -> str:  # pragma: no cover - trivial clock wrapper
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _positive_float(value: str) -> float:
    """argparse type: a strictly-positive, FINITE float.

    Rejects 0, negatives, and non-finite ``inf``/``nan`` at parse time with a clean CLI error.
    Non-finiteness matters as much as sign (#482 review): ``--hijack-probe-seconds inf`` would make
    ``deadline = monotonic() + probe`` never expire, reintroducing the infinite overlay dead-wait
    #466 removes; ``--setup-rebake-interval 0`` would raise an uncaught ``ValueError`` deep in
    ``race_ini_setup_bake_loop`` mid-launch. Both fail fast here instead.
    """
    parsed = float(value)  # ValueError here is turned into a usage error by argparse
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a finite number > 0, got {value!r}")
    return parsed


def _nonneg_float(value: str) -> float:
    """argparse type: a non-negative, FINITE float (``0`` allowed to disable the feature).

    Like :func:`_positive_float` but permits ``0`` — ``--lap-finalize-grace-s 0`` is a valid "no
    grace" opt-out. Still rejects negatives and non-finite ``inf``/``nan``: ``inf`` would make the
    post-lap ``await asyncio.sleep(inf)`` never reach the teardown ``finally`` (#515 review).
    """
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(f"must be a finite number >= 0, got {value!r}")
    return parsed


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Composed autonomous self-test (#154 Part G): drive any car/track + assert"
    )
    p.add_argument(
        "--cm-preset",
        type=Path,
        default=None,
        help="Quick Drive .cmpreset (omit to generate a deterministic practice preset from --car)",
    )
    p.add_argument(
        "--car",
        default=None,
        help="AC car id (e.g. ks_porsche_911_gt3_r_2016); with --track it generates the preset",
    )
    p.add_argument("--track", required=True, help="AC track id (for the fast_lane.ai racing line)")
    p.add_argument(
        "--track-layout",
        default=None,
        help="layout subdir for multi-layout tracks (e.g. layout_gp)",
    )
    p.add_argument(
        "--setup",
        default=None,
        help="car setup to apply + verify in-sim: a name under Documents/Assetto Corsa/setups/"
        "<car>/<track|generic>/ (no .ini), or a path inside the setups folder",
    )
    p.add_argument(
        "--setup-timeout",
        type=float,
        default=20.0,
        help="seconds to wait for acpmf_physics.fuel to confirm the launch-baked setup",
    )
    p.add_argument(
        "--setup-rebake-interval",
        type=_positive_float,
        default=AutoDriveConfig.setup_rebake_interval,
        help="how often (s) to re-bake the setup into race.ini during the CM launch window; a very "
        "small value fights CM's own race.ini writes and stalls the pre-drive auto-start (#466). "
        "Must be > 0 (race_ini_setup_bake_loop rejects a non-positive interval)",
    )
    p.add_argument("--ac-root", type=Path, default=None, help="AC content root (Steam install)")
    p.add_argument(
        "--ac-user-dir",
        type=Path,
        default=None,
        help="AC user data root (Documents/Assetto Corsa; auto-detects OneDrive redirect)",
    )
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
    p.add_argument(
        "--lap-finalize-grace-s",
        type=_nonneg_float,
        default=8.0,
        help="drive this long past S/F after the lap so the async archive writer finalizes; "
        "0 disables (#515)",
    )
    p.add_argument("--target-speed", type=float, default=55.0, help="cruise target speed (km/h)")
    p.add_argument("--min-corner", type=float, default=30.0, help="cruise min corner speed (km/h)")
    p.add_argument("--tap-seconds", type=float, default=30.0)
    p.add_argument("--wait-lap", action="store_true", help="assert a completed lap (real motion)")
    p.add_argument("--strict", action="store_true", help="require session+lap, enforce ordering")
    p.add_argument("--skip-launch", action="store_true", help="AC already LIVE; only hijack+drive")
    p.add_argument(
        "--hijack-probe-seconds",
        type=_positive_float,
        default=5.0,
        help="per-attempt wait for the carcsw hijack to land; a stalled pre-drive overlay is "
        "detected within this window and the launch recycles (was one long dead-wait) (#466). "
        "Must be finite and > 0 (a non-finite value would never expire)",
    )
    p.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="proof bundle destination (default: .scratch/harness-evidence/<ts>_<car>_<track>/)",
    )
    p.add_argument(
        "--hud-region",
        choices=("full", "left", "coaching"),
        default="full",
        help="HUD capture region saved into the evidence bundle",
    )
    p.add_argument(
        "--max-recoveries",
        type=int,
        default=6,
        help="stuck/no-progress recoveries before the run FAILS honestly",
    )
    p.add_argument(
        "--progress-stall-seconds",
        type=float,
        default=10.0,
        help="no forward progress for this long triggers a recovery (any throttle)",
    )
    p.add_argument(
        "--no-spawn-line",
        action="store_true",
        help="do not teleport a pit-box spawn onto the racing line (use the OUT-phase pit exit)",
    )
    p.add_argument(
        "--no-sidecar-autostart",
        action="store_true",
        help="fail preflight instead of auto-starting a loopback sidecar",
    )
    p.add_argument(
        "--keep-sidecar",
        action="store_true",
        help="leave a harness-auto-started sidecar running after the run",
    )
    p.add_argument(
        "--preflight-only",
        action="store_true",
        help="run the preflight asserts and exit (0 = ready to launch)",
    )
    return p


def _config_from_args(args: argparse.Namespace) -> AutoDriveConfig:
    kwargs: dict[str, Any] = dict(
        cm_preset=args.cm_preset,
        track_id=args.track,
        track_layout=args.track_layout,
        car_id=args.car,
        ac_user_dir=args.ac_user_dir,
        cm_exe=args.cm_exe,
        sidecar_url=args.sidecar_url,
        setup=args.setup,
        setup_timeout=args.setup_timeout,
        setup_rebake_interval=args.setup_rebake_interval,
        driver=args.driver,
        pace=args.pace,
        ggv_scale=args.ggv_scale,
        racing_max_speed_kmh=args.max_speed,
        drive_seconds=args.drive_seconds,
        lap_finalize_grace_s=args.lap_finalize_grace_s,
        target_speed_kmh=args.target_speed,
        min_corner_speed_kmh=args.min_corner,
        tap_seconds=args.tap_seconds,
        wait_lap=args.wait_lap,
        strict=args.strict,
        skip_launch=args.skip_launch,
        hijack_probe_seconds=args.hijack_probe_seconds,
        max_recoveries=args.max_recoveries,
        progress_stall_seconds=args.progress_stall_seconds,
        spawn_to_line=not args.no_spawn_line,
    )
    if args.ac_root is not None:
        kwargs["ac_root"] = args.ac_root
    return AutoDriveConfig(**kwargs)


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig-only CLI wiring
    args = _build_arg_parser().parse_args(argv)
    if args.cm_preset is None and not args.car:
        print("auto-drive: pass --car (preset is generated) or --cm-preset (hand-authored)")
        return 2
    config = _config_from_args(args)
    try:
        # Ids become path segments (evidence dir, preset, setups) — reject path-shaped input
        # before anything touches the filesystem (review #460: a hostile --car could otherwise
        # steer the evidence mkdir outside .scratch).
        validate_ac_id("track", config.track_id)
        if config.car_id:
            validate_ac_id("car", config.car_id)
        if config.track_layout:
            validate_ac_id("layout", config.track_layout)
    except ValueError as exc:
        print(f"auto-drive: {exc}")
        return 2
    user_dir = resolve_ac_user_dir(config.ac_user_dir)

    car_tag = config.car_id or "car"
    evidence_dir = args.evidence_dir or (
        Path(".scratch") / "harness-evidence" / f"{_utc_stamp()}_{car_tag}_{config.track_id}"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)

    if config.cm_preset is None:
        # Deterministic practice preset (#154 Part-G determinism lock), START spawn. A setup run
        # keeps race.ini re-baked during the CM launch window so the setup applies at spawn.
        preset_path = evidence_dir / "generated.cmpreset"
        preset_path.write_text(
            build_practice_preset(
                config.car_id, config.track_id, start_type="START", layout=config.track_layout
            ),
            encoding="utf-8",
        )
        config.cm_preset = preset_path

    issues = preflight(config)
    if issues:
        print("auto-drive: PREFLIGHT FAILED")
        for issue in issues:
            print(f"  [{issue.check}] {issue.message}")
        return 2
    print("auto-drive: preflight ok")
    if args.preflight_only:
        return 0

    if config.setup:
        config.setup_ini = resolve_setup_ini(
            user_dir,
            config.car_id,
            config.track_id,
            config.setup,
            layout=config.track_layout,
        )
        print(f"auto-drive: setup resolved -> {config.setup_ini}")

    sidecar_ok, sidecar_detail, sidecar_proc = ensure_sidecar(
        config.sidecar_url, autostart=not args.no_sidecar_autostart
    )
    print(f"auto-drive: {sidecar_detail}")
    if not sidecar_ok:
        return 2

    run_started_epoch = time.time()
    try:
        report = asyncio.run(
            run_auto_drive(
                config,
                launch=rig_launch,
                hijack=rig_hijack,
                drive=rig_drive,
                tap=tap_frames,
                apply_setup=rig_apply_setup,
            )
        )
    finally:
        if sidecar_proc is not None and not args.keep_sidecar:
            sidecar_proc.terminate()

    hud = _capture_hud_evidence(evidence_dir, args.hud_region)
    # Gate the wait on the WS `lap` frame the tap actually saw (report.counts["lap"]) — the SAME
    # signal run_auto_drive's grace uses — not rig_drive's separate lap counter, so the two never
    # diverge (#515 review). The async writer finalizes just after that frame, so wait briefly
    # rather than racing to []. On a fresh profile journal/laps may not exist until the writer
    # creates it, so poll the deterministic known path when discovery finds nothing yet.
    # Only wait when the grace-drive ACTUALLY ran — gate on the single flag run_auto_drive set
    # (report.lap_grace_applied), not a re-derived condition, so the grace and the poll can never
    # disagree (#516 review). On a fresh profile journal/laps may not exist until the async writer
    # creates it — pass a re-discovering resolver so the poll finds it at its real path (default or
    # renamed install), not a hardcoded one. No grace-drive => single scan, no hang.
    # The grace-drive already elapsed synchronously in run_auto_drive, so by here the writer has
    # streamed the trace; this poll only awaits the OS flush/rename — a short CONSTANT timeout, not
    # one scaled to the in-sim grace time (#516 review). collect_lap_archives' default covers it.
    # Scan ALL candidate journal/laps dirs each poll (canonical + any renamed) and filter by mtime:
    # CSP leaves stale default state dirs on rename, so preferring one dir lets a stale leftover
    # shadow the active renamed dir (#516 review). The fresh archive is found wherever the active
    # writer put it; stale files are excluded by the since_epoch gate.
    lap_archives = collect_lap_archives(
        None,
        run_started_epoch,
        resolve=lambda: candidate_journal_laps_dirs(user_dir),
        wait_for_first=report.lap_grace_applied,
    )
    # Report the dir the archive was actually found in (correct even for a renamed install), so the
    # metadata matches the multi-dir scan, not the canonical-preferring discover (#516 review).
    journal_dir = (
        Path(lap_archives[0]).parent if lap_archives else discover_journal_laps_dir(user_dir)
    )
    extras = {
        "run": {
            "started_epoch": run_started_epoch,
            "argv": list(argv) if argv is not None else None,
            "cm_preset": str(config.cm_preset),
            "setup_ini": str(config.setup_ini) if config.setup_ini else None,
            "driver": config.driver,
            "sidecar": sidecar_detail,
        },
        "hud": hud,
        "lap_archives": lap_archives,
        "journal_dir": str(journal_dir) if journal_dir else None,
    }
    report_path = write_evidence(evidence_dir, report, extras=extras)

    print(report.summary())
    if hud.get("rendering") is not None:
        print(
            f"  hud: {'RENDERING' if hud['rendering'] else 'BLACK/FROZEN'} "
            f"mean={hud.get('mean')} distinct={hud.get('distinct')} -> {hud.get('path')}"
        )
    if lap_archives:
        print(f"  lap archives ({len(lap_archives)}): {lap_archives[0]}")
    print(f"  evidence: {report_path}")
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    import sys
    from pathlib import Path as _Path

    _repo_root = str(_Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
