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
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

from tools.ac_content import read_car_data_member
from tools.ac_harness.custom_ai import (
    ControllerCloseRetryError,
    close_controller_with_retries,
)
from tools.ac_harness.preset_utils import build_practice_preset
from tools.ac_harness.sequence_probe import (
    Check,
    evaluate_sequence,
    intervention_summary,
    tap_frames,
)
from tools.ac_harness.window_utils import minimize_foreground_window
from tools.ai_sidecar.external_protocol import CLIENT_CLASS_OBSERVER

if TYPE_CHECKING:
    from tools.ac_harness.ggv_profile import GGVModel


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


# #577: hard cap on the deliberate self-play overspeed probe (ggv_scale above 1 on the alien
# path). The uncertainty-safe QSS envelope is a lower-confidence bound, so a bounded supra-LCB
# probe is how self-play generates the evidence that raises the measured bins — but 1.2x speed
# is 1.44x lateral g, already an aggressive single step; anything above is a config error, not
# a braver probe. Requires the explicit --alien-allow-overspeed opt-in (auto_alien iterate mode).
ALIEN_MAX_OVERSPEED_SCALE = 1.2

# #596 Part A: retain a bounded, low-rate controller trace in every evidence bundle.  The drive
# loop runs at ~80 Hz, so dumping every frame would turn a five-minute report into tens of
# thousands of rows.  Two samples/second plus forced recovery events is enough to reconstruct the
# 450-580 m stall while keeping the JSON comfortably reviewable.  When an unusually long drive
# exceeds the cap, keep the most recent samples: the state immediately before a failure is the
# diagnostically valuable window.
CONTROL_TRACE_INTERVAL_S = 0.5
CONTROL_TRACE_MAX_SAMPLES = 2048


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
    # ``driver="handshake"`` runs the #532 plant-ID handshake instead of a plain drive: guided
    # probes measure ff_sign / steer-FF / shift points / r_eff. The result flows OUT via
    # ``DriveStats.payload`` (rig_drive copies the controller's sink there), not a config
    # side-channel (daemon review) — config stays input-only.
    driver: str = "racing"
    drive_seconds: float = 300.0
    # Plant-artifact consumption (#532): RacingDriver kwargs derived from the combo's identified
    # plant (see plant_id.plant_driver_kwargs), applied on the ggv path. None => generic plant.
    plant_kwargs: dict | None = None
    # #532 Part B: the combo's identified friction plant (a ggv_profile.GGVModel), consumed on the
    # ggv path INSTEAD of generic_gt3_ggv() when the loaded artifact carries a fitted ggv block.
    # None => generic plant.
    plant_ggv: GGVModel | None = None
    # #572 alien pipeline: the combo's optimized line + QSS profile resolved by the CLI from the
    # alien-line artifact (built/cached against the identified plant). ``driver="alien"`` REQUIRES
    # both — there is no silent fallback to the stock fast_lane geometry (a degrade the alien
    # pipeline exists to end). Points are (x, y, z) in the fast_lane frame; v_target is m/s per
    # point (unscaled physics optimum; ggv_scale applies at driver construction).
    alien_line: list | None = None
    alien_v_target: list | None = None
    pace: float = 0.9  # racing: fraction of the AI line's speed profile to target
    racing_max_speed_kmh: float = (
        240.0  # racing/ggv: cap (above any GT speed; lets it use top gears)
    )
    ggv_scale: float = 0.9  # ggv: safety margin on the min-time profile (flat-out * scale)
    # #577 progressive-envelope self-play: allow the alien path to run a deliberate, bounded
    # overspeed probe (ggv_scale in (1, ALIEN_MAX_OVERSPEED_SCALE]) — the uncertainty-safe QSS
    # floor is a lower-confidence bound, and driving slightly above it is how the self-play loop
    # generates the supra-LCB lateral evidence that raises the measured bins. Guarded: opt-in
    # flag only (the one-shot alien path keeps the hard <=1 gate from #572), hard-capped, and
    # every step is falsifiable via the auto_alien keep-last-valid oracle.
    alien_overspeed: bool = False
    # #582 L3: opt-in beyond-QSS per-corner refinement of the alien-line profile. The refined
    # v_target rides the same artifact/provenance gates; per-corner revert reasons land in the
    # artifact's ``l3`` report. Off (default) builds/serves the pre-#582 QSS-only artifact.
    alien_l3: bool = False
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
    # #577 flying-lap windows: keep the tap window open until this many TIMED laps complete
    # (or the drive budget expires — whichever first). 0 = legacy single-lap --wait-lap
    # semantics. Setting it >0 implies wait_lap (the CLI enforces this coupling).
    target_laps: int = 0
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
    # #596 Part B: acs.exe death is an intermittent rig failure, not a controller verdict.  Retry
    # the entire launch->hijack->drive attempt once by default; the wrapper retains every attempt
    # in report.json so a recovered crash is measured rather than hidden.
    sim_death_retries: int = 1
    # #737: the launch-time setup re-bake can lose CM's race.ini regeneration race (#466) even on
    # the CORRECT combo — the car spawns on default fuel and setup verification honestly fails.
    # That miss is confirmed intermittent, so it earns the same fresh-full-launch treatment as a
    # sim death: bounded retries with every attempt retained in report.json.  0 disables.
    setup_verify_retries: int = 1
    skip_launch: bool = False
    # #738: auto-skip CM's pre-drive "Custom Shaders Patch data" dialog. On a boot where the
    # online patch-data fetch hangs (CM Main Log: "Cannot get data"), that dialog blocks the
    # launch — acs.exe never spawns — and the attempt loop would otherwise relaunch-loop
    # against it, burning ~2x launch cycles per drive. The watcher only ever invokes the
    # dialog's own Skip button (CM then proceeds on its local cache).
    cm_dialog_skip: bool = True


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
    # #555: process identity observed after hijack. A different acs.exe PID means another
    # harness/CM launch replaced this session; that is distinct from a generic sim death.
    sim_pid: int | None = None
    unexpected_sim_pids: list[int] = field(default_factory=list)
    session_replaced: bool = False
    recoveries: int = 0  # stuck/no-progress recoveries taken (capped by max_recoveries)
    recovery_capped: bool = False  # True when max_recoveries was exhausted (vetoes success)
    spawn_teleport: str = ""  # "" (not attempted) | "ok" | "failed" | "skipped (on line)"
    reason: str = ""
    # #596 Part A: bounded 2 Hz state+command trace, with every recovery forced into the stream.
    # This makes a capped stall diagnosable from report.json (gear/RPM/controls/position/action)
    # instead of leaving only the final distance and a screenshot.
    control_trace: list[dict[str, Any]] = field(default_factory=list)
    control_trace_truncated: bool = False
    # Driver-specific result payload flowing OUT through the normal return value (not a config
    # side-channel): the #532 handshake result (ok/result/constants/diagnostics) lands here.
    payload: dict = field(default_factory=dict)


def drive_leg_succeeded(stats: DriveStats | None) -> bool:
    """Pure verdict on the drive leg — the motion half of :func:`run_auto_drive`'s success gate.

    True only when the car really drove and no veto fired. Each False case is a real #528-class
    failure that MUST stay caught (never leaked into a green report):

    * ``stats is None`` — the hijack never landed, so no drive leg ran at all.
    * ``not stats.drove`` — the car never cleared the distance/speed floor (a pit-start stall that
      never moves reads ``drove=False`` at 0 m).
    * ``stats.sim_dead`` — ``acs.exe`` died mid-run; the totals are stale (#459/#460).
    * ``stats.session_replaced`` — another harness/CM launch replaced the session (#555).
    * ``stats.recovery_capped`` — the car kept stalling until the recovery cap; it never sustained
      progress whatever the totals say (the pit-start recovery-cap stall, #528).

    :func:`drive_veto_reason` is the single source of truth for these vetoes; this boolean gate is
    its exact inverse. :func:`run_auto_drive` composes it with the pipeline verdict and error state,
    while the false-green KPI corpus (`false_green_kpi.py`) exercises it directly.
    """
    return drive_veto_reason(stats) == ""


def drive_veto_reason(stats: DriveStats | None) -> str:
    """The drive-leg half of :func:`compose_failure_reason` — "" when the drive leg is clean.

    This is the single source of truth consumed by :func:`drive_leg_succeeded`, so a new veto cannot
    make the run fail without also supplying a reason. Each branch prefers the reason the drive loop
    already recorded (it carries the live detail — the stall distance, the stagnant packet) and
    falls back to a description of the veto itself, because an empty ``reason`` is exactly the #596
    Part C failure.
    """
    if stats is None:
        return "drive: no drive leg ran (the hijack never landed)"
    if stats.sim_dead:
        return stats.reason or "drive: acs.exe died mid-run (acpmf_physics packet_id stagnant)"
    if stats.session_replaced:
        return stats.reason or (
            f"drive: another launch replaced this session (sim_pid={stats.sim_pid}, "
            f"unexpected={stats.unexpected_sim_pids})"
        )
    if stats.recovery_capped:
        return stats.reason or (
            f"drive: recovery cap exceeded after {stats.recoveries} recoveries "
            f"at {stats.total_distance_m:.0f}m"
        )
    if not stats.drove:
        return stats.reason or (
            f"drive: car never cleared the distance/speed floor "
            f"(dist={stats.total_distance_m:.0f}m max_speed={stats.max_speed_kmh:.1f}km/h)"
        )
    return ""


def compose_failure_reason(
    *,
    error: str | None,
    seq_ok: bool | None,
    checks: list[Check],
    stats: DriveStats | None,
) -> str:
    """The single actionable root cause of a failed run — "" only when nothing failed (#596 Part C).

    The #596 repro: a run drove 2 laps / 6138 m and wrote a valid lap archive, yet reported
    ``ok=False`` with an **empty** reason, because the only ``reason`` field lived on
    :class:`DriveStats` and the drive leg had not failed — the *pipeline* had. The failing
    :class:`Check` was computed by :func:`evaluate_sequence` and then dropped on the floor, so the
    bundle could not be triaged at all: indistinguishable from a real fault.

    Precedence is "most authoritative cause first", matching the gate in :func:`run_auto_drive`
    (``bool(seq_ok) and drive_leg_succeeded(stats) and error is None``):

    1. ``error`` — a raised stage failure is the root cause; the later legs never honestly ran.
    2. a **drive-leg veto** — a dead/stalled sim makes the pipeline fail *as a consequence*, so
       reporting "tire_temps never seen" over "acs.exe died" would name the symptom, not the cause.
    3. the **pipeline** verdict — name the exact failing checks (the #596 Part C acceptance
       criterion: "says exactly which assert failed").

    The final fallback can only be reached if a future caller adds a veto to the ``ok`` gate without
    adding it here; it stays non-empty on purpose — a wrong reason is triageable, an empty one is
    not.
    """
    if error:
        return error
    veto = drive_veto_reason(stats)
    if veto:
        return veto
    if seq_ok is False:
        failed = [c for c in checks if not c.ok]
        if failed:
            detail = "; ".join(f"{c.name} ({c.detail})" for c in failed)
            return f"pipeline: failed {len(failed)}/{len(checks)} checks: {detail}"
        # seq_ok was forced False by a caller-side assert (e.g. the #579 timed-lap window) that
        # records its finding in notes rather than as a Check.
        return "pipeline: sequence verdict FAILED (see notes for the failing assert)"
    if seq_ok is None:
        return "pipeline: no sequence verdict — the tap/eval never completed"
    return "run failed with no identified cause (report this — the reason composer has a gap)"


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
    stage: (
        str  # preflight | alien_line | launch | hijack | setup | pipeline | drive | cleanup | done
    )
    launched: bool = False
    hijacked: bool = False
    drive: DriveStats | None = None
    sequence_ok: bool | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    # #596 Part C: the per-check verdicts from `evaluate_sequence` — previously computed and
    # dropped, which is why a failed pipeline could not name its own failing assert in report.json.
    checks: list[Check] = field(default_factory=list)
    # Whether the post-lap grace-drive ran (drove past S/F so the async writer finalizes the lap
    # archive). The single source of truth the evidence-bundle poll gates on, so the grace condition
    # and the poll condition can never diverge (#515/#516 review).
    lap_grace_applied: bool = False
    # #577: per-lap times (ms, stream order) of every TIMED lap boundary the tap observed, plus
    # the requested lap budget — the flying-lap-window evidence consumers key on (the self-play
    # iteration verdict, the per-iteration trajectory report).
    lap_times_ms: list[int] = field(default_factory=list)
    laps_requested: int = 0
    # #531 Part D: electronics-intervention evidence from the `telemetry_tick` stream — per-flag
    # true/false/absent counts (see sequence_probe.intervention_summary). This is the acceptance
    # criterion's proof surface: before it, "did the TC/ABS flash fire?" could only be answered by
    # a human watching the tablet, and the in-run tap could not see the channel at all.
    # None = the tap did not run (a failure before the pipeline stage), which is NOT "no ticks".
    intervention: dict | None = None
    # Combo identity + setup verification (#459 Parts A/C) — evidence consumers key on these.
    car_id: str | None = None
    track_id: str | None = None
    setup_requested: str | None = None
    setup_applied: bool | None = None  # None = no setup requested
    setup_ack: dict | None = None  # the in-sim `setup.load.ack` (name/path/error)
    # #737: True exactly when setup fuel-verification missed while the loaded combo was NOT
    # positively mismatched — the #466 CM race.ini re-bake race signature.  The retry wrapper
    # treats only this terminal state as worth a fresh launch cycle; wiring failures and
    # exhausted cached-session mismatches (#537) stay non-retryable.
    setup_race_suspected: bool = False
    # #596 Part B: complete per-attempt reports from the bounded sim-death retry wrapper.  The
    # final report stays at the top level for backward compatibility; this list makes a recovered
    # crash visible and preserves its control trace/checks instead of laundering it into PASS.
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def cleanup_holds(self) -> tuple[Controller, ...]:
        """Non-serialized telemetry mapping owners retained for process-lifetime cleanup."""
        return tuple(getattr(self, "_cleanup_holds", ()))

    def retain_cleanup_controller(self, controller: Controller) -> None:
        """Keep a failed read-only mapping reachable without polluting JSON evidence."""
        holds = getattr(self, "_cleanup_holds", None)
        if holds is None:
            holds = []
            self._cleanup_holds = holds
        if not any(retained is controller for retained in holds):
            holds.append(controller)

    @property
    def reason(self) -> str:
        """Current run-level root cause: non-empty exactly when this report fails (#596 Part C).

        This is computed rather than stored because ``apply_handshake_outcome`` mutates ``ok`` and
        ``error`` after construction. A stored value would be stale until some serializer repaired
        it, leaving direct ``report.reason`` consumers with an invalid public state (Cursor review
        on PR #598). Computing from the same live inputs as the success gate keeps direct reads,
        summaries, and evidence JSON consistent without mutation side effects.
        """
        if self.ok:
            return ""
        return compose_failure_reason(
            error=self.error,
            seq_ok=self.sequence_ok,
            checks=self.checks,
            stats=self.drive,
        )

    def summary(self) -> str:
        lines = [f"auto-drive: {'PASS' if self.ok else 'FAIL'} (stage={self.stage})"]
        # #596 Part C: lead a FAIL with its root cause — the operator reads this line, not the JSON.
        if self.reason:
            lines.append(f"  reason: {self.reason}")
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
                f"recoveries={d.recoveries} sim_dead={d.sim_dead} "
                f"session_replaced={d.session_replaced}"
                + (f" sim_pid={d.sim_pid}" if d.sim_pid is not None else "")
                + (f" unexpected_sim_pids={d.unexpected_sim_pids}" if d.unexpected_sim_pids else "")
                + (f" spawn_teleport={d.spawn_teleport}" if d.spawn_teleport else "")
                + (f" reason={d.reason}" if d.reason else "")
            )
        if self.attempts:
            sim_deaths = sum(
                1
                for attempt in self.attempts
                if isinstance(attempt.get("drive"), dict)
                and attempt["drive"].get("sim_dead") is True
            )
            setup_races = sum(
                1 for attempt in self.attempts if attempt.get("setup_race_suspected") is True
            )
            lines.append(
                f"  attempts: {len(self.attempts)} (detected sim deaths={sim_deaths}, "
                f"setup races={setup_races}, "
                f"retry budget={max(len(self.attempts) - 1, 0)} used)"
            )
        if self.lap_times_ms:
            times = ", ".join(f"{ms / 1000.0:.3f}s" for ms in self.lap_times_ms)
            requested = f" (requested {self.laps_requested})" if self.laps_requested else ""
            lines.append(f"  laps timed: {len(self.lap_times_ms)}{requested}: {times}")
        if self.sequence_ok is not None:
            lines.append(f"  pipeline: {'ok' if self.sequence_ok else 'FAILED'}")
            if self.counts:
                lines.append(
                    "  frames: " + ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
                )
            for note in self.notes:
                lines.append(f"  note: {note}")
        if self.intervention is not None:
            ticks = self.intervention.get("telemetry_ticks", 0)
            flags = self.intervention.get("flags", {})
            detail = "  ".join(
                # `absent` is reported explicitly: it is the honest reading for a car that does not
                # fit the system (the M3 GT2 has no ABS) AND for a CSP field name that failed to
                # resolve. Collapsing it into `false` would hide a producer bug as a quiet lap.
                f"{name}: fired={f['true']} idle={f['false']} absent={f['absent']}"
                for name, f in sorted(flags.items())
            )
            lines.append(f"  intervention: telemetry_ticks={ticks}  {detail}")
        if self.error:
            lines.append(f"  error: {self.error}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for the evidence bundle (``report.json``)."""
        payload = asdict(self)
        # Dataclasses serialize fields, not computed properties. Keep the stable report.json key
        # while sourcing it from the same always-current property direct callers read.
        payload["reason"] = self.reason
        return payload


class Controller(Protocol):
    """The subset of :class:`custom_ai.CustomAIController` the drive loop needs (test seam)."""

    def write_controls(self, gas: float, brake: float, steer: float, **kwargs: Any) -> None: ...
    def read_car_data(self) -> dict[str, object] | None: ...
    def teleport_to_pits(self) -> None: ...
    def close(self) -> None: ...


class ControllerCleanupError(RuntimeError):
    """A Custom-AI controller could not release its native shared-memory resources."""


class ControllerTelemetryCleanupPending(ControllerCleanupError):
    """CarControls released, but a read-only mapping remains owned for later/process cleanup."""

    def __init__(self, message: str, controller: Controller) -> None:
        super().__init__(message)
        self.controller = controller


class ControllerCleanupAbort(SystemExit):
    """Fail-closed abort that retains a controller until process teardown releases its mapping."""

    def __init__(self, error: ControllerCleanupError, controller: Controller) -> None:
        super().__init__(f"fatal controller cleanup failure: {error}")
        self.controller = controller
        self._cleanup_holds: list[Controller] = [controller]
        self.cleanup_hold: ExitStack | None = None

    @property
    def cleanup_holds(self) -> tuple[Controller, ...]:
        """All native mapping owners that must remain reachable until process teardown."""
        return tuple(self._cleanup_holds)

    def retain_cleanup_controller(self, controller: Controller) -> None:
        """Attach an earlier telemetry-only owner to this fail-closed abort."""
        if not any(retained is controller for retained in self._cleanup_holds):
            self._cleanup_holds.append(controller)


CleanupFailureFn = Callable[[Controller, ControllerCleanupError], bool]


def _close_controller(
    controller: Controller,
    *,
    context: str,
    cleanup_failure: CleanupFailureFn | None = None,
    attempts: int = 3,
) -> None:
    """Release a controller without ever abandoning a live Custom-AI control mapping.

    ``CustomAIController.close`` preserves whichever native handle/view failed to release, so a
    retry is meaningful: successfully released members remain cleared and only failed resources
    are retried. If all attempts fail, the rig callback must make AC safe and return ``True`` only
    after confirming ``acs.exe`` is gone. Without that proof, abort while retaining ``controller``
    on the exception; process teardown then releases the mapping instead of a normal return
    silently dropping the last owner.
    """
    try:
        close_controller_with_retries(controller, attempts=attempts)
        return
    except ControllerCloseRetryError as exc:
        last_error = exc.last_error
        failed_attempts = exc.attempts
        controls_retained = exc.controls_retained
    except BaseException as exc:
        interrupted_error = ControllerCleanupError(
            f"{context}: {type(exc).__name__}: {exc} "
            "(interrupted during controller close; control ownership unknown)"
        )
        raise ControllerCleanupAbort(interrupted_error, controller) from exc
    error = ControllerCleanupError(
        f"{context}: {type(last_error).__name__}: {last_error} "
        f"(failed after {failed_attempts} close attempts)"
    )
    error.__cause__ = last_error
    if not controls_retained:
        raise ControllerTelemetryCleanupPending(
            f"{error}; CarControls ownership released, read-only telemetry mapping retained",
            controller,
        ) from last_error
    try:
        safety_confirmed = (
            cleanup_failure(controller, error) if cleanup_failure is not None else False
        )
    except ControllerCleanupAbort:
        raise
    except BaseException as exc:  # noqa: BLE001 - interrupts must retain controller and rig lock
        error.add_note(f"cleanup safety action failed: {type(exc).__name__}: {exc}")
        raise ControllerCleanupAbort(error, controller) from exc
    if not safety_confirmed:
        raise ControllerCleanupAbort(error, controller)

    # AC is confirmed absent, so the control mapping can no longer command a live car. Try once
    # more to release the local native resources. The run still fails: needing to kill AC is never
    # a successful cleanup, even when this last local close succeeds.
    try:
        controller.close()
    except ControllerCleanupAbort:
        raise
    except BaseException as exc:  # noqa: BLE001 - retain mapping and rig lock on every failure
        final_error = ControllerCleanupError(
            f"{error}; AC safety shutdown confirmed, but final local release failed: "
            f"{type(exc).__name__}: {exc}"
        )
        raise ControllerCleanupAbort(final_error, controller) from exc
    raise ControllerCleanupError(f"{error}; AC safety shutdown confirmed")


LaunchFn = Callable[[AutoDriveConfig], "tuple[bool, str]"]
HijackFn = Callable[[AutoDriveConfig], "Controller | None"]
ApplySetupFn = Callable[[AutoDriveConfig], Awaitable[dict]]
DriveFn = Callable[[Controller, AutoDriveConfig, threading.Event], DriveStats]
TapFn = Callable[..., Awaitable[list[dict]]]
# Returns the loaded (track, car) identity from the live sim, or None when it cannot be read.
VerifyTrackFn = Callable[[AutoDriveConfig], "tuple[str | None, str | None] | None"]
# #558: called on a cached-session mismatch to RESTART the launcher (kill Content Manager) so the
# next launch cold-starts a fresh CM — the recovery a plain URL re-issue cannot perform.
RestartLauncherFn = Callable[[AutoDriveConfig], None]


def rig_force_safe_after_cleanup_failure(
    controller: Controller,
    error: ControllerCleanupError,
) -> bool:  # pragma: no cover - rig-only
    """Brake, terminate AC, and confirm absence after persistent controller cleanup failure."""
    from tools.ac_harness.entry_launcher import terminate_process_tree_confirmed_absent

    try:
        controller.write_controls(0.0, 1.0, 0.0, handbrake=0.0)
    except Exception as exc:  # noqa: BLE001 - taskkill remains the authoritative safety action
        _log(f"controller cleanup safety brake failed: {type(exc).__name__}: {exc}")

    _log(f"FATAL {error}; terminating acs.exe before releasing controller ownership")
    safe = terminate_process_tree_confirmed_absent(
        "acs.exe",
        timeout=3.0,
        poll=0.1,
        absent_confirmations=2,
        log=lambda message: _log(f"controller cleanup safety action: {message}"),
    )
    if safe:
        _log("controller cleanup safety action confirmed: acs.exe is absent")
    else:
        _log("FATAL could not confirm acs.exe safety shutdown")
    return safe


def rig_verify_track(
    config: AutoDriveConfig,
) -> tuple[str | None, str | None] | None:  # pragma: no cover - rig-only
    """Read the loaded ``(track, car)`` identity from ``acpmf_static``; ``None`` when unreadable.

    Returning ``None`` (static page absent/short) makes the guard skip rather than block — a
    missing read must never fail a run; only a POSITIVE mismatch does.
    """
    from tools.ac_harness.shared_memory import (
        SHM_STATIC,
        STATIC_MAP_BYTES,
        open_shared_memory,
        parse_static_car,
        parse_static_track,
    )

    try:
        section = open_shared_memory(SHM_STATIC, STATIC_MAP_BYTES)
    except Exception:  # noqa: BLE001 - unavailable/platform error → cannot confirm, skip guard
        return None
    try:
        buf = section.read(STATIC_MAP_BYTES)
        return parse_static_track(buf), parse_static_car(buf)
    except Exception:  # noqa: BLE001 - short/garbled read → cannot confirm, skip guard
        return None
    finally:
        section.close()


def track_ids_match(requested: str, loaded: str) -> bool:
    """Whether a loaded AC track id satisfies the requested one (pure, case-insensitive).

    AC track ids are plain folder names (``magione``, ``spa``); ``acpmf_static.track`` reports the
    **base** id only — the layout is NOT exposed via shared memory — so this compares base ids.
    That catches the observed failure (CM launched a cached session on a different *base* track,
    #532). A same-base-but-different-layout cached session is a narrower residual not verifiable
    from ``acpmf_static``; it is tracked with the CM-cached-session root cause in #537. An empty
    loaded id (static page not yet published) is "cannot confirm" -> match, so the guard never
    blocks on a missing read; only a POSITIVE, different base id fails.
    """
    want = (requested or "").strip().lower()
    got = (loaded or "").strip().lower()
    if not want or not got:
        return True
    return want == got


def loaded_combo_mismatch(
    config: AutoDriveConfig, loaded: tuple[str | None, str | None] | None
) -> str | None:
    """Human-readable reason when the loaded ``(track, car)`` differs from the requested combo.

    Returns ``None`` when it matches OR cannot be confirmed (``loaded is None``, or an empty id per
    :func:`track_ids_match`) — a missing read never blocks; only a POSITIVE, different base id does.
    Pure, so the same "CM served a cached session" verdict (#532/#537) is shared by the post-hijack
    guard AND the setup-verify path (a cached wrong session also fails setup fuel verification).
    """
    if loaded is None:
        return None
    loaded_track, loaded_car = loaded
    if not track_ids_match(config.track_id, loaded_track):
        return f"track {loaded_track!r} != requested {config.track_id!r}"
    if config.car_id and not track_ids_match(config.car_id, loaded_car):
        return f"car {loaded_car!r} != requested {config.car_id!r}"
    return None


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


def setup_ack_fuel_mismatch(ack: dict | None) -> bool:
    """Pure check that a failed setup ack is a genuine fuel-verify miss (#737).

    Only the rig leg's fuel verification failing qualifies: ``ok`` is not true AND the parsed
    ``expected_fuel`` is present — the leg read the setup's ``[FUEL]`` and the live physics fuel
    refused to match within the tolerance window.  Deterministic failures (no ack, unresolved or
    unreadable setup ini, an ack naming a different setup) must NOT look like the transient
    re-bake race: retrying them wastes a full launch cycle on a wiring bug.
    """
    return isinstance(ack, dict) and ack.get("ok") is not True and "expected_fuel" in ack


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
    verify_track: VerifyTrackFn | None = None,
    restart_launcher: RestartLauncherFn | None = None,
    cleanup_failure: CleanupFailureFn | None = None,
    press_start: Callable[[], Awaitable[dict | None]] | None = None,
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
    telemetry_cleanup_holds: list[Controller] = []

    def retain_abort_cleanup_holds(exc: ControllerCleanupAbort) -> None:
        for retained_controller in telemetry_cleanup_holds:
            exc.retain_cleanup_controller(retained_controller)

    def finish(report: AutoDriveReport) -> AutoDriveReport:
        prior_notes = [note for note in launch_notes if note not in report.notes]
        report.notes[:0] = prior_notes
        for retained_controller in telemetry_cleanup_holds:
            report.retain_cleanup_controller(retained_controller)
        return report

    attempts = 1 if config.skip_launch else max(1, config.max_launches)
    launch_config = replace(config, max_launches=1)
    launched_once = config.skip_launch
    last_launch_error = ""
    launch_notes: list[str] = []
    # #558: cold-start a FRESH Content Manager before a relaunch when the previous attempt signalled
    # a stale CM. A stale CM keeps serving its cached session / stalling the pre-drive overlay no
    # matter how often the acmanager:// URL is re-issued, so the only real recovery is a CM restart.
    restart_cm_next = False
    for attempt_idx in range(attempts):
        if not config.skip_launch:
            # Restart CM before relaunching when the last attempt hit a cached-session mismatch
            # (``restart_cm_next`` — a clear staleness signal) OR plain relaunches have already
            # failed twice (``attempt_idx >= 2`` — persistent degradation). A transient pre-drive
            # overlay race still gets ONE plain relaunch first. Best-effort: a restart failure still
            # relaunches, and the terminal attempt FAILs honestly.
            if (
                attempt_idx > 0
                and restart_launcher is not None
                and (restart_cm_next or attempt_idx >= 2)
            ):
                try:
                    restart_launcher(config)
                    _log("relaunch: restarted Content Manager for a fresh cold-start")
                except Exception as exc:  # noqa: BLE001 - never crash the run on a restart failure
                    _log(f"relaunch: Content Manager restart failed ({type(exc).__name__}: {exc})")
            restart_cm_next = False
            ok, reason = launch(launch_config)
            if not ok:
                last_launch_error = reason
                continue
            launched_once = True
            # #738 forensics: a successful launch's detail (attempt count, csp_dialog_skips
            # evidence) must survive into report.json — overnight ladders read the evidence
            # bundle, not the console stream, and this string was previously dropped on success.
            launch_notes.append(f"launch: {reason}")
            # Reset so the post-loop stage report reflects THIS attempt's terminal cause, not a
            # stale launch/mismatch error from an earlier attempt (#537 Codex P2 observability): a
            # relaunch that reaches LIVE but fails to hijack must read as stage="hijack", while one
            # that never reaches LIVE (or re-serves a cached session) reads as stage="launch".
            last_launch_error = ""
        # The setup is BAKED at launch (AC only applies setups at spawn; the WS load is gated shut
        # for an autonomous car). Verify it BEFORE the hijack — the fuel read needs no hijack, and
        # a wrong setup must fail the run before it drives (#459 Part A). On a relaunch the launch
        # leg re-bakes, so this re-verifies each attempt.
        if config.setup:
            if apply_setup is None:
                return finish(
                    AutoDriveReport(
                        ok=False,
                        stage="setup",
                        launched=not config.skip_launch,
                        setup_requested=setup_requested,
                        setup_applied=False,
                        error="setup requested but no apply_setup leg wired",
                        **identity,
                    )
                )
            try:
                setup_ack = await apply_setup(config)
            except Exception as exc:  # noqa: BLE001 - a setup-leg crash is a run FAIL
                return finish(
                    AutoDriveReport(
                        ok=False,
                        stage="setup",
                        launched=not config.skip_launch,
                        setup_requested=setup_requested,
                        setup_applied=False,
                        error=f"setup verify failed: {type(exc).__name__}: {exc}",
                        **identity,
                    )
                )
            ok_setup, detail = verify_setup_ack(setup_ack, setup_requested)
            setup_applied = ok_setup
            if not ok_setup:
                # #537: a cached wrong session (CM served its last session) ALSO fails setup
                # verification — its fuel won't match the requested setup. Setup is verified before
                # the post-hijack track guard, so without this a --setup run would abort at
                # stage="setup" on the very first cached session and never consume the retry budget.
                # This is a BEST-EFFORT, FAIL-SAFE early-out — NOT the authoritative guard. It reads
                # acpmf_static before the hijack, where the static page may not yet be populated; on
                # "cannot confirm" it does NOT drive — it falls through to the setup-stage return
                # below (safe), and the authoritative post-hijack guard remains the single
                # source of truth for a session that DOES reach the drive leg. Only a POSITIVE early
                # mismatch relaunches (bounded); a genuine setup failure on the CORRECT combo still
                # fails fast at stage="setup" (combo_mismatch is None → skip).
                combo_mismatch = loaded_combo_mismatch(
                    config, verify_track(config) if verify_track is not None else None
                )
                if (
                    combo_mismatch is not None
                    and attempt_idx < attempts - 1
                    and not config.skip_launch
                ):
                    last_launch_error = (
                        f"setup verify failed on a cached session ({combo_mismatch}): {detail}"
                    )
                    restart_cm_next = True  # #558: cached session => cold-start a fresh CM next
                    _log(
                        f"setup guard: {combo_mismatch} (CM cached session — setup fuel mismatch) "
                        f"— relaunching (attempt {attempt_idx + 2}/{attempts})"
                    )
                    continue
                return finish(
                    AutoDriveReport(
                        ok=False,
                        stage="setup",
                        launched=not config.skip_launch,
                        setup_requested=setup_requested,
                        setup_applied=False,
                        setup_ack=setup_ack,
                        # #737: a fuel-verify miss WITHOUT a positive combo mismatch is the #466
                        # re-bake race signature — the one setup failure the retry wrapper may
                        # answer with a fresh launch cycle.  A cached-session mismatch already
                        # consumed the in-loop relaunch budget above and stays terminal.
                        setup_race_suspected=(
                            combo_mismatch is None and setup_ack_fuel_mismatch(setup_ack)
                        ),
                        error=(
                            f"setup not applied: {detail}"
                            + (
                                " (Content Manager served a cached session: "
                                f"{combo_mismatch}; still "
                                f"mismatched after {attempts} launch attempt(s))"
                                if combo_mismatch is not None
                                else ""
                            )
                        ),
                        **identity,
                    )
                )
        # #627/#466: press AC's Start button from INSIDE the sim before probing for Car0.
        #
        # AC parks at its pre-drive screen; CSP therefore never exposes Car0 and the carcsw
        # hijack below can never land. The harness cannot break that from outside — the hijack
        # IS how it would supply input, but the hijack needs the session started. Measured
        # 2026-07-29: 0 landed drives / 6 invocations. Content Manager's "Start race
        # immediately" cannot help: CM's own source disables it whenever CSP is installed
        # (`if (!...ImmediateStart || PatchHelper.IsActive()) return;`), so it is a designed
        # no-op on this rig even though the checkbox is ticked.
        #
        # The supported lever is CSP's `ac.tryToStart`, reachable only from in-sim Lua — and our
        # app is already loaded there. Best-effort by design: a failure here must NOT fail the
        # run, because the hijack probes are still the authoritative drivability oracle and a
        # session that was ALREADY driving needs no press at all.
        if press_start is not None:
            try:
                ack = await press_start()
            except Exception as exc:  # noqa: BLE001 - never let the press fail the run
                _log(f"session.start: press failed ({type(exc).__name__}: {exc}); probing anyway")
            else:
                if ack is None:
                    _log("session.start: no ack from the in-sim app; probing anyway")
                else:
                    if ack.get("type") == "error":
                        _log(
                            "session.start: sidecar REJECTED the relay: "
                            f"{ack.get('message') or ack}"
                        )
                    else:
                        _log(
                            "session.start: "
                            f"ok={ack.get('ok')} started={ack.get('started')} "
                            f"already_started={ack.get('already_started')}"
                            + (f" error={ack.get('error')!r}" if ack.get("error") else "")
                        )
        try:
            controller = hijack(config)
        except ControllerCleanupAbort as exc:
            retain_abort_cleanup_holds(exc)
            raise
        except ControllerTelemetryCleanupPending as exc:
            telemetry_cleanup_holds.append(exc.controller)
            report = AutoDriveReport(
                ok=False,
                stage="cleanup",
                launched=not config.skip_launch,
                setup_requested=setup_requested,
                setup_applied=setup_applied,
                setup_ack=setup_ack,
                error=str(exc),
                **identity,
            )
            return finish(report)
        except ControllerCleanupError as exc:
            cleanup_detail = str(exc)
            if attempt_idx < attempts - 1 and not config.skip_launch:
                launch_notes.append(cleanup_detail)
                restart_cm_next = True
                _log(
                    "hijack cleanup made AC safe; retrying a fresh launch "
                    f"(attempt {attempt_idx + 2}/{attempts})"
                )
                continue
            return finish(
                AutoDriveReport(
                    ok=False,
                    stage="cleanup",
                    launched=not config.skip_launch,
                    setup_requested=setup_requested,
                    setup_applied=setup_applied,
                    setup_ack=setup_ack,
                    error=cleanup_detail,
                    **identity,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a hijack-leg crash is a structured run failure
            return finish(
                AutoDriveReport(
                    ok=False,
                    stage="hijack",
                    launched=not config.skip_launch,
                    setup_requested=setup_requested,
                    setup_applied=setup_applied,
                    setup_ack=setup_ack,
                    error=f"hijack failed: {type(exc).__name__}: {exc}",
                    **identity,
                )
            )
        if controller is not None:
            # AUTHORITATIVE identity guard (#532/#535). CM sometimes launches its cached last
            # session instead of the requested preset; driving the requested line on a different
            # track — or persisting a plant artifact under the requested car when a DIFFERENT car
            # is loaded — is a guaranteed corruption. This runs POST-hijack on purpose: a landed
            # hijack means CSP created Car0, a STRONGER "session fully initialised" signal than
            # _wait_live's LIVE + advancing-physics, so acpmf_static is reliably populated here
            # (#535 rig-proven). This is the single source of truth — every drivable session passes
            # through it — a not-yet-populated static page can never slip a mismatch to the drive.
            mismatch = loaded_combo_mismatch(
                config, verify_track(config) if verify_track is not None else None
            )
            if mismatch is not None:
                # #537: CM served its cached last session. RELAUNCH (bounded) rather than drive
                # the wrong line — the next launch kills acs.exe and re-issues the acmanager://
                # Quick-Drive URL to the now-running CM, which processes it via single-instance
                # IPC without the cold-start auto-resume race that served the stale combo. Only
                # the terminal attempt — or skip_launch, which has no launch leg to relaunch —
                # FAILs fast at stage="launch", preserving the #535/#532 honest-failure guard so
                # the harness never drives a mismatched combo or persists a mislabeled plant.
                try:
                    _close_controller(
                        controller,
                        context=f"cleanup after rejecting mismatched {mismatch}",
                        cleanup_failure=cleanup_failure,
                    )
                except ControllerCleanupAbort as exc:
                    retain_abort_cleanup_holds(exc)
                    raise
                except ControllerTelemetryCleanupPending as exc:
                    cleanup_detail = str(exc)
                    telemetry_cleanup_holds.append(exc.controller)
                    controller = None
                    last_launch_error = (
                        f"loaded {mismatch} — Content Manager launched a cached session"
                    )
                    if attempt_idx < attempts - 1 and not config.skip_launch:
                        launch_notes.append(cleanup_detail)
                        restart_cm_next = True
                        _log(
                            f"track/car guard: {mismatch} (CM cached session; read-only cleanup "
                            f"retained) — relaunching (attempt {attempt_idx + 2}/{attempts})"
                        )
                        continue
                    return finish(
                        AutoDriveReport(
                            ok=False,
                            stage="launch",
                            launched=not config.skip_launch,
                            hijacked=True,
                            setup_requested=setup_requested,
                            setup_applied=setup_applied,
                            setup_ack=setup_ack,
                            error=(
                                f"loaded {mismatch} — Content Manager launched a cached session; "
                                "the harness will not drive the requested line on a different combo"
                            ),
                            notes=[*launch_notes, cleanup_detail],
                            **identity,
                        )
                    )
                except ControllerCleanupError as exc:
                    cleanup_detail = str(exc)
                    controller = None
                    last_launch_error = (
                        f"loaded {mismatch} — Content Manager launched a cached session"
                    )
                    if attempt_idx < attempts - 1 and not config.skip_launch:
                        launch_notes.append(cleanup_detail)
                        restart_cm_next = True
                        _log(
                            f"track/car guard: {mismatch} (CM cached session; cleanup required "
                            f"AC safety shutdown) — relaunching (attempt "
                            f"{attempt_idx + 2}/{attempts})"
                        )
                        continue
                    return finish(
                        AutoDriveReport(
                            ok=False,
                            stage="launch",
                            launched=not config.skip_launch,
                            hijacked=True,
                            setup_requested=setup_requested,
                            setup_applied=setup_applied,
                            setup_ack=setup_ack,
                            error=(
                                f"loaded {mismatch} — Content Manager launched a cached session; "
                                "the harness will not drive the requested line on a different combo"
                            ),
                            notes=[*launch_notes, cleanup_detail],
                            **identity,
                        )
                    )
                controller = None
                last_launch_error = f"loaded {mismatch} — Content Manager launched a cached session"
                if attempt_idx < attempts - 1 and not config.skip_launch:
                    restart_cm_next = True  # #558: cached session => cold-start a fresh CM next
                    _log(
                        f"track/car guard: {mismatch} (CM cached session) — relaunching "
                        f"(attempt {attempt_idx + 2}/{attempts})"
                    )
                    continue
                return finish(
                    AutoDriveReport(
                        ok=False,
                        stage="launch",
                        launched=not config.skip_launch,
                        hijacked=True,
                        setup_requested=setup_requested,
                        setup_applied=setup_applied,
                        setup_ack=setup_ack,
                        error=(
                            f"loaded {mismatch} — Content Manager launched a cached session; "
                            f"still mismatched after {attempts} launch attempt(s) (the harness "
                            "will not drive the requested line on a different combo or persist a "
                            "mislabeled plant)"
                        ),
                        **identity,
                    )
                )
            break
        if config.skip_launch:
            break

    if controller is None:
        if not launched_once:
            return finish(
                AutoDriveReport(
                    ok=False,
                    stage="launch",
                    launched=False,
                    error=last_launch_error or "sim never reached LIVE",
                    **identity,
                )
            )
        if last_launch_error:
            # The most recent attempt failed at launch (never reached LIVE) or re-served a cached
            # session — report that, not a generic hijack failure, so the evidence bundle points at
            # the real subsystem (#537 Codex P2). Cleared on every successful launch above, so a
            # true hijack failure (launch OK, no controller) still reads as stage="hijack" below.
            return finish(
                AutoDriveReport(
                    ok=False,
                    stage="launch",
                    launched=not config.skip_launch,
                    setup_requested=setup_requested,
                    setup_applied=setup_applied,
                    setup_ack=setup_ack,
                    error=last_launch_error,
                    **identity,
                )
            )
        return finish(
            AutoDriveReport(
                ok=False,
                stage="hijack",
                launched=not config.skip_launch,
                setup_requested=setup_requested,
                setup_applied=setup_applied,
                setup_ack=setup_ack,
                error="CSP did not accept the carcsw hijack",
                **identity,
            )
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
    checks: list[Check] = []
    notes: list[str] = list(launch_notes)
    grace_applied = False
    # None until the tap actually returns frames — a tap that raised must not report "0 ticks"
    # (indistinguishable from a healthy tap on a silent producer). See AutoDriveReport.intervention.
    intervention: dict | None = None
    # A fuel-less setup is baked but not fuel-confirmed — surface that in the report so a setup
    # A/B run does not read `setup_applied=True` as "independently verified" (#460 review).
    if setup_ack is not None and setup_applied and setup_ack.get("expected_fuel") is None:
        notes.append(f"setup baked but UNCONFIRMED: {setup_ack.get('detail', 'no fuel key')}")
    error: str | None = None
    stage = "done"
    lap_times_ms: list[int] = []
    try:
        # #531 Part D: the composed drive is the caller that needs intervention evidence, so it
        # explicitly opts into the 20 Hz tick fan-out. Keep generic ``tap_frames`` classless by
        # default: its topic subscription must not silently imply a high-rate peripheral stream.
        tap_kwargs: dict[str, Any] = dict(
            seconds=config.tap_seconds,
            wait_for_lap=config.wait_lap,
            client_class=CLIENT_CLASS_OBSERVER,
        )
        if config.wait_lap:
            # The SAME settle + lap deadline the drive budget is sized to (above), so the tap never
            # waits past what the drive thread can still drive (a full lap at pace can exceed
            # the 180 s default, Spa ~7 km); #459 F / #516.
            tap_kwargs["settle_timeout"] = tap_settle_s
            tap_kwargs["lap_timeout"] = lap_deadline
            if config.target_laps > 0:
                # #577 flying-lap window: hold the tap open until N TIMED laps (or the shared
                # deadline). Includes N == 1 — a requested one-lap batch must not exit on an
                # untimed out-lap/teleport boundary the way plain --wait-lap may (#579 daemon
                # HIGH). The deadline stays the drive-budget-derived one — "N laps or the time
                # budget, whichever first" — so a shortfall ends honestly, never hangs.
                tap_kwargs["lap_count"] = config.target_laps
        frames = await tap(config.sidecar_url, **tap_kwargs)
        # #531 Part D: derive the electronics-intervention evidence from the SAME captured stream
        # the pipeline checks read, so the tick evidence and the sequence verdict can never come
        # from two different windows.
        intervention = intervention_summary(frames)
        result = evaluate_sequence(
            frames, strict_lifecycle=config.strict, require_lap=config.wait_lap
        )
        seq_ok = result.ok
        counts = dict(result.counts)
        checks = list(result.checks)
        notes.extend(result.notes)
        # #577: the per-lap trajectory is report evidence whenever the lap machinery ran.
        if config.wait_lap:
            from tools.ac_harness.sequence_probe import timed_lap_times_ms

            lap_times_ms = timed_lap_times_ms(frames)
            if config.target_laps > 0 and not lap_times_ms:
                # --laps N contracts for TIMED laps. require_lap alone is satisfiable by an
                # untimed out-lap/teleport boundary, which would exit 0 with an empty
                # trajectory — a false green for the requested window (#579 Codex P2).
                seq_ok = False
                # #596 Part C: record the caller-side assert as a real Check, not only a note.
                # It is the one pipeline failure `evaluate_sequence` cannot see (it owns the topic
                # contract, not the lap-window contract), and a reason that said "see notes" would
                # make the harness's own `--laps N` guard the single least-triageable failure mode
                # (codex on PR #598). As a Check it names itself through the normal reason path.
                checks.append(
                    Check(
                        "laps:timed-window",
                        False,
                        f"requested {config.target_laps} timed, observed ZERO "
                        "(untimed out-lap/teleport boundaries do not count)",
                    )
                )
                notes.append(
                    f"laps: requested {config.target_laps} timed, observed ZERO — "
                    "the window produced no timed lap (untimed boundaries do not count)"
                )
            elif config.target_laps > 0 and len(lap_times_ms) < config.target_laps:
                notes.append(
                    f"laps: requested {config.target_laps}, observed "
                    f"{len(lap_times_ms)} timed within the drive budget"
                )
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
        # A handshake drive (#532) self-terminates (`driver.finished` breaks the rig loop) and
        # must OUTLIVE the tap: stopping at the tap boundary would kill the probe schedule
        # mid-maneuver. Its honest cap is drive_seconds. But a tap/eval EXCEPTION *or* a pipeline
        # check that already FAILED (`seq_ok is False` — e.g. missing continuous topics) still
        # stops it, so the run doesn't burn the whole budget on a pipeline that already failed
        # (Codex review).
        if config.driver != "handshake" or error is not None or seq_ok is False:
            stop.set()
        # Always await the drive AND release the controller — even if the drive thread raised, the
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
            try:
                _close_controller(
                    controller,
                    context="final controller cleanup",
                    cleanup_failure=cleanup_failure,
                )
            except ControllerCleanupAbort as exc:
                retain_abort_cleanup_holds(exc)
                raise
            except ControllerTelemetryCleanupPending as exc:
                telemetry_cleanup_holds.append(exc.controller)
                cleanup_error = str(exc)
                if error is None:
                    stage, error = "cleanup", cleanup_error
                else:
                    notes.append(cleanup_error)
            except ControllerCleanupError as exc:
                cleanup_error = str(exc)
                if error is None:
                    stage, error = "cleanup", cleanup_error
                else:
                    notes.append(cleanup_error)

    # Success needs a clean pipeline AND a real drive that did not die mid-run or stall out. The
    # drive-leg vetoes (drove / sim_dead / recovery_capped) live in drive_leg_succeeded so this gate
    # and the false-green KPI corpus that exercises them cannot drift apart (#528).
    ok = bool(seq_ok) and drive_leg_succeeded(stats) and error is None
    # #596 Part C: `reason` is computed from these same live inputs, so it cannot drift from the
    # `ok` gate computed just above — including after the handshake mutates the report.
    report = AutoDriveReport(
        ok=ok,
        stage=stage,
        launched=not config.skip_launch,
        hijacked=True,
        drive=stats,
        sequence_ok=seq_ok,
        checks=checks,
        lap_grace_applied=grace_applied,
        lap_times_ms=lap_times_ms,
        laps_requested=config.target_laps,
        intervention=intervention,
        counts=counts,
        notes=notes,
        error=error,
        setup_requested=setup_requested,
        setup_applied=setup_applied,
        setup_ack=setup_ack,
        **identity,
    )
    return finish(report)


async def run_auto_drive_with_sim_retries(
    config: AutoDriveConfig,
    *,
    launch: LaunchFn,
    hijack: HijackFn,
    drive: DriveFn,
    tap: TapFn = tap_frames,
    apply_setup: ApplySetupFn | None = None,
    verify_track: VerifyTrackFn | None = None,
    restart_launcher: RestartLauncherFn | None = None,
    cleanup_failure: CleanupFailureFn | None = None,
    press_start: Callable[[], Awaitable[dict | None]] | None = None,
) -> AutoDriveReport:
    """Run the full attempt again after a transient rig failure, bounded and evidenced.

    Two intermittent, launch-curable failure classes are retryable, each on its own budget:

    * **Sim death** (``sim_death_retries``, #596 Part B).  A frozen main-physics packet is already
      the harness's authoritative death oracle.  Retrying inside the drive loop would reuse a dead
      controller/shared-memory session and blur two runs; instead, this coordinator lets
      :func:`run_auto_drive` finish its normal controller teardown and starts the complete
      launch->hijack->drive->tap path again.
    * **Setup re-bake race** (``setup_verify_retries``, #737).  The launch-time setup bake can lose
      CM's race.ini regeneration race (#466) on the CORRECT combo; the car spawns on default fuel
      and verification honestly FAILs at ``stage="setup"``.  Exactly that terminal state
      (``setup_race_suspected``) earns a fresh launch cycle — the relaunch re-bakes the setup.

    The caller holds the machine-global rig lock across this wrapper, so no peer worktree can
    claim the rig between attempts.  Everything else remains an honest terminal failure: a session
    replacement means another launch took ownership; a recovery cap is a controller/track failure;
    a pipeline failure is an assertion failure; a wiring/cached-session setup failure is not the
    race; and ``--skip-launch`` has no launch leg to repeat (a re-verify of the same session would
    read the same fuel).  A persistent setup mismatch still FAILs after the budget — the verify
    gate is never weakened, only re-armed on a fresh launch.
    """

    sim_death_budget = int(config.sim_death_retries)
    if sim_death_budget < 0:
        raise ValueError("sim_death_retries must be >= 0")
    setup_retry_budget = int(config.setup_verify_retries)
    if setup_retry_budget < 0:
        raise ValueError("setup_verify_retries must be >= 0")
    attempt_reports: list[dict[str, Any]] = []
    cleanup_holds: list[Controller] = []
    sim_deaths_used = 0
    setup_retries_used = 0
    while True:
        try:
            report = await run_auto_drive(
                config,
                launch=launch,
                hijack=hijack,
                drive=drive,
                tap=tap,
                apply_setup=apply_setup,
                verify_track=verify_track,
                restart_launcher=restart_launcher,
                cleanup_failure=cleanup_failure,
                press_start=press_start,
            )
        except ControllerCleanupAbort as exc:
            for retained_controller in cleanup_holds:
                exc.retain_cleanup_controller(retained_controller)
            raise
        for retained_controller in report.cleanup_holds:
            if not any(retained is retained_controller for retained in cleanup_holds):
                cleanup_holds.append(retained_controller)
        # Snapshot BEFORE assigning the aggregate list, so nested attempts do not recursively
        # contain themselves.  This is the full attempt (checks, trace, cause), not a lossy summary.
        attempt_reports.append(_attempt_snapshot(report))
        sim_death = bool(
            report.drive is not None
            and report.drive.sim_dead
            and not report.drive.session_replaced
            and not report.drive.recovery_capped
            and report.error is None
        )
        if sim_death and not config.skip_launch and sim_deaths_used < sim_death_budget:
            sim_deaths_used += 1
            _log(
                "sim death: retrying a fresh full launch "
                f"(sim-death retry {sim_deaths_used}/{sim_death_budget})"
            )
            continue
        setup_race = bool(not report.ok and report.stage == "setup" and report.setup_race_suspected)
        if setup_race and not config.skip_launch and setup_retries_used < setup_retry_budget:
            setup_retries_used += 1
            _log(
                "setup verify: fuel mismatch on the requested combo (#466 re-bake race) — "
                "retrying a fresh full launch cycle "
                f"(setup retry {setup_retries_used}/{setup_retry_budget})"
            )
            continue
        for retained_controller in cleanup_holds:
            report.retain_cleanup_controller(retained_controller)
        report.attempts = attempt_reports
        return report


def _attempt_snapshot(report: AutoDriveReport) -> dict[str, Any]:
    """Serialize one attempt without recursively embedding the aggregate attempt history."""

    payload = report.to_dict()
    payload["attempts"] = []
    return payload


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
# Preflight (pure over the filesystem; #459 Part B — fail fast, actionably).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PreflightIssue:
    """One failed preflight assertion, with an actionable message.

    ``severity`` is ``"error"`` (the run cannot proceed) or ``"warning"`` (loud, but the run may
    proceed unless the caller opts into strictness). Default ``"error"`` keeps every pre-#575
    check fatal.
    """

    check: str
    message: str
    severity: str = "error"


def car_content_preflight(car_dir: Path) -> list[PreflightIssue]:
    """Validate the selected car's read-only launch chain: data -> LOD config -> KN5s.

    A car directory and its model files can survive a damaged Content Manager operation while
    ``data.acd`` (or unpacked ``data/``) disappears.  AC then aborts before a drivable session, so
    the harness must classify that as a non-drive content failure instead of paying launch timeouts
    or contaminating drive/sim-death denominators (#603).
    """
    data_dir = car_dir / "data"
    data_acd = car_dir / "data.acd"
    if not data_dir.is_dir() and not data_acd.is_file():
        return [
            PreflightIssue(
                "car_data",
                f"car content is damaged: {car_dir} has neither data.acd nor an unpacked data/ "
                "folder. Restore the car or verify its files in Steam/Content Manager before "
                "running the harness.",
            )
        ]

    lods_raw = read_car_data_member(car_dir, "lods.ini")
    source = data_acd if data_acd.is_file() else data_dir
    if not lods_raw:
        return [
            PreflightIssue(
                "car_lods",
                f"car content is damaged: {source} is unreadable or has no lods.ini. Restore "
                "the car or verify its files in Steam/Content Manager before running the harness.",
            )
        ]

    try:
        try:
            lods_text = lods_raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            lods_text = lods_raw.decode("cp1252")
        parser = configparser.ConfigParser(
            strict=False, interpolation=None, inline_comment_prefixes=(";", "#")
        )
        parser.read_string(lods_text)
    except (UnicodeDecodeError, configparser.Error) as exc:
        return [PreflightIssue("car_lods", f"car lods.ini is unreadable ({source}): {exc}")]

    sections = [section for section in parser.sections() if re.fullmatch(r"LOD_\d+", section, re.I)]
    if not sections:
        return [
            PreflightIssue(
                "car_lods",
                f"car lods.ini in {source} has no [LOD_n] entries; restore or verify the car.",
            )
        ]

    invalid: list[str] = []
    missing: list[str] = []
    for section in sections:
        raw_ref = parser.get(section, "FILE", fallback="").strip().strip('"')
        normalized = raw_ref.replace("\\", "/")
        ref = PurePosixPath(normalized)
        if (
            not normalized
            or normalized.startswith("/")
            or re.match(r"^[A-Za-z]:", normalized)
            or ".." in ref.parts
            or ref.suffix.lower() != ".kn5"
        ):
            invalid.append(f"{section}.FILE={raw_ref or '<missing>'}")
            continue
        candidate = car_dir.joinpath(*ref.parts)
        try:
            usable = candidate.is_file() and candidate.stat().st_size > 0
        except OSError:
            usable = False
        if not usable:
            missing.append(str(ref))

    if invalid:
        return [
            PreflightIssue(
                "car_lods",
                "car lods.ini has invalid LOD model entries: " + ", ".join(invalid[:4]),
            )
        ]
    if missing:
        return [
            PreflightIssue(
                "car_lod_file",
                "car content is damaged: lods.ini references missing/empty model file(s): "
                + ", ".join(missing[:4])
                + ". Restore or verify the car files before running the harness.",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Installed-app provenance (#575).
#
# The trainer app is installed as a junction:
#     <ac_root>/apps/lua/AC_Copilot_Trainer -> <some checkout>/src/ac_copilot_trainer
# The harness runs from its OWN checkout (often a worktree), so the two can silently disagree —
# the rig then executes an app version the harness never saw. Observed damage (EPIC #529 G1): the
# junction target sat ten days stale, lap archives were written with `car: "function_0xff"`, and
# the #543 friction fit could not promote because zero valid archives matched.
#
# The verdict is a CONTENT digest, not a commit compare: the two checkouts can share a HEAD and
# still differ (dirty tree), and a junction may point at a non-git export. Commits are carried
# alongside as human-readable provenance so the warning can name both versions.
# ---------------------------------------------------------------------------
APP_INSTALL_RELPATH = ("apps", "lua", "AC_Copilot_Trainer")
APP_SOURCE_RELPATH = ("src", "ac_copilot_trainer")

# Build noise that lives inside the source tree but is never app payload: the AC Lua runtime never
# reads it, and it differs between checkouts for reasons that are not a version drift. Observed on
# the rig: the primary checkout carries `src/ac_copilot_trainer/__pycache__/*.pyc` that a worktree
# does not — hashing it would report false drift on every run.
_APP_DIGEST_IGNORED_DIRS = frozenset({"__pycache__", ".git"})
_APP_DIGEST_IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})
_APP_DIGEST_IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db"})


def _app_digest_bytes(data: bytes) -> bytes:
    """Normalize a file's bytes for version comparison: CRLF -> LF in text, binary untouched.

    Two checkouts of the SAME commit can legitimately hold different line endings — `.gitattributes`
    (`*.bat text eol=crlf`) normalizes on checkout, and a tree cloned under different settings keeps
    the other ending. Observed on the rig: `start_sidecar.bat` differed between the primary checkout
    and a worktree at the identical commit, purely in EOLs. Hashing raw bytes would therefore report
    drift on every run here — and a check that always cries wolf trains the operator to ignore the
    one time it is real, which is the failure #575 exists to prevent.

    Binary detection mirrors git's: a NUL byte means binary (fonts, PNGs), hashed byte-exact.
    """
    if b"\x00" in data:
        return data
    return data.replace(b"\r\n", b"\n")


def harness_repo_root() -> Path:
    """Repo root of the checkout this harness module was imported from."""
    return Path(__file__).resolve().parents[2]


def _app_digest_includes(rel: Path) -> bool:
    """True when a tree-relative path is app payload (see the ignore sets above)."""
    if _APP_DIGEST_IGNORED_DIRS & set(rel.parts[:-1]):
        return False
    return rel.suffix.lower() not in _APP_DIGEST_IGNORED_SUFFIXES and (
        rel.name not in _APP_DIGEST_IGNORED_NAMES
    )


def app_tree_digest(root: Path) -> str | None:
    """Content digest of an app tree, or ``None`` when it cannot be read.

    Order-independent and path-sensitive: a rename with identical bytes is a real drift and must
    not hash equal. Text is compared EOL-insensitively (see :func:`_app_digest_bytes`). Follows the
    junction, so passing the install path digests the target.
    """
    if not root.is_dir():
        return None
    entries: list[tuple[str, bytes]] = []
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if not _app_digest_includes(rel):
                continue
            payload = _app_digest_bytes(path.read_bytes())
            entries.append((rel.as_posix(), hashlib.sha256(payload).digest()))
    except OSError:
        return None  # unreadable tree — provenance is unknown, never a crash (#575 AC2)
    digest = hashlib.sha256()
    for rel_posix, file_digest in sorted(entries):
        digest.update(rel_posix.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest)
    return digest.hexdigest()


def _git_head(path: Path) -> str | None:
    """``HEAD`` of the checkout containing ``path``; ``None`` when it is not one (or git is gone).

    ``git -C`` walks up to the repo root, so any path inside a checkout resolves it.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _short(commit: str | None, digest: str | None) -> str:
    """Human-readable version tag: the commit when the tree is a checkout, else the digest."""
    if commit:
        return commit[:12]
    if digest:
        return f"content:{digest[:12]}"
    return "unknown"


# Statuses that `--strict-app-version` treats as fatal. The split matters: an app that is ABSENT
# cannot run the wrong code, but an app that is PRESENT AND UNVERIFIABLE might already be the stale
# one — and a strictness flag that greens on "something is installed but I cannot tell what" would
# reintroduce the exact silent-false-confidence failure #575 exists to kill. Absence of proof is not
# proof of match, but absence of an app is not absence of proof.
APP_PROVENANCE_STRICT_FATAL = frozenset({"drift", "unverifiable"})


@dataclass(frozen=True)
class AppInstallProvenance:
    """Whether the AC-installed trainer app matches the harness's own checkout.

    ``status`` is one of:

    - ``match`` — installed content equals the harness's own app source.
    - ``drift`` — proven different. Warns; fatal under ``--strict-app-version``.
    - ``absent`` — no app installed. Nothing can run the wrong code, so this warns even under
      strict; a rig that does not run the Lua app is a legitimate configuration.
    - ``unverifiable`` — an app IS installed but its version cannot be established (unreadable
      tree, or a harness checkout with no app source to compare against). Warns by default; fatal
      under strict, because the installed app may already be the stale one.

    ``absent`` and ``unverifiable`` are the two halves of what a coarser design would call
    "unknown" — they are split because strictness must treat them oppositely (PR #587 review).
    """

    status: str
    detail: str
    installed_path: str | None = None
    installed_target: str | None = None
    installed_digest: str | None = None
    installed_commit: str | None = None
    harness_path: str | None = None
    harness_digest: str | None = None
    harness_commit: str | None = None

    @property
    def blocks_strict(self) -> bool:
        """True when ``--strict-app-version`` should fail the run on this verdict."""
        return self.status in APP_PROVENANCE_STRICT_FATAL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def app_install_provenance(ac_root: Path, harness_root: Path | None = None) -> AppInstallProvenance:
    """Compare the AC-installed trainer app against the harness's own ``src/ac_copilot_trainer``.

    Pure over the filesystem (plus a read-only ``git rev-parse``); safe to call from preflight.
    """
    root = harness_repo_root() if harness_root is None else harness_root
    harness_src = root.joinpath(*APP_SOURCE_RELPATH)
    installed = ac_root.joinpath(*APP_INSTALL_RELPATH)

    harness_digest = app_tree_digest(harness_src)
    harness_commit = _git_head(root) if harness_src.is_dir() else None
    common = {
        "installed_path": str(installed),
        "harness_path": str(harness_src),
        "harness_digest": harness_digest,
        "harness_commit": harness_commit,
    }

    if not installed.is_dir():
        # ABSENT, not unverifiable: no app is installed, so none can run the wrong code. Non-fatal
        # even under strict — a rig that does not run the Lua app is a legitimate configuration.
        return AppInstallProvenance(
            status="absent",
            detail=(
                f"trainer app is not installed at {installed} — no in-sim app will run. Install it "
                f"as a junction to this checkout's {harness_src} (mklink /J), or ignore if this "
                "rig does not run the Lua app."
            ),
            **common,
        )

    # A junction is not a symlink to Python (is_symlink() is False), so compare the real path.
    resolved = Path(os.path.realpath(installed))
    target = str(resolved) if resolved != Path(os.path.abspath(installed)) else None
    installed_digest = app_tree_digest(installed)
    installed_commit = _git_head(resolved)
    common.update(
        installed_target=target,
        installed_digest=installed_digest,
        installed_commit=installed_commit,
    )
    installed_where = target or str(installed)

    # Below here an app IS installed, so any failure to establish its version is UNVERIFIABLE, not
    # absent: the rig will run that app, and it may already be the stale one.
    if harness_digest is None:
        return AppInstallProvenance(
            status="unverifiable",
            detail=(
                f"an app is installed at {installed_where} but this harness checkout has no "
                f"readable app source at {harness_src} to compare it against — the rig's app "
                "version cannot be established."
            ),
            **common,
        )
    if installed_digest is None:
        return AppInstallProvenance(
            status="unverifiable",
            detail=(
                f"an app is installed at {installed} but its content is not readable — the rig's "
                "app version cannot be established."
            ),
            **common,
        )
    if installed_digest == harness_digest:
        return AppInstallProvenance(
            status="match",
            detail=(
                f"installed app matches this harness checkout "
                f"({_short(harness_commit, harness_digest)})"
            ),
            **common,
        )

    return AppInstallProvenance(
        status="drift",
        detail=(
            "INSTALLED TRAINER APP DIFFERS FROM THIS HARNESS CHECKOUT — the rig would run app "
            f"code the harness never saw. Installed: {installed_where} at "
            f"{_short(installed_commit, installed_digest)}. Harness: {harness_src} at "
            f"{_short(harness_commit, harness_digest)}. Point the junction at this checkout, or "
            "sync the installed checkout, before trusting this run's lap archives."
        ),
        **common,
    )


def app_version_preflight_fatal(
    provenance: AppInstallProvenance, *, strict: bool, preflight_only: bool
) -> bool:
    """Whether the PRE-rig-lock ``app_version`` row should abort the run.

    Only ``--preflight-only`` may abort here: it takes no rig lock, so the pre-lock verdict is the
    only measurement it will ever have, and a readiness probe that cannot fail is useless.

    A real drive must NOT abort pre-lock. A peer worktree holding the lock may fix or repoint the
    install before we acquire it, so a pre-lock drift can be stale by the time the drive would
    start — aborting on it is a false-fail, and it would also make the post-lock recheck
    unreachable. Real drives gate on :func:`app_provenance_recheck` instead (PR #587 review).
    """
    return bool(strict and preflight_only and provenance.blocks_strict)


def app_provenance_recheck(
    before: AppInstallProvenance,
    after: AppInstallProvenance,
    *,
    strict: bool,
) -> tuple[str | None, bool]:
    """Decide a post-rig-lock provenance re-measurement: ``(race_note, fatal)``.

    The installed app is shared rig state. A peer worktree can repoint the junction while we block
    on the machine-global lock, so the verdict that gates ``--strict-app-version`` and lands in the
    evidence bundle must be the one measured **under** the lock — otherwise a pre-lock ``match``
    bypasses strict on an app that has since drifted, and the bundle records a version the rig
    never ran (PR #587 review; same reasoning as the plant/line post-lock resolution).

    ``race_note`` is non-None when the verdict changed across the lock wait — worth surfacing on
    its own, since it is the #575 failure mode caught in the act.
    """
    note: str | None = None
    if after.status != before.status:
        note = (
            f"app provenance CHANGED while waiting for the rig lock: {before.status} -> "
            f"{after.status} (a peer worktree touched the install). {after.detail}"
        )
    return note, bool(strict and after.blocks_strict)


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


def _read_cm_preset_selection(path: str | Path) -> tuple[str | None, str | None]:
    """Return ``(car_id, track_id)`` from a readable Quick Drive preset.

    Parsing remains side-effect free so callers can use the effective selection for evidence
    metadata without mutating the explicit CLI configuration.  Read/JSON errors intentionally
    propagate: :func:`preflight` turns them into actionable rows, while early evidence naming
    can safely fall back to generic tags.
    """
    preset = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(preset, dict):
        raise TypeError("Quick Drive preset root must be a JSON object")
    car_id = str(preset.get("CarId") or "").strip() or None
    track_id = str(preset.get("TrackId") or "").strip() or None
    return car_id, track_id


def _effective_car_id(config: AutoDriveConfig) -> str | None:
    """Resolve the selected car for read-only evidence attribution."""
    if config.car_id:
        return config.car_id
    if config.cm_preset is None or not Path(config.cm_preset).is_file():
        return None
    try:
        preset_car, _preset_track = _read_cm_preset_selection(config.cm_preset)
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return preset_car


def preflight(
    config: AutoDriveConfig, *, app_provenance: AppInstallProvenance | None = None
) -> list[PreflightIssue]:
    """Assert every launch precondition with an actionable message (no error rows = go).

    Covers the tribal-lore failure modes that used to surface as mid-run mysteries: missing
    content, a preset whose CarId/TrackId disagree with the CLI, CSP Custom AI disabled (the
    hijack silently no-ops), a missing Content Manager, an unresolvable setup, and an installed
    trainer app that disagrees with this checkout (#575).

    ``app_provenance`` is injectable so the CLI can compute it once and also record it in the
    evidence bundle; it is resolved from ``config.ac_root`` when omitted.
    """
    issues: list[PreflightIssue] = []
    user_dir = resolve_ac_user_dir(config.ac_user_dir)
    selected_car_id = _effective_car_id(config)

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
            preset_car, preset_track = _read_cm_preset_selection(config.cm_preset)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            issues.append(
                PreflightIssue("preset", f"unreadable Quick Drive preset {config.cm_preset}: {exc}")
            )
        else:
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

    # Validate the actual selected car whether it came from --car or a hand-authored preset.
    # Preset-only runs are a supported launch path; letting them bypass content validation would
    # preserve the same full-timeout failure under a different CLI spelling (#603).
    if selected_car_id:
        try:
            validate_ac_id("car", selected_car_id)
        except ValueError as exc:
            issues.append(PreflightIssue("car", str(exc)))
        else:
            car_dir = config.ac_root / "content" / "cars" / selected_car_id
            if not car_dir.is_dir():
                issues.append(
                    PreflightIssue("car", f"car content not installed: {car_dir} (check car id)")
                )
            else:
                issues.extend(car_content_preflight(car_dir))
    elif config.cm_preset is not None and Path(config.cm_preset).is_file():
        issues.append(
            PreflightIssue("car", "Quick Drive preset has no CarId and --car was not provided")
        )

    provenance = (
        app_install_provenance(config.ac_root) if app_provenance is None else app_provenance
    )
    if provenance.status != "match":
        # Warning, not an error: a drifted app still drives, and an unknown-provenance install
        # (non-junction export, app not installed) must never brick the rig. --strict-app-version
        # promotes this to fatal for runs whose evidence depends on the app version (#575).
        issues.append(PreflightIssue("app_version", provenance.detail, severity="warning"))

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
    min_count: int = 1,
    min_valid_count: int | None = None,
    min_matching_count: int | None = None,
    valid_archive_predicate: Callable[[dict], bool] | None = None,
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

    With ``wait_for_first`` (set when the run produced a lap) this polls up to ``timeout_s`` for
    ``min_count`` archives and, when supplied, ``min_valid_count`` valid archives instead of racing
    the writer. The latter is essential in hotlap mode: invalid boundaries still produce archive
    files but do not advance AC's completed-lap counter.
    It returns immediately with no wait when ``wait_for_first`` is false (a run that produced no
    lap).

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

    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 1:
        raise ValueError("min_count must be a positive integer")
    if min_valid_count is not None and (
        isinstance(min_valid_count, bool)
        or not isinstance(min_valid_count, int)
        or min_valid_count < 1
    ):
        raise ValueError("min_valid_count must be a positive integer or None")
    if min_matching_count is not None and (
        isinstance(min_matching_count, bool)
        or not isinstance(min_matching_count, int)
        or min_matching_count < 1
    ):
        raise ValueError("min_matching_count must be a positive integer or None")

    def _enough(paths: list[str]) -> bool:
        # ``min_matching_count`` gates on the predicate ALONE (validity-agnostic): a #577
        # flying-lap batch must wait for THIS combo's archives — the multi-dir resolver can see
        # another app/combo's fresh files — but must not gate on validity (an AC-invalid lap's
        # archive is falsification evidence that never turns valid; #579 Qodo + Codex).
        return (
            len(paths) >= min_count
            and (
                min_valid_count is None
                or _count_valid_lap_archives(paths, valid_archive_predicate) >= min_valid_count
            )
            and (
                min_matching_count is None
                or _count_matching_lap_archives(paths, valid_archive_predicate)
                >= min_matching_count
            )
        )

    found = _scan_lap_archives(_current(), since_epoch)
    if _enough(found) or not wait_for_first:
        return found
    deadline = _clock() + max(0.0, timeout_s)
    while _clock() < deadline:
        _sleep(max(0.0, poll_s))
        found = _scan_lap_archives(_current(), since_epoch)
        if _enough(found):
            return found
    return found


def _count_valid_lap_archives(
    paths: list[str], predicate: Callable[[dict], bool] | None = None
) -> int:
    """Count finalized archive files whose canonical lap validity is explicitly true."""
    count = 0
    for item in paths:
        try:
            payload = json.loads(Path(item).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        lap = payload.get("lap") if isinstance(payload, dict) else None
        if (
            isinstance(lap, dict)
            and lap.get("is_valid") is True
            and (predicate is None or predicate(payload))
        ):
            count += 1
    return count


def _count_matching_lap_archives(
    paths: list[str], predicate: Callable[[dict], bool] | None = None
) -> int:
    """Count finalized archive files matching ``predicate``, regardless of lap validity.

    The #577 flying-lap batch gate: an AC-INVALID lap's archive still counts (it is the
    falsification evidence the self-play verdict needs), but a foreign app/combo's archive
    must not satisfy the batch (#579 Codex).
    """
    count = 0
    for item in paths:
        try:
            payload = json.loads(Path(item).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, dict) and (predicate is None or predicate(payload)):
            count += 1
    return count


def archive_matches_combo(payload: dict, *, car_id: str, track_id: str, layout: str | None) -> bool:
    """Return whether a current-run archive can belong to the requested combo."""
    car = payload.get("car") if isinstance(payload.get("car"), dict) else {}
    track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
    if str(car.get("id") or "") != car_id or str(track.get("id") or "") != track_id:
        return False
    actual_layout = track.get("layout") or None
    # The current Lua schema can omit layout; current-run scoping proves the requested launch.
    return actual_layout is None or actual_layout == layout


# ---------------------------------------------------------------------------
# Rig wiring (Windows/AC only; not exercised by CI — validated on the rig).
# ---------------------------------------------------------------------------
def _log(msg: str) -> None:  # pragma: no cover - rig-only progress trace
    """Print a timestamped harness progress line so per-cycle launch/hijack timing is visible.

    #466 acceptance requires proving a stalled cycle is *recycled within a few seconds* rather than
    burning a full-timeout dead-wait; these lines (with their wall-clock stamps) are that proof.
    """
    print(f"[auto-drive {time.strftime('%H:%M:%S')}] {msg}", flush=True)


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
    from tools.ac_harness.cm_dialog_watcher import CmSkipWatcher
    from tools.ac_harness.entry_launcher import ContentManagerActuator

    actuator = ContentManagerActuator(preset=config.cm_preset, cm_exe=config.cm_exe)
    actuator.normalize_prior_state()
    # #738: while attempts wait for LIVE, auto-skip CM's "Custom Shaders Patch data" dialog —
    # a hanging online fetch otherwise blocks acs.exe from ever spawning and every relaunch
    # re-opens the same dialog. One watcher spans all attempts; its evidence rides the
    # returned launch message either way the run ends.
    watcher: CmSkipWatcher | None = None
    if config.cm_dialog_skip:
        watcher = CmSkipWatcher(log=_log)
        watcher.start()

    def _with_skip_evidence(message: str) -> str:
        summary = watcher.summary() if watcher is not None else None
        return f"{message}; {summary}" if summary else message

    try:
        for attempt in range(1, config.max_launches + 1):
            _log(
                "launching AC via Content Manager"
                + (" (setup baked into race.ini)" if config.setup_ini is not None else "")
            )
            minimize_foreground_window()  # the CM auto-start race needs the foreground free
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
                            _with_skip_evidence(
                                f"LIVE with setup after {attempt} launch attempt(s) — race.ini "
                                f"ready {bake.ready}x during CM launch ({bake.writes} rewrite(s))"
                            ),
                        )
                    detail = f"; last error: {bake.last_error}" if bake.last_error else ""
                    return (
                        True,
                        _with_skip_evidence(
                            "LIVE with setup verification deferred after "
                            f"{attempt} launch attempt(s) — race.ini readiness was not observed "
                            f"at {race_ini}{detail}"
                        ),
                    )
                continue
            actuator.launch() if attempt == 1 else actuator.relaunch()
            if _wait_live(config.attempt_timeout):
                time.sleep(config.settle_seconds)  # let CSP arm Custom-AI before the hijack
                return True, _with_skip_evidence(f"LIVE after {attempt} launch attempt(s)")
        return False, _with_skip_evidence(
            f"sim never reached LIVE after {config.max_launches} attempt(s)"
        )
    finally:
        if watcher is not None:
            watcher.stop()


def rig_restart_launcher(config: AutoDriveConfig) -> None:  # pragma: no cover - rig-only
    """Restart Content Manager so the next :func:`rig_launch` cold-starts a FRESH CM (#558).

    Invoked by :func:`run_auto_drive` on a cached-session mismatch: a stale CM keeps serving its
    cached last session no matter how often the ``acmanager://`` URL is re-sent, so the harness
    must kill CM and let the next launch cold-start a fresh instance that honors the preset.
    """
    from tools.ac_harness.entry_launcher import ContentManagerActuator

    actuator = ContentManagerActuator(preset=config.cm_preset, cm_exe=config.cm_exe)
    event = actuator.restart_content_manager()
    _log(f"restart Content Manager (cached-session recovery): {event.detail}")


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


async def rig_press_session_start(
    config: AutoDriveConfig, *, instant: bool = True, ack_timeout_s: float = 10.0
) -> dict | None:  # pragma: no cover - rig-only
    """Ask the in-sim Lua app to press AC's Start button (CSP ``ac.tryToStart``) — #627/#466.

    Joins the sidecar as an ordinary external peer and sends one ``session.start``; the sidecar
    relays it to the loopback Lua peer, whose handler calls ``ac.tryToStart`` and answers
    ``session.start.ack``. Returns the ack or correlated sidecar error frame, or ``None`` when
    neither arrived within ``ack_timeout_s`` (sidecar down or an older app without the handler).

    Deliberately tolerant: the caller treats every failure as "probe anyway", because the Car0
    handshake remains the authoritative drivability oracle. A press that silently did nothing must
    never read as a drivable session — that is exactly the false green #627 was full of.
    """
    from tools.ai_sidecar.external_protocol import SESSION_START_CLIENT_ID
    from tools.ai_sidecar.harness_client import HarnessClient

    token = os.environ.get("AC_COPILOT_SIDECAR_TOKEN") or None
    async with HarnessClient(
        config.sidecar_url, token=token, client_id=SESSION_START_CLIENT_ID
    ) as hc:
        await hc.hello()
        return await hc.request_session_start(instant=instant, timeout=ack_timeout_s)


def rig_hijack(
    config: AutoDriveConfig,
    *,
    retain_telemetry_controller: Callable[[Controller], None] | None = None,
) -> Controller | None:  # pragma: no cover - rig-only
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
        try:
            _close_controller(
                ctrl,
                context=f"hijack probe {attempt}/{attempts} cleanup",
                cleanup_failure=rig_force_safe_after_cleanup_failure,
            )  # recreate the section next attempt to re-trigger the hijack
        except ControllerTelemetryCleanupPending as exc:
            if retain_telemetry_controller is None:
                raise
            retain_telemetry_controller(exc.controller)
            _log(
                f"hijack probe {attempt}/{attempts}: retained a read-only telemetry mapping; "
                "continuing with a fresh CarControls section"
            )
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

        # #532 Part B: drive the combo's identified friction plant (safe-envelope-blended GGVModel)
        # when the CLI resolved one from the artifact; otherwise the generic GT3 plant.
        plant = config.plant_ggv if config.plant_ggv is not None else generic_gt3_ggv()
        v_target, _summ = ggv_speed_profile_from_model(
            fast_line, plant, v_top_kmh=config.racing_max_speed_kmh
        )
        v_target = [v * config.ggv_scale for v in v_target]
        # #532: consume the combo's machine-measured plant constants when the CLI resolved an
        # artifact (shift points always; measured curvature-FF steering with --use-plant full).
        return RacingDriver.from_ggv_profile(fast_line, v_target, **(config.plant_kwargs or {}))
    if config.driver == "alien":
        from tools.ac_harness.racing_driver import RacingDriver

        # #572: drive the combo's optimized line + identified-plant QSS profile. Both come from
        # the alien-line artifact the CLI resolved (built/cached with identity + provenance
        # gates); missing state here is a wiring bug, not a degrade point — fail loud.
        if not config.alien_line or not config.alien_v_target:
            raise ValueError(
                "alien driver requires the optimized line + v_target from the alien-line "
                "artifact (CLI resolution missing)"
            )
        if not config.plant_kwargs:
            raise ValueError(
                "alien driver requires the combo's measured plant constants "
                "(ff_sign/ff_c1/ff_c2 + shift points) — run --driver handshake first"
            )
        # The stored v_target is envelope-verified at build time; scaling above 1 would push
        # corner speeds past the verified plant envelope AFTER that check (#572 Codex review).
        # #577: config.alien_overspeed opts in to a bounded supra-envelope probe (self-play only;
        # every step falsifiable via the auto_alien keep-last-valid oracle).
        scale_cap = ALIEN_MAX_OVERSPEED_SCALE if config.alien_overspeed else 1.0
        if not 0.0 < config.ggv_scale <= scale_cap:
            raise ValueError(
                f"alien driver requires 0 < ggv_scale <= {scale_cap} (got {config.ggv_scale}); "
                "the scale is a safety margin under the envelope-verified profile"
            )
        v_target = [v * config.ggv_scale for v in config.alien_v_target]
        return RacingDriver.from_ggv_profile(config.alien_line, v_target, **config.plant_kwargs)
    if config.driver == "handshake":
        from tools.ac_harness.plant_id import HandshakeController

        if speed_profile is None:
            raise ValueError(
                "handshake driver requires a speed_profile from the track's fast_lane.ai"
            )
        return HandshakeController(
            fast_line,
            speed_profile,
            car_id=config.car_id or "",
            track_id=config.track_id,
            layout=config.track_layout,
            setup=(Path(config.setup).stem if config.setup else None),
            setup_ini=(str(config.setup_ini) if config.setup_ini else None),
            # Fresh sink owned by the controller; rig_drive copies it into DriveStats.payload so
            # the result returns normally (no config side-channel — daemon review).
            sink={},
            # The controller does NOT open OS memory itself (daemon review): rig_drive injects a
            # harness-owned physics reader via set_phys_read and owns its close.
            phys_read=None,
            # Moderate cornering pace (fixed, not the flat-out ggv pace) so more corners exceed the
            # steer-FF lateral-g floor (0.3 g) -> the fit reaches its 80-row budget within a lap,
            # while staying conservative enough to drive clean. Live-found on Spa (#532): at pace
            # 0.65 only ~4 rows/3 km qualified; 0.8 loads the corners ~50% more (v^2).
            pace=0.8,
            # #532 Part B: the trusted generic plant the measured friction envelope is
            # safe-envelope-blended against (enables the ggv artifact block + the brake-at-speed
            # probe). The harness owns the prior so the controller stays import-clean of auto_drive.
            prior_ggv=generic_gt3_ggv(),
            prior_ggv_name="generic_gt3_ggv",
        )
    raise ValueError(
        f"unknown driver {config.driver!r} "
        "(expected 'ggv', 'racing', 'cruise', 'handshake', or 'alien')"
    )


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


class SimProcessIdentityMonitor:
    """Track the one ``acs.exe`` process that owns a hijacked drive session (#555).

    An empty first observation is tolerated (``tasklist`` can race process startup); the first
    singleton observation becomes the expected process. Multiple processes are immediately unsafe,
    and any later PID outside the expected singleton is a session takeover.
    """

    def __init__(self, initial_pids: frozenset[int] | set[int] = frozenset()) -> None:
        self.expected_pid: int | None = None
        self._initial_conflict: tuple[int, ...] = ()
        self.observe(initial_pids)

    def observe(self, current_pids: frozenset[int] | set[int]) -> tuple[int, ...]:
        """Return unexpected PIDs, or ``()`` while the original session still owns the rig."""

        current = {int(pid) for pid in current_pids if int(pid) > 0}
        if self.expected_pid is None:
            if self._initial_conflict:
                # Ownership stays unsafe after an ambiguous start, but diagnostics should name the
                # PIDs that are live now rather than replaying a stale historical set forever.
                return tuple(sorted(current)) or self._initial_conflict
            if len(current) == 1:
                self.expected_pid = next(iter(current))
                return ()
            if len(current) > 1:
                self._initial_conflict = tuple(sorted(current))
                return self._initial_conflict
            return self._initial_conflict
        return tuple(sorted(current - {self.expected_pid}))


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
    # #572 alien: spawn/teleport/recovery target the OPTIMIZED geometry the controller tracks,
    # not the stock centre line — a recovery teleport onto the stock line would drop the car up
    # to the full corridor width off its own racing line.
    if config.driver == "alien" and config.alien_line:
        line = config.alien_line
    speed_profile = None
    if config.driver in ("racing", "handshake"):
        from tools.ac_harness.racing_driver import load_speed_profile

        speed_profile = load_speed_profile(fast_path)
    driver = _build_driver(config, line, speed_profile)
    stats = DriveStats()
    watchdog = ProgressWatchdog(stall_seconds=config.progress_stall_seconds)
    last_control_trace_s = -math.inf
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

    def _record_control_trace(
        now: float,
        cd: dict[str, Any],
        frame: Any,
        *,
        event: str = "control",
        force: bool = False,
    ) -> None:
        """Append one bounded state+command sample; recovery events bypass the 2 Hz throttle."""

        nonlocal last_control_trace_s
        if not force and now - last_control_trace_s < CONTROL_TRACE_INTERVAL_S:
            return
        if len(stats.control_trace) >= CONTROL_TRACE_MAX_SAMPLES:
            # Keep the failure-adjacent tail for very long runs.  The truncation bit prevents a
            # consumer from mistaking the retained window for a complete drive trace.
            stats.control_trace.pop(0)
            stats.control_trace_truncated = True
        position = cd.get("position")
        stats.control_trace.append(
            {
                "t_s": round(float(now), 3),
                "distance_m": round(float(stats.total_distance_m), 3),
                "position": (
                    [round(float(value), 4) for value in position]
                    if isinstance(position, (list, tuple)) and len(position) == 3
                    else None
                ),
                "speed_kmh": round(float(cd.get("speed_kmh", 0.0)), 3),
                "rpm": round(float(cd.get("rpm", 0.0)), 1),
                "gear": int(cd.get("gear", 0)),
                "gas": round(float(frame.gas), 4),
                "brake": round(float(frame.brake), 4),
                "steer": round(float(frame.steer), 4),
                "phase": str(frame.phase),
                "event": event,
            }
        )
        last_control_trace_s = now

    def _recover(now: float) -> tuple[bool, str]:
        """Shared recovery for driver/watchdog stalls; return ``(within_cap, action)``."""
        nonlocal line_teleport_works, off_line
        stats.recoveries += 1
        if stats.recoveries > config.max_recoveries:
            stats.recovery_capped = True
            stats.reason = (
                f"recovery cap ({config.max_recoveries}) exceeded at {stats.total_distance_m:.0f}m"
            )
            return False, "cap_exceeded"
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
        return True, "line_teleport" if recovered_to_line else "teleport_to_pits"

    # Sim-death keys on the MAIN acpmf_physics packet_id, NOT the Car0 (Custom-AI) one: live-found
    # (Spa 2026-07-02) that CSP does NOT bump Car0.packet_id every frame — it stays constant while a
    # car is stationary — so watching Car0 falsely declared "acs.exe died" 4 s into a start-line
    # spawn, before the driver could even shift out of neutral. The main physics packet advances
    # every frame while the sim runs and freezes only when acs actually dies (#459 review).
    from tools.ac_harness.entry_launcher import running_process_ids
    from tools.ac_harness.shared_memory import SharedMemoryReader, SharedMemoryUnavailable

    phys_reader: SharedMemoryReader | None = None
    try:
        phys_reader = SharedMemoryReader()
    except SharedMemoryUnavailable:
        phys_reader = None

    # #532: the handshake needs per-wheel angular speed (r_eff probe) from acpmf_physics. Reuse the
    # SAME harness-owned physics map (phys_reader) rather than opening a second identical view — the
    # controller never touches OS memory itself, and there is no redundant map (daemon review).
    if hasattr(driver, "set_phys_read"):
        from tools.ac_harness.racing_telemetry import parse_physics as _parse_phys
        from tools.ac_harness.shared_memory import PHYSICS_MAP_BYTES

        def _read_hs_phys():
            reader = phys_reader  # late-bound: follows _main_packet_id's reopen/close
            if reader is None:
                return None
            try:
                buf = reader.read_physics_bytes(PHYSICS_MAP_BYTES)
                if buf is None:
                    return None
                physics = _parse_phys(buf)
            except (ValueError, SharedMemoryUnavailable):
                return None
            try:
                graphics = reader.read_graphics()
                completed_laps = graphics.completed_laps
            except (ValueError, SharedMemoryUnavailable):
                # Graphics is optional provenance/completion state. Never discard a valid physics
                # frame (including wheel speed and accG probes) because this secondary map failed.
                completed_laps = None
            return replace(physics, completed_laps=completed_laps)

        driver.set_phys_read(_read_hs_phys)

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

    # Capture the process that owns the already-hijacked session. CM requests are machine-global;
    # without this identity, a concurrent worktree that starts another Quick Drive session only
    # surfaces later as frozen physics and the report misleadingly says generic ``sim_dead``.
    process_monitor = SimProcessIdentityMonitor(running_process_ids("acs.exe"))
    stats.sim_pid = process_monitor.expected_pid
    process_probe_stop = threading.Event()
    process_probe_lock = threading.Lock()
    process_takeover: tuple[int, ...] = ()

    def _sample_sim_process() -> tuple[int, ...]:
        """Synchronously sample ownership and latch any unsafe process identity."""

        nonlocal process_takeover
        current = running_process_ids("acs.exe")
        with process_probe_lock:
            unexpected = process_monitor.observe(current)
            if unexpected:
                process_takeover = unexpected
            return process_takeover

    def _record_process_takeover(*, synchronous: bool) -> bool:
        """Copy a latched/fresh takeover into the structured drive verdict."""

        if synchronous:
            unexpected = _sample_sim_process()
        else:
            with process_probe_lock:
                unexpected = process_takeover
        if not unexpected:
            return False
        stats.sim_pid = process_monitor.expected_pid
        stats.session_replaced = True
        stats.unexpected_sim_pids = list(unexpected)
        stats.reason = (
            "unexpected acs.exe PID takeover during live drive "
            f"(expected_sim_pid={stats.sim_pid}, observed={list(unexpected)})"
        )
        return True

    def _watch_sim_process() -> None:
        # Process enumeration takes ~20 ms on a busy rig. Keep it off the real-time control loop;
        # one-second attribution latency is tiny beside the 4 s sim-death threshold.
        while not process_probe_stop.is_set():
            if _sample_sim_process():
                return
            process_probe_stop.wait(1.0)

    process_probe_thread = threading.Thread(
        target=_watch_sim_process, name="acs-process-identity", daemon=True
    )
    process_probe_thread.start()
    prev_plane: tuple[float, float] | None = None
    t0 = time.monotonic()
    # Anchor the sim-death timer at the loop start (not the first packet sample) so a sim that is
    # already dead trips once stale car data appears, even on a short/ending run (codex on #513).
    stall = PhysicsStallDetector(config.sim_dead_seconds, now=t0)
    try:
        while time.monotonic() - t0 < config.drive_seconds:
            # The sidecar tap can stop the drive between one-second watcher polls. Refresh ownership
            # synchronously before accepting that stop as clean (#555 review).
            if stop.is_set():
                _record_process_takeover(synchronous=True)
                break
            if _record_process_takeover(synchronous=False):
                break
            cd = controller.read_car_data()
            if not cd:
                # A replacement can tear down Car0 before the background watcher runs. Sample now,
                # before missing telemetry continues past the only attribution opportunity.
                if _record_process_takeover(synchronous=True):
                    break
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
            if getattr(driver, "finished", False):
                # A self-terminating driver (the #532 handshake) reports completion; stop the
                # loop instead of burning the remaining drive budget (teardown brakes the car).
                stats.reason = stats.reason or "driver finished"
                break
            stalled = watchdog.update(stats.total_distance_m, now)
            if frame.needs_recovery or stalled:
                trigger = "driver_stuck" if frame.needs_recovery else "progress_watchdog"
                recovered, action = _recover(now)
                _record_control_trace(
                    now,
                    cd,
                    frame,
                    event=f"recovery:{trigger}:{action}",
                    force=True,
                )
                if not recovered:
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
            _record_control_trace(now, cd, frame)
            time.sleep(0.012)
    finally:
        # Close the final sub-second race at timeout/driver completion too; rig teardown has not
        # begun yet, so a different PID here is always a session replacement rather than expected.
        _record_process_takeover(synchronous=True)
        process_probe_stop.set()
        process_probe_thread.join(timeout=3.0)
        stats.sim_pid = process_monitor.expected_pid
        # #532: if the handshake driver did not self-complete within the drive budget, finalize it
        # so the run still produces a result (which constants WERE measured), not "no result".
        finalize = getattr(driver, "finalize", None)
        if finalize is not None and not getattr(driver, "finished", True):
            try:
                finalize(time.monotonic() - t0)
            except Exception as exc:  # noqa: BLE001 - must not mask the drive outcome, but be LOUD
                # Do not re-raise (that would mask the drive result), but the failure MUST be
                # observable: log the traceback AND annotate the outcome so a crashed finalize
                # never silently becomes an opaque "handshake produced no result" (Qodo review).
                logging.getLogger(__name__).exception("handshake finalize() crashed")
                stats.reason = (stats.reason + "; " if stats.reason else "") + (
                    f"handshake finalize crashed: {type(exc).__name__}: {exc}"
                )
        # Route the handshake result OUT via DriveStats.payload (normal return value), so _main
        # never reaches into a config-embedded mutable sink (daemon review).
        driver_sink = getattr(driver, "sink", None)
        if isinstance(driver_sink, dict) and driver_sink:
            stats.payload = dict(driver_sink)
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


def _nonneg_int(value: str) -> int:
    """argparse type: a non-negative integer (``0`` disables a bounded retry feature)."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be an integer >= 0, got {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be an integer >= 0, got {value!r}")
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
        choices=("ggv", "racing", "cruise", "handshake", "alien"),
        default="racing",
        help="ggv = flat-out min-time (top gears, 200+); racing = AI-line pace (default); "
        "cruise = slow 1st-gear lane-keeper; handshake = #532 plant-ID probes (measures "
        "ff_sign/steer-FF/shift points/r_eff in <=2 laps, persists a per-combo plant artifact); "
        "alien = #572 optimized min-curvature line + identified-plant QSS profile (requires the "
        "combo's plant artifact incl. uncertainty-aware friction fit; builds/caches the line "
        "artifact under Documents/Assetto Corsa/alien_line/)",
    )
    p.add_argument(
        "--alien-rebuild-line",
        action="store_true",
        help="alien: ignore the cached line artifact and rebuild it from the current plant",
    )
    p.add_argument(
        "--l3",
        action="store_true",
        help="alien: #582 beyond-QSS per-corner refinement — relax measured, low-variance grip "
        "bins from the 1.96-z safe LCB toward the posterior mean (stability floor z=1.0), "
        "re-solve each corner's interior between QSS-pinned entry/exit speeds, revert to "
        "safe-QSS per corner when evidence is thin (named in the artifact's l3 report). Off = "
        "byte-identical pre-#582 QSS artifact",
    )
    p.add_argument(
        "--use-plant",
        choices=("off", "auto", "full"),
        default="auto",
        help="consume the combo's identified plant artifact on the ggv path: auto = measured "
        "shift points when an artifact exists (default); full = also the measured "
        "curvature-feedforward steering (ff_sign/ff_c1/ff_c2); off = generic plant only",
    )
    p.add_argument("--pace", type=float, default=0.9, help="racing: fraction of AI-line speed")
    p.add_argument("--ggv-scale", type=float, default=0.9, help="ggv: safety margin on min-time")
    p.add_argument("--max-speed", type=float, default=240.0, help="racing/ggv: speed cap (km/h)")
    p.add_argument(
        "--drive-seconds",
        type=_positive_float,
        default=None,
        help="drive time budget (default: 300, or 180+240*laps for a flying-lap window)",
    )
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
    p.add_argument(
        "--laps",
        type=int,
        default=0,
        help="#577 flying-lap window: keep driving until this many TIMED laps complete (or "
        "--drive-seconds expires, whichever first); implies --wait-lap; per-lap times land in "
        "the report. 0 = legacy single-lap --wait-lap semantics",
    )
    p.add_argument(
        "--alien-allow-overspeed",
        action="store_true",
        help="EXPERT opt-in (#577): permit --ggv-scale in (1, 1.2] on the alien path — drives "
        "ABOVE the uncertainty-safe envelope. The keep-last-valid falsification protection "
        "exists only under auto_alien --iterations (which passes this per ladder step); a "
        "direct overspeed drive carries spin/damage risk on the operator",
    )
    p.add_argument("--strict", action="store_true", help="require session+lap, enforce ordering")
    p.add_argument(
        "--strict-app-version",
        action="store_true",
        help="fail preflight when the AC-installed trainer app is not proven to match this "
        "checkout — drift, or installed-but-unverifiable (default: warn). An absent app still "
        "only warns. Use for runs whose evidence depends on the rig running THIS app (#575)",
    )
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
        "--sim-death-retries",
        type=_nonneg_int,
        default=AutoDriveConfig.sim_death_retries,
        help="fresh full-launch retries after acs.exe death (default: 1; 0 disables)",
    )
    p.add_argument(
        "--setup-verify-retries",
        type=_nonneg_int,
        default=AutoDriveConfig.setup_verify_retries,
        help="fresh full-launch retries after a setup fuel-verify miss on the correct combo "
        "(the #466 race.ini re-bake race; default: 1; 0 disables)",
    )
    p.add_argument(
        "--no-spawn-line",
        action="store_true",
        help="do not teleport a pit-box spawn onto the racing line (use the OUT-phase pit exit)",
    )
    p.add_argument(
        "--no-cm-dialog-skip",
        action="store_true",
        help="do not auto-skip CM's pre-drive 'Custom Shaders Patch data' dialog (#738)",
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
        "--rig-lock-timeout",
        type=_nonneg_float,
        default=0.0,
        help="seconds to wait for another auto-drive process to release the single-rig lock; "
        "0 fails immediately and reports the owner (#555)",
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
        drive_seconds=resolve_lap_window_drive_seconds(args.drive_seconds, args.laps),
        lap_finalize_grace_s=args.lap_finalize_grace_s,
        target_speed_kmh=args.target_speed,
        min_corner_speed_kmh=args.min_corner,
        tap_seconds=args.tap_seconds,
        # --laps implies the lap-wait machinery: a multi-lap window without wait_lap would tap a
        # fixed 30 s and never see lap 2 (#577).
        wait_lap=args.wait_lap or args.laps > 0,
        target_laps=max(0, args.laps),
        alien_overspeed=args.alien_allow_overspeed,
        alien_l3=args.l3,
        strict=args.strict,
        skip_launch=args.skip_launch,
        cm_dialog_skip=not args.no_cm_dialog_skip,
        hijack_probe_seconds=args.hijack_probe_seconds,
        max_recoveries=args.max_recoveries,
        progress_stall_seconds=args.progress_stall_seconds,
        sim_death_retries=args.sim_death_retries,
        setup_verify_retries=args.setup_verify_retries,
        spawn_to_line=not args.no_spawn_line,
    )
    if args.ac_root is not None:
        kwargs["ac_root"] = args.ac_root
    return AutoDriveConfig(**kwargs)


def resolve_lap_window_drive_seconds(explicit: float | None, target_laps: int) -> float:
    """Return the stage-owned drive budget for a direct or composed flying-lap run.

    An explicit budget remains authoritative. Otherwise the legacy path keeps 300 seconds and
    ``--laps N`` gets enough headroom for a standing start plus N Spa-length laps. Keeping this
    rule in ``auto_drive`` ensures direct CLI users and orchestrators share one contract.
    """
    if explicit is not None:
        value = float(explicit)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"drive seconds must be finite and > 0 (got {explicit!r})")
        return value
    if target_laps > 0:
        return 180.0 + 240.0 * target_laps
    return 300.0


def _alien_prerequisites_error(config: AutoDriveConfig, user_dir: Path) -> str | None:
    """Read-only alien readiness check for ``--preflight-only``; message or ``None`` when ready.

    Validates what the post-lock resolution will require — a plant artifact passing the shared
    readiness gate (:func:`~tools.ac_harness.plant_id.plant_ready_for_full_consumption`), a
    resolvable ``fast_lane.ai``, and a sane parsed corridor — WITHOUT building or persisting the
    line cache (preflight must never write state).
    """
    from tools.ac_harness.alien_line import validate_corridor
    from tools.ac_harness.ggv_profile import load_track_widths
    from tools.ac_harness.plant_id import (
        load_plant_artifact,
        plant_artifact_path,
        plant_ready_for_full_consumption,
    )

    setup_key = Path(config.setup).stem if config.setup else None
    artifact = load_plant_artifact(
        user_dir,
        config.car_id,
        config.track_id,
        setup_key,
        config.setup_ini,
        layout=config.track_layout,
    )
    reason = plant_ready_for_full_consumption(artifact, require_friction_fit=True)
    if reason is not None:
        if artifact is None:
            expected = plant_artifact_path(
                user_dir,
                config.car_id,
                config.track_id,
                setup_key,
                config.setup_ini,
                layout=config.track_layout,
            )
            reason = f"{reason} ({expected}); run --driver handshake first"
        return reason
    try:
        from tools.ac_harness.ai_line import load_ai_line

        fast_path = resolve_fast_lane(config.ac_root, config.track_id, config.track_layout)
        line = load_ai_line(fast_path)
        side_left, side_right = load_track_widths(fast_path)
        validate_corridor(side_left, side_right, len(line), source=str(fast_path))
    except (FileNotFoundError, ValueError) as exc:
        return str(exc)
    return None


def _resolve_alien_assets(
    config: AutoDriveConfig, user_dir: Path, *, rebuild: bool
) -> tuple[str | None, str | None, dict | None]:
    """Resolve the alien drive's plant + optimized-line artifacts from current on-disk state.

    Returns ``(error, plant_artifact_used, alien_line_used)`` — ``error`` is a printable message
    (caller exits 2) or ``None`` on success, in which case ``config.plant_kwargs`` /
    ``config.plant_ggv`` / ``config.alien_line`` / ``config.alien_v_target`` are populated.

    MUST be called **after the machine-global rig lock is held** (#572 Codex review): a peer
    worktree waiting on the lock may re-identify the same combo; resolving before the lock could
    drive an in-memory plant/line that a newer on-disk plant artifact has already superseded,
    bypassing the cache/provenance gates.
    """
    from tools.ac_harness.alien_line import alien_line_path, ensure_alien_line_artifact
    from tools.ac_harness.corner_refine import L3Params
    from tools.ac_harness.plant_id import (
        load_plant_artifact,
        plant_artifact_path,
        plant_driver_kwargs,
        plant_ggv_model,
        plant_ready_for_full_consumption,
    )

    setup_key = Path(config.setup).stem if config.setup else None
    artifact = load_plant_artifact(
        user_dir,
        config.car_id,
        config.track_id,
        setup_key,
        config.setup_ini,
        layout=config.track_layout,
    )
    # Alien implies the full measured plant: the #543 uncertainty-aware friction fit + the
    # measured curvature-FF steering and shift points. One shared readiness gate — the same one
    # auto_alien.needs_identification and the alien preflight consult (#572 daemon review).
    reason = plant_ready_for_full_consumption(artifact, require_friction_fit=True)
    if reason is not None:
        if artifact is None:
            expected = plant_artifact_path(
                user_dir,
                config.car_id,
                config.track_id,
                setup_key,
                config.setup_ini,
                layout=config.track_layout,
            )
            reason = (
                f"--driver alien requires this combo's plant artifact ({expected}); "
                "run --driver handshake first (or python -m tools.ac_harness.auto_alien for "
                "the one-button pipeline)"
            )
        return (reason, None, None)
    config.plant_kwargs = plant_driver_kwargs(artifact, steer=True)
    plant = plant_ggv_model(artifact)
    config.plant_ggv = plant
    plant_artifact_used = str(
        plant_artifact_path(
            user_dir,
            config.car_id,
            config.track_id,
            setup_key,
            config.setup_ini,
            layout=config.track_layout,
        )
    )
    try:
        fast_path = resolve_fast_lane(config.ac_root, config.track_id, config.track_layout)
        line_artifact, line_source = ensure_alien_line_artifact(
            user_dir,
            fast_path,
            plant,
            artifact,
            car_id=config.car_id,
            track_id=config.track_id,
            layout=config.track_layout,
            setup=setup_key,
            setup_ini=config.setup_ini,
            v_top_kmh=config.racing_max_speed_kmh,
            l3_params=L3Params() if config.alien_l3 else None,
            rebuild=rebuild,
        )
    except (OSError, ValueError) as exc:
        return (f"alien line build failed — {exc}", plant_artifact_used, None)
    config.alien_line = line_artifact["line"]
    config.alien_v_target = line_artifact["v_target_mps"]
    alien_path = alien_line_path(
        user_dir,
        config.car_id,
        config.track_id,
        setup_key,
        config.setup_ini,
        layout=config.track_layout,
    )
    alien_line_used = {
        "path": str(alien_path),
        "source": line_source,
        "plant_provenance": line_artifact.get("plant_provenance"),
        "qss": line_artifact.get("qss"),
        "corridor": line_artifact.get("corridor"),
    }
    l3_report = line_artifact.get("l3")
    if isinstance(l3_report, dict):
        # The driver multiplies the artifact's v_target by config.ggv_scale AFTER this report
        # snapshot, so the artifact's own (unscaled) utilisation metrics would under-report an
        # overspeed probe as within-barrier. Recompute the DRIVEN target's utilisation exactly
        # against the same barrier; a failure is disclosed in the report, never swallowed
        # (#583 Codex P2).
        from tools.ac_harness.corner_refine import barrier_ggv, profile_utilisation
        from tools.ac_harness.ggv_profile import curvature_profile

        l3_report = dict(l3_report)
        scale = float(config.ggv_scale)
        l3_report["ggv_scale"] = scale
        try:
            l3p = L3Params.from_dict((line_artifact.get("params") or {}).get("l3"))
            plane = [(p[0], p[2]) for p in line_artifact["line"]]
            driven = [float(v) * scale for v in line_artifact["v_target_mps"]]
            l3_report["driven_max_ay_utilisation_vs_barrier"] = round(
                profile_utilisation(
                    curvature_profile(plane), driven, barrier_ggv(plant, l3p.max_rel_std)
                ),
                4,
            )
        except (TypeError, ValueError, KeyError) as exc:
            l3_report["driven_utilisation_error"] = f"{type(exc).__name__}: {exc}"
        alien_line_used["l3"] = l3_report
    qss = line_artifact.get("qss") or {}
    print(
        f"auto-drive: alien line {line_source} "
        f"(QSS {qss.get('qss_laptime_s')}s, vmax {qss.get('vmax_kmh')} km/h, "
        f"plant fit {line_artifact.get('plant_provenance', {}).get('sha12')}) <- {alien_path}"
    )
    if isinstance(l3_report, dict):
        reverted_all = l3_report.get("reverted_all")
        if reverted_all:
            print(f"auto-drive: alien L3 refinement reverted entirely — {reverted_all}")
        else:
            print(
                "auto-drive: alien L3 refined "
                f"{l3_report.get('refined_corners')} corner(s) "
                f"({l3_report.get('reverted_corners')} reverted to safe-QSS, "
                f"predicted gain {l3_report.get('predicted_gain_ms')} ms)"
            )
    return (None, plant_artifact_used, alien_line_used)


def _main_impl(
    argv: list[str] | None, cleanup: ExitStack
) -> int:  # pragma: no cover - rig-only CLI wiring
    args = _build_arg_parser().parse_args(argv)
    if args.cm_preset is None and not args.car:
        print("auto-drive: pass --car (preset is generated) or --cm-preset (hand-authored)")
        return 2
    if args.laps < 0:
        print(f"auto-drive: --laps must be >= 0 (got {args.laps})")
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
    # Plant artifacts are keyed by car+track+layout+setup (#532/#552). A preset-only run
    # (``--cm-preset`` without ``--car``) has no car id, so BOTH the handshake (which persists one)
    # and ``--use-plant full`` (which must load one) need ``--car`` explicitly — otherwise the
    # handshake would run the whole rig drive and then crash in ``save_plant_artifact`` with an
    # empty car id (Codex review), and ``--use-plant full`` would silently skip its own hard
    # requirement and drive on generic constants.
    if config.driver in ("handshake", "alien") and not config.car_id:
        print(
            f"auto-drive: --driver {config.driver} requires --car "
            "(the plant artifact is keyed by car)"
        )
        return 2
    if config.driver == "ggv" and args.use_plant == "full" and not config.car_id:
        print("auto-drive: --use-plant full requires --car (plant lookup is keyed by car+track)")
        return 2
    user_dir = resolve_ac_user_dir(config.ac_user_dir)

    # Resolve the setup .ini ONCE here (best-effort) so BOTH the ggv plant-load key and the
    # handshake artifact save share the same content-hashed identity — no asymmetric resolution
    # between drivers (daemon review). The authoritative confirm + print stays below; this only
    # populates config.setup_ini early enough for the plant-load key.
    if config.setup and config.setup_ini is None:
        try:
            config.setup_ini = resolve_setup_ini(
                user_dir, config.car_id, config.track_id, config.setup, layout=config.track_layout
            )
        except (FileNotFoundError, ValueError):
            config.setup_ini = None  # unresolved -> basename-only key (best effort)

    plant_artifact_used: str | None = None

    # #572: reject an overspeed scale on the alien path BEFORE any launch work. The alien QSS
    # profile is envelope-verified at build time; a scale above 1 would multiply corner speeds
    # past the verified plant envelope after that check (Codex review). #577 self-play may opt
    # in to a bounded overspeed probe (the LCB envelope is deliberately conservative; supra-LCB
    # evidence is what raises the measured bins) — capped and falsification-gated by auto_alien.
    alien_line_used: dict | None = None
    if config.driver == "alien":
        scale_cap = ALIEN_MAX_OVERSPEED_SCALE if config.alien_overspeed else 1.0
        if not 0.0 < config.ggv_scale <= scale_cap:
            print(
                f"auto-drive: --driver alien requires 0 < --ggv-scale <= {scale_cap} "
                f"(got {config.ggv_scale}"
                + ("" if config.alien_overspeed else "; --alien-allow-overspeed lifts to 1.2")
                + ")"
            )
            return 2
        if config.ggv_scale > 1.0:
            print(
                f"auto-drive: ALIEN OVERSPEED PROBE — ggv_scale={config.ggv_scale} drives above "
                "the uncertainty-safe QSS envelope (bounded, falsification-gated self-play step)"
            )

    effective_car_id = _effective_car_id(config)
    car_tag = "car"
    if effective_car_id:
        try:
            validate_ac_id("car", effective_car_id)
        except ValueError:
            pass  # preflight will report the invalid preset id; never use it as a path segment
        else:
            car_tag = effective_car_id
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

    app_provenance = app_install_provenance(config.ac_root)
    print(f"auto-drive: installed app provenance: {app_provenance.status}")
    issues = preflight(config, app_provenance=app_provenance)
    # #575: an app_version row is a warning by default; --strict-app-version makes it fatal for
    # runs whose evidence is only meaningful if the rig ran THIS checkout's app. Strictness gates
    # on the PROVENANCE VERDICT, not merely on the row's presence: an `absent` app cannot run the
    # wrong code, so it stays a warning even under strict (PR #587 review). A real drive defers
    # the strict abort to the post-lock recheck; only --preflight-only (which takes no lock, so
    # gets no later measurement) may abort on the pre-lock verdict.
    strict_app_fatal = app_version_preflight_fatal(
        app_provenance, strict=args.strict_app_version, preflight_only=args.preflight_only
    )
    fatal: list[PreflightIssue] = []
    for issue in issues:
        if issue.severity == "error" or (strict_app_fatal and issue.check == "app_version"):
            fatal.append(issue)
        else:
            print(f"auto-drive: PREFLIGHT WARNING [{issue.check}] {issue.message}")
    if fatal:
        print("auto-drive: PREFLIGHT FAILED")
        for issue in fatal:
            print(f"  [{issue.check}] {issue.message}")
        # A launch never started, so this is explicitly a non-drive outcome. Persist that
        # distinction in the normal evidence surface: downstream reliability summaries can skip
        # it without guessing from console text, and it can never inflate drive or sim-death
        # denominators (#603).
        error = "preflight failed: " + " | ".join(
            f"[{issue.check}] {issue.message}" for issue in fatal
        )
        preflight_report = AutoDriveReport(
            ok=False,
            stage="preflight",
            launched=False,
            hijacked=False,
            drive=None,
            error=error,
            car_id=effective_car_id,
            track_id=config.track_id,
            setup_requested=config.setup,
        )
        report_path = write_evidence(
            evidence_dir,
            preflight_report,
            extras={
                "run": {
                    "argv": list(argv) if argv is not None else None,
                    "cm_preset": str(config.cm_preset),
                    "driver": config.driver,
                    "app_install": app_provenance.to_dict(),
                },
                "preflight": {
                    "status": "failed",
                    "classification": "non_drive_preflight_failure",
                    "counts_as_drive_run": False,
                    "counts_as_sim_death": False,
                    "issues": [asdict(issue) for issue in fatal],
                },
            },
        )
        print(preflight_report.summary())
        print(f"  evidence: {report_path}")
        return 2
    print("auto-drive: preflight ok")
    if args.preflight_only:
        # #572: an alien readiness gate must include the alien prerequisites, or preflight-only
        # reports a false green for a drive that would exit at resolution (Codex review). Read-only
        # — validates the plant artifact + fast_lane without building or writing the line cache.
        if config.driver == "alien":
            alien_issue = _alien_prerequisites_error(config, user_dir)
            if alien_issue is not None:
                print(f"auto-drive: ALIEN PREFLIGHT FAILED — {alien_issue}")
                return 2
            print("auto-drive: alien prerequisites ok (plant artifact + fast_lane corridor)")
        elif config.driver == "ggv" and args.use_plant == "full":
            # #572: --use-plant full is a hard plant requirement — a preflight-only readiness
            # gate must not report green for a run that would exit at post-lock resolution.
            from tools.ac_harness.plant_id import (
                load_plant_artifact,
                plant_ready_for_full_consumption,
            )

            full_artifact = load_plant_artifact(
                user_dir,
                config.car_id,
                config.track_id,
                Path(config.setup).stem if config.setup else None,
                config.setup_ini,
                layout=config.track_layout,
            )
            full_reason = plant_ready_for_full_consumption(
                full_artifact, require_friction_fit=False
            )
            if full_reason is not None:
                print(
                    f"auto-drive: PREFLIGHT FAILED — --use-plant full: {full_reason}; "
                    "run --driver handshake first"
                )
                return 2
            print("auto-drive: --use-plant full prerequisites ok (plant artifact)")
        return 0

    if config.setup:
        if config.setup_ini is None:  # not resolved by the early best-effort pass above
            config.setup_ini = resolve_setup_ini(
                user_dir,
                config.car_id,
                config.track_id,
                config.setup,
                layout=config.track_layout,
            )
        print(f"auto-drive: setup resolved -> {config.setup_ini}")

    # #555: AC + Content Manager are one machine-global rig. A repo-local lock cannot serialize
    # different worktrees, so own the shared LocalAppData lock from before sidecar/launch through
    # drive teardown. A peer fails/waits here BEFORE either process can kill or relaunch its AC.
    from tools.ac_harness.rig_lock import (
        RigSessionBusy,
        RigSessionLock,
        RigSessionOwner,
        default_rig_session_lock_path,
    )

    rig_lock = RigSessionLock(
        default_rig_session_lock_path(),
        owner=RigSessionOwner(
            pid=os.getpid(),
            cwd=str(Path.cwd()),
            car=config.car_id,
            track=config.track_id,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            session_kind="auto_drive",
        ),
        timeout=args.rig_lock_timeout,
    )
    try:
        rig_lock.acquire()
    except RigSessionBusy as exc:
        print(f"auto-drive: RIG BUSY — {exc}")
        return 3
    cleanup.callback(rig_lock.release)
    print(f"auto-drive: rig lock acquired -> {rig_lock.path}")

    # #575 (PR #587 review): the installed app is shared rig state, so its provenance must be
    # measured UNDER the lock — same reasoning as the plant/line resolution below. The pre-lock
    # verdict above is fast feedback only: a peer worktree can repoint the junction while we block
    # here, which would both record a false verdict in the evidence bundle and let a pre-lock
    # `match` bypass --strict-app-version on an app that drifted since. (Observed live: a peer
    # worktree repointed the junction mid-session during this PR's own verification.)
    pre_lock_provenance = app_provenance
    app_provenance = app_install_provenance(config.ac_root)  # the verdict the drive actually runs
    race_note, app_version_fatal = app_provenance_recheck(
        pre_lock_provenance, app_provenance, strict=args.strict_app_version
    )
    if race_note:
        print(f"auto-drive: {race_note}")
    if app_version_fatal:
        print("auto-drive: PREFLIGHT FAILED (post-lock re-check)")
        print(f"  [app_version] {app_provenance.detail}")
        return 2

    # Plant/line artifact resolution happens AFTER preflight (actionable content errors, and
    # --preflight-only never writes state) and AFTER the machine-global rig lock, for EVERY
    # consumer of the plant artifact: a peer worktree may have re-identified this combo while we
    # waited on the lock, and resolving pre-lock would drive a stale in-memory plant that the
    # on-disk artifact has already superseded (#572 Codex + daemon review — same rule for the
    # ggv path, not just alien).
    if config.driver == "ggv" and args.use_plant != "off" and config.car_id:
        # #532: `auto` silently falls back to the generic plant when no artifact exists; `full`
        # REQUIRES one (measured steering must never silently degrade to hand constants — that is
        # the failure mode the handshake exists to end).
        from tools.ac_harness.plant_id import (
            load_plant_artifact,
            plant_artifact_path,
            plant_driver_kwargs,
            plant_ggv_model,
        )

        # Key by layout plus setup CONTENT (#532/#552): neither another physical course nor another
        # setup may reuse this plant. Uses the same track_layout + config.setup_ini identity that
        # the handshake result carries into save_plant_artifact.
        setup_key = Path(config.setup).stem if config.setup else None
        setup_ini_key = config.setup_ini
        artifact = load_plant_artifact(
            user_dir,
            config.car_id,
            config.track_id,
            setup_key,
            setup_ini_key,
            layout=config.track_layout,
        )
        if artifact is not None:
            config.plant_kwargs = plant_driver_kwargs(artifact, steer=args.use_plant == "full")
            # #532 Part B: also consume the identified friction plant (GGVModel) when the artifact
            # carries a fitted ggv block. Applies on `auto` and `full` alike — the friction plant
            # shapes the SPEED profile, orthogonal to the steering mode. None => generic plant.
            config.plant_ggv = plant_ggv_model(artifact)
            plant_artifact_used = str(
                plant_artifact_path(
                    user_dir,
                    config.car_id,
                    config.track_id,
                    setup_key,
                    setup_ini_key,
                    layout=config.track_layout,
                )
            )
            ggv_note = (
                "identified friction plant" if config.plant_ggv is not None else "generic plant"
            )
            print(
                f"auto-drive: plant artifact loaded ({args.use_plant}: "
                f"{sorted(config.plant_kwargs)}; {ggv_note}) <- {plant_artifact_used}"
            )
        elif args.use_plant == "full":
            print(
                "auto-drive: --use-plant full requires a plant artifact for this combo; "
                "run --driver handshake first"
            )
            return 2
        else:
            print("auto-drive: no plant artifact for this combo; using the generic GT3 plant")

    # #572 alien pipeline: resolve the identified plant (mandatory, full-steering semantics) and
    # the optimized line + QSS profile artifact (cache-or-build, identity + provenance gated).
    if config.driver == "alien":
        alien_error, plant_artifact_used, alien_line_used = _resolve_alien_assets(
            config, user_dir, rebuild=args.alien_rebuild_line
        )
        if alien_error is not None:
            print(f"auto-drive: {alien_error}")
            # Emit the evidence bundle even on this pre-launch exit. Without it the composed
            # self-play oracle sees no report.json at all and can only report "stage report
            # missing", which reads as a physical falsification of the envelope step when the
            # real cause was an asset/solver failure that never put the car on track (#695).
            write_evidence(
                evidence_dir,
                AutoDriveReport(
                    ok=False,
                    stage="alien_line",
                    error=alien_error,
                    car_id=config.car_id,
                    track_id=config.track_id,
                ),
            )
            return 2

    sidecar_proc = None
    try:
        sidecar_ok, sidecar_detail, sidecar_proc = ensure_sidecar(
            config.sidecar_url, autostart=not args.no_sidecar_autostart
        )
        print(f"auto-drive: {sidecar_detail}")
        if not sidecar_ok:
            return 2

        run_started_epoch = time.time()
        rig_telemetry_cleanup_holds: list[Controller] = []
        try:
            report = asyncio.run(
                run_auto_drive_with_sim_retries(
                    config,
                    launch=rig_launch,
                    hijack=lambda run_config: rig_hijack(
                        run_config,
                        retain_telemetry_controller=rig_telemetry_cleanup_holds.append,
                    ),
                    press_start=lambda: rig_press_session_start(config),
                    drive=rig_drive,
                    tap=tap_frames,
                    apply_setup=rig_apply_setup,
                    verify_track=rig_verify_track,
                    restart_launcher=rig_restart_launcher,
                    cleanup_failure=rig_force_safe_after_cleanup_failure,
                )
            )
        except ControllerCleanupAbort as exc:
            for retained_controller in rig_telemetry_cleanup_holds:
                exc.retain_cleanup_controller(retained_controller)
            raise
        for retained_controller in rig_telemetry_cleanup_holds:
            report.retain_cleanup_controller(retained_controller)
    finally:
        if sidecar_proc is not None and not args.keep_sidecar:
            sidecar_proc.terminate()

    # Keep the rig owned through HUD/archive/report capture: otherwise a waiting worktree can
    # relaunch AC in the narrow gap after drive teardown and corrupt this run's evidence bundle.
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
    handshake_laps_used = 0
    if config.driver == "handshake" and report.drive and isinstance(report.drive.payload, dict):
        pending_result = report.drive.payload.get("result")
        if isinstance(pending_result, dict):
            value = pending_result.get("laps_used")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                handshake_laps_used = value
    # #577 flying-lap window: every timed lap the tap observed should have an archive — the
    # trainer archives each timed boundary, and the self-play refine consumes the full batch.
    # The poll waits for that count (bounded), not merely the first archive. Batch semantics key
    # on INTENT (--laps requested / handshake), not on the observed count — a requested 1-lap
    # batch still gets the strict combo-matched validation its archives_same_run=True provenance
    # depends on (#579 daemon MEDIUM).
    batch_mode = config.target_laps > 0 or handshake_laps_used > 0
    # A batch run must also WAIT for its archives even when the grace didn't fire (e.g.
    # --lap-finalize-grace-s 0): grace-or-handshake alone would skip the poll and falsely
    # falsify the iteration on missing evidence (#579 daemon HIGH).
    wait_for_archives = report.lap_grace_applied or batch_mode
    timed_laps_observed = len(report.lap_times_ms)
    expected_archives = max(handshake_laps_used, timed_laps_observed)

    def _combo_predicate(payload: dict) -> bool:
        return archive_matches_combo(
            payload,
            car_id=config.car_id,
            track_id=config.track_id,
            layout=config.track_layout,
        )

    lap_archives = collect_lap_archives(
        None,
        run_started_epoch,
        resolve=lambda: candidate_journal_laps_dirs(user_dir),
        wait_for_first=wait_for_archives,
        min_count=max(1, expected_archives),
        # Valid-count gating is HANDSHAKE-only (the fit must never promote from a partial valid
        # set). A flying-lap batch must not gate on validity: an AC-invalid lap still writes its
        # archive, that archive IS the falsification evidence the self-play verdict needs
        # promptly, and no amount of waiting turns it valid — gating on it would stall the poll
        # to full timeout on every falsified batch (#579 Qodo). The batch DOES gate on the
        # combo-matched count (validity-agnostic): the multi-dir resolver can see another
        # app/combo's fresh archives, which must not satisfy the batch before this combo's own
        # writer finishes (#579 Codex P2).
        min_valid_count=handshake_laps_used if handshake_laps_used > 0 else None,
        # The combo gate needs a car identity to match against: a preset-only run (--cm-preset
        # without --car) has none, so the predicate could never match and the poll would always
        # burn its full timeout (#579 Qodo perf).
        min_matching_count=(
            expected_archives if batch_mode and expected_archives > 0 and config.car_id else None
        ),
        # Defensive: without a car identity the predicate can never match, so it must not gate
        # ANY counting path (min_valid_count is handshake-only and handshake requires --car, so
        # this is unreachable today — kept consistent regardless; #579 daemon MEDIUM).
        valid_archive_predicate=_combo_predicate if config.car_id else None,
        timeout_s=20.0 if batch_mode else 8.0,
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
            "use_plant": args.use_plant,
            "plant_artifact": plant_artifact_used,
            "alien_line": alien_line_used,
            "sidecar": sidecar_detail,
            # #575: the app version the rig actually ran. Without it, a bundle cannot be trusted
            # retroactively — a stale junction silently invalidates every archive it produced.
            "app_install": app_provenance.to_dict(),
        },
        "hud": hud,
        "lap_archives": lap_archives,
        "journal_dir": str(journal_dir) if journal_dir else None,
    }
    if config.driver == "handshake":
        # #532: fold the handshake outcome into the report and persist a PASSED result as the
        # combo's plant artifact. Diagnostics ALWAYS go to extras. But only OVERWRITE the report
        # stage/error when the drive actually reached the handshake — a pre-drive failure
        # (stage=launch/hijack/setup, e.g. the track/car guard) is the authoritative root cause
        # and must NOT be clobbered with "handshake produced no result" (Codex + Qodo review).
        from tools.ac_harness.plant_id import (
            apply_handshake_outcome,
            refine_ggv_from_lap_archives,
            save_plant_artifact,
        )

        # The handshake result flows out via DriveStats.payload (report.drive.payload), not a
        # config side-channel (daemon review).
        sink = dict(report.drive.payload) if report.drive and report.drive.payload else {}
        matching_valid_archives = _count_valid_lap_archives(lap_archives, _combo_predicate)
        if (
            sink.get("ok")
            and isinstance(sink.get("result"), dict)
            and handshake_laps_used > 0
            and matching_valid_archives < handshake_laps_used
        ):
            # The bounded writer wait expired with a partial lap set. Do not promote a model from
            # lap 1 while the thermal/probe-relevant lap 2 is absent; constants may still persist.
            sink["result"]["ggv"] = {
                "ok": False,
                "model": None,
                "reason": (
                    "incomplete handshake lap archive set: "
                    f"{matching_valid_archives} "
                    f"matching valid < {handshake_laps_used}"
                ),
            }
        elif sink.get("ok") and isinstance(sink.get("result"), dict):
            # #543: live physics rows alone have no tyre state. Refine only from the immutable
            # #488 lap archives collected by the same run; no archive/thermal cohort means the ggv
            # block remains visibly unavailable and --use-plant safely keeps the generic plant.
            refine_ggv_from_lap_archives(
                sink["result"],
                lap_archives,
                generic_gt3_ggv(),
                prior_name="generic_gt3_ggv",
                archives_same_run=True,
            )
        extras["handshake"] = sink
        # Fold the handshake outcome ONLY when the run otherwise fully SUCCEEDED (`report.ok`).
        # report.ok already vetoes on a pipeline check failure (`seq_ok is False`) or a drive-leg
        # veto (`sim_dead` / `recovery_capped`) — none of which raise, so gating on `error is None`
        # alone would still mask them. Any such run-level failure is the authoritative root cause
        # and must NOT be replaced with "handshake produced no result" or probe-failure details
        # caused by the earlier stop/veto (daemon HIGH + Codex). On a clean run,
        # apply_handshake_outcome sets the honest handshake verdict (incl. empty-sink "no result").
        if report.ok:
            apply_handshake_outcome(report, sink)
        # Persist the plant ONLY from a fully clean run (report.ok): a drive-leg veto (sim_dead /
        # recovery_capped) can leave sink["ok"]=True from samples collected before the veto, but
        # constants from a compromised/stale drive must NOT be promoted into the reusable artifact
        # for later --use-plant runs (Codex review). report.ok already vetoes on those flags.
        if sink.get("ok") and report.ok:
            artifact_path = save_plant_artifact(user_dir, sink["result"])
            extras["plant_artifact_saved"] = str(artifact_path)
            print(f"auto-drive: plant artifact saved -> {artifact_path}")
        elif sink.get("ok") and not report.ok:
            note = "handshake probes passed but the drive was vetoed — plant NOT persisted"
            report.notes.append(note)
            print(f"auto-drive: {note}")
    # Handshake post-processing above can change the final verdict after the retry wrapper took
    # its attempt snapshot. Refresh only the final attempt so the aggregate and top-level report
    # have the same final truth; earlier failed attempts remain immutable evidence.
    if report.attempts:
        report.attempts[-1] = _attempt_snapshot(report)
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
    exit_code = 0 if report.ok else 1
    return exit_code


def _main(argv: list[str] | None = None) -> int:  # pragma: no cover - rig-only CLI wiring
    # ExitStack makes the machine-global rig lock exception-safe for both the CLI and programmatic
    # callers, including failures during HUD/archive/report capture after the drive has stopped.
    # ControllerCleanupAbort is the one deliberate exception: the process still owns a native
    # control mapping, so detach and retain the stack instead of running rig_lock.release. The OS
    # releases both mapping and byte lock together when this fatal CLI process exits.
    cleanup = ExitStack()
    try:
        return _main_impl(argv, cleanup)
    except ControllerCleanupAbort as exc:
        hold = cleanup.pop_all()
        exc.cleanup_hold = hold
        raise
    finally:
        cleanup.close()


def _exit_after_controller_cleanup_abort(exc: ControllerCleanupAbort) -> None:
    """Emit chained fatal-cleanup evidence, then atomically drop the mapping and rig lock."""
    print(
        "auto-drive: fatal controller cleanup abort; retained native resources will be released "
        "by immediate OS process exit",
        file=sys.stderr,
    )
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    sys.stderr.flush()
    os._exit(1)


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    from pathlib import Path as _Path

    _repo_root = str(_Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    try:
        _exit_code = _main()
    except ControllerCleanupAbort as _cleanup_abort:
        # Do not run normal interpreter unwinding after a fatal native cleanup failure: the OS
        # closes the retained Custom-AI mapping and rig-lock descriptor together at process exit,
        # leaving no window where a peer can acquire the rig while this process still controls it.
        # Emit and flush the chained exception first so the rare native failure remains diagnosable.
        _exit_after_controller_cleanup_abort(_cleanup_abort)
    raise SystemExit(_exit_code)
