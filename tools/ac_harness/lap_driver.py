"""Autonomous lap driver — orchestrates :mod:`ai_line` (where to go) and :mod:`custom_ai`
(how to actuate) into a car that drives clean laps of a real track with no human.

This is the orchestration keystone of EPIC #154 Part E (#190). :class:`PurePursuit` gives a
steering/throttle frame for following the racing line, but a real drive also needs: shifting out
of neutral and managing gears, getting **out of the pit box** when the car spawns/resets there
(pure pursuit alone full-locks in place off-line), detecting lap completion without the unreliable
``cai_car_data`` spline (LIVE-VERIFIED garbage; see :mod:`custom_ai`), and recovering from a stuck
state. :class:`LapDriver` folds those into one controller.

Design mirrors the rest of ``ac_harness``: the decision logic is **pure and deterministic**
(:meth:`LapDriver.step` takes the live pose + clock and returns a control frame; no mmap, no real
clock, no Assetto Corsa) so CI verifies it on any OS with synthetic inputs, exactly like
:class:`ai_line.PurePursuit`. The Windows-only run loop (:meth:`LapDriver.run`) that wires it to a
:class:`custom_ai.CustomAIController` at ~80 Hz is pragma-guarded and validated on the rig — it was
proven over a 30-minute continuous zero-crash drive of Magione.

Live-verified behaviour baked in (2026-06-16, Porsche 911 GT3 R at Magione):
* AC ``gear`` encoding is **0=Reverse, 1=NEUTRAL, 2=1st** — so "in gear" means ``gear >= 2``.
* The launch needs ``autoclutch_on_start`` + ``autoclutch_on_change`` (the controller always sets
  them); a manually-written clutch fights the autoclutch, so we never touch it.
* ``steer > 0`` turns the car right (matches :class:`ai_line.PurePursuit`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from tools.ac_harness.ai_line import ControlOutput, PurePursuit, _horizontal

# Phases. OUT = getting from the pit box / off-line back onto the racing line; LAP = following it.
PHASE_OUT = "OUT"
PHASE_LAP = "LAP"


@dataclass(frozen=True)
class DriveFrame:
    """One decision from :meth:`LapDriver.step` — a control frame plus harness signals.

    ``gas`` / ``brake`` ``0..1``, ``steer`` ``-1..1`` (>0 = right). ``gear_up`` / ``gear_dn`` are
    one-frame shift pulses. ``phase`` is :data:`PHASE_OUT` / :data:`PHASE_LAP`. ``lap_completed``
    is True on the single frame a full lap closes (position-return). ``needs_recovery`` is True
    when the car has been stuck (slow while asking for throttle) past the threshold — the run loop
    answers it with a teleport-to-pits.
    """

    gas: float
    brake: float
    steer: float
    gear_up: bool
    gear_dn: bool
    phase: str
    lap_completed: bool
    needs_recovery: bool


def _planar_nearest_distance_m(
    pursuit: PurePursuit, position_xyz: tuple[float, float, float]
) -> float:
    """Planar (x, z) distance from ``position_xyz`` to the closest racing-line point, in metres."""
    car = _horizontal(position_xyz)
    idx = pursuit.nearest_index(car)
    px, pz = pursuit._plane[idx]
    return math.hypot(px - car[0], pz - car[1])


class LapDriver:
    """Drive one car around ``fast_line`` from any starting state (pits, off-line, on-line).

    Pure tuning + state; feed live telemetry to :meth:`step`. ``merge_distance_m`` is how close to
    the line (and ``merge_speed_kmh`` how fast) the car must be to switch OUT→LAP. In OUT the steer
    is clamped to ``out_steer_clamp`` and gas floored to ``out_gas`` so the car drives *forward* out
    of the box instead of full-locking in place. Gears: shift up out of neutral and above
    ``rpm_up`` (capped at ``max_gear``), down below ``rpm_dn``. Lap completion is position-return:
    a lap closes when the car has travelled ``min_lap_m`` and is back within ``return_radius_m`` of
    the lap-start anchor (``cai_car_data`` spline is unusable — see module docstring).
    """

    def __init__(
        self,
        fast_line: list[tuple[float, float, float]],
        *,
        lookahead_m: float = 10.0,
        target_speed_kmh: float = 50.0,
        min_corner_speed_kmh: float = 26.0,
        max_steer_curvature: float = 0.16,
        curvature_lookahead_m: float = 38.0,
        merge_distance_m: float = 9.0,
        merge_speed_kmh: float = 10.0,
        out_steer_clamp: float = 0.35,
        out_gas: float = 0.30,
        rpm_up: float = 7800.0,
        rpm_dn: float = 3200.0,
        max_gear: int = 3,
        shift_cooldown_s: float = 0.35,
        stuck_speed_kmh: float = 3.0,
        stuck_seconds: float = 5.0,
        stuck_throttle: float = 0.1,
        min_lap_m: float = 1800.0,
        return_radius_m: float = 12.0,
    ) -> None:
        self.pursuit = PurePursuit(
            fast_line,
            lookahead_m=lookahead_m,
            target_speed_kmh=target_speed_kmh,
            min_corner_speed_kmh=min_corner_speed_kmh,
            max_steer_curvature=max_steer_curvature,
            curvature_lookahead_m=curvature_lookahead_m,
        )
        self.merge_distance_m = merge_distance_m
        self.merge_speed_kmh = merge_speed_kmh
        self.out_steer_clamp = out_steer_clamp
        self.out_gas = out_gas
        self.rpm_up = rpm_up
        self.rpm_dn = rpm_dn
        self.max_gear = max_gear
        self.shift_cooldown_s = shift_cooldown_s
        self.stuck_speed_kmh = stuck_speed_kmh
        self.stuck_seconds = stuck_seconds
        self.stuck_throttle = stuck_throttle
        self.min_lap_m = min_lap_m
        self.return_radius_m = return_radius_m

        # Mutable run state.
        self.phase = PHASE_OUT
        self._last_shift_s = -1e9
        self._stuck_since: float | None = None
        self._lap_anchor: tuple[float, float] | None = None
        self._lap_distance_m = 0.0
        self._prev_plane: tuple[float, float] | None = None

    def _gear_pulse(self, rpm: float, gear: int, speed_kmh: float, now: float) -> tuple[bool, bool]:
        """Decide a one-frame shift. Shift out of neutral (gear<2), up past ``rpm_up`` (while
        moving, capped at ``max_gear``), down past ``rpm_dn`` (only while rolling and above 1st).
        Rate-limited by ``shift_cooldown_s`` so one rising edge is one shift."""
        if now - self._last_shift_s <= self.shift_cooldown_s:
            return (False, False)
        if gear < 2:
            self._last_shift_s = now
            return (True, False)
        if rpm > self.rpm_up and gear < self.max_gear and speed_kmh > 20.0:
            self._last_shift_s = now
            return (True, False)
        if rpm < self.rpm_dn and gear > 2 and speed_kmh > 5.0:
            self._last_shift_s = now
            return (False, True)
        return (False, False)

    def _accumulate_lap(self, car_plane: tuple[float, float]) -> bool:
        """Track distance travelled + position-return lap closure. Returns True the frame a lap
        closes. Anchored at the first LAP-phase position; resets the anchor on closure."""
        if self._lap_anchor is None:
            self._lap_anchor = car_plane
            self._lap_distance_m = 0.0
            self._prev_plane = car_plane
            return False
        if self._prev_plane is not None:
            self._lap_distance_m += math.hypot(
                car_plane[0] - self._prev_plane[0], car_plane[1] - self._prev_plane[1]
            )
        self._prev_plane = car_plane
        if self._lap_distance_m >= self.min_lap_m:
            back = math.hypot(
                car_plane[0] - self._lap_anchor[0], car_plane[1] - self._lap_anchor[1]
            )
            if back <= self.return_radius_m:
                self._lap_anchor = car_plane
                self._lap_distance_m = 0.0
                return True
        return False

    def step(
        self,
        position_xyz: tuple[float, float, float],
        look_dir_xyz: tuple[float, float, float],
        speed_kmh: float,
        rpm: float,
        gear: int,
        now: float,
    ) -> DriveFrame:
        """Pure: one control decision from the live pose + monotonic clock ``now`` (seconds)."""
        dist_to_line = _planar_nearest_distance_m(self.pursuit, position_xyz)

        if (
            self.phase == PHASE_OUT
            and dist_to_line < self.merge_distance_m
            and speed_kmh > self.merge_speed_kmh
        ):
            self.phase = PHASE_LAP

        out: ControlOutput = self.pursuit.control(position_xyz, look_dir_xyz, speed_kmh)
        gas, brake, steer = out.gas, out.brake, out.steer
        if self.phase == PHASE_OUT:
            gas = max(gas, self.out_gas)
            brake = 0.0
            steer = max(-self.out_steer_clamp, min(self.out_steer_clamp, steer))

        gear_up, gear_dn = self._gear_pulse(rpm, gear, speed_kmh, now)

        # Stuck = barely moving while we are commanding meaningful throttle. The threshold must sit
        # BELOW out_gas (OUT-phase floors gas at 0.30) and the PurePursuit zero-look creep (0.30),
        # or a car stuck in OUT phase would never trip recovery (Bugbot).
        needs_recovery = False
        if speed_kmh < self.stuck_speed_kmh and gas > self.stuck_throttle:
            if self._stuck_since is None:
                self._stuck_since = now
            elif now - self._stuck_since > self.stuck_seconds:
                needs_recovery = True
        else:
            self._stuck_since = None

        lap_completed = (
            self._accumulate_lap(_horizontal(position_xyz)) if self.phase == PHASE_LAP else False
        )

        return DriveFrame(
            gas=gas,
            brake=brake,
            steer=steer,
            gear_up=gear_up,
            gear_dn=gear_dn,
            phase=self.phase,
            lap_completed=lap_completed,
            needs_recovery=needs_recovery,
        )

    def on_recovery(self) -> None:
        """Reset transient state after the run loop teleports the car to pits — re-enter OUT and
        clear the stuck timer and the lap anchor (the car is no longer on its lap)."""
        self.phase = PHASE_OUT
        self._stuck_since = None
        self._lap_anchor = None
        self._lap_distance_m = 0.0
        self._prev_plane = None

    def run(self, controller, *, seconds: float, on_lap=None):  # pragma: no cover - rig-only
        """Drive ``controller`` (a :class:`custom_ai.CustomAIController`) for ``seconds`` at ~80 Hz.

        Pulls the live pose from ``controller.read_car_data()``, feeds :meth:`step`, writes the
        frame, and on ``needs_recovery`` teleports to pits and re-enters OUT. Calls ``on_lap(n)``
        on each completed lap. Returns the completed-lap count. Windows/rig-only.
        """
        import time

        laps = 0
        # monotonic(): immune to wall-clock/NTP jumps that would corrupt elapsed-time + the
        # stuck/cooldown timers fed to step() (CodeRabbit).
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < seconds:
                cd = controller.read_car_data()
                if not cd:
                    time.sleep(0.02)
                    continue
                frame = self.step(
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
                    self.on_recovery()
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
                if frame.lap_completed:
                    laps += 1
                    if on_lap is not None:
                        on_lap(laps)
                time.sleep(0.012)
        finally:
            for _ in range(20):
                controller.write_controls(0.0, 0.6, 0.0)
                time.sleep(0.05)
        return laps
