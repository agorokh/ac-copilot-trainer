"""Racing driver — follows ``fast_lane.ai``'s embedded speed profile with real braking points,
trail braking, and traction-limited throttle (EPIC #154 Part G, #241).

Where :mod:`lap_driver` is a ~50 km/h lane-keeper that *never brakes*, this drives racing dynamics:
``fast_lane.ai`` stores, per point, the speed/gas/brake the game AI actually uses (magione: up to
223 km/h on the straights, hard braking into corners). :func:`load_speed_profile` reads that, and
:class:`RacingDriver`:

* **braking points** — a backward pass over the (cyclic) profile, using the car's brake-g, makes
  each point's target only as fast as you can still brake to the next; so the car brakes *before* a
  corner, not in it;
* **hard braking** — full brake when well over the target, closed-loop on the speed error;
* **traction-limited throttle** — lift on throttle as steering loads the car (friction-circle proxy)
  so it does not just spin the wheels on corner exit;
* **trail braking** — bleed the brake off as steering increases (coupled brake+steer).

Steering reuses :class:`ai_line.PurePursuit`. The decision logic (:meth:`RacingDriver.step`) is pure
and deterministic — CI-verified with synthetic lines, exactly like :class:`lap_driver.LapDriver`. A
``pace`` fraction + ``max_speed_kmh`` cap scale the optimal profile into pure-pursuit's stable
steering envelope; the *dynamics* (hard braking, trail braking, real corner-vs-straight speeds, full
gearbox) are real racing — closing the gap to optimal pace needs a stronger steering controller
(tracked follow-up, see #241).
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from tools.ac_harness.ai_line import PurePursuit, _horizontal
from tools.ac_harness.lap_driver import PHASE_LAP, PHASE_OUT, DriveFrame

# fast_lane.ai AiPointExtra block: speed@0, gas@4, brake@8 — 72-byte stride. Ground-truthed live
# against magione (count 1754, speeds 0->61.9 m/s) and the actools AiPoint layout.
_HEADER_SIZE = 16
_POINT_SIZE = 20
_EXTRA_STRIDE = 72


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def load_speed_profile(path: str | Path) -> list[float]:
    """Parse the per-point target SPEED (m/s) the game AI drives, from ``fast_lane.ai``.

    Returns one speed per main point, ordered along the racing direction (same length/order as
    :func:`ai_line.load_ai_line`). Raises :class:`ValueError` if the extra block is missing or its
    ``extraCount`` cross-check fails.
    """
    data = Path(path).read_bytes()
    if len(data) < _HEADER_SIZE:
        raise ValueError(f"fast_lane.ai too short: {len(data)} bytes")
    _version, count, _lap, _samp = struct.unpack_from("<4i", data, 0)
    if count <= 0:
        raise ValueError(f"fast_lane.ai non-positive count: {count}")
    main_end = _HEADER_SIZE + count * _POINT_SIZE
    if main_end + 4 > len(data):
        raise ValueError("fast_lane.ai has no AiPointExtra block")
    extra_count = struct.unpack_from("<i", data, main_end)[0]
    if extra_count != count:
        raise ValueError(f"AiPointExtra count {extra_count} != point count {count}")
    extra_start = main_end + 4
    if extra_start + count * _EXTRA_STRIDE > len(data):
        raise ValueError(
            f"AiPointExtra block needs {extra_start + count * _EXTRA_STRIDE} bytes, "
            f"file is {len(data)}"
        )
    return [
        struct.unpack_from("<f", data, extra_start + i * _EXTRA_STRIDE)[0] for i in range(count)
    ]


class RacingDriver:
    """Drive ``fast_line`` at racing dynamics from any starting state (pits, off-line, on-line).

    ``speed_profile`` is the per-point target speed (m/s) from :func:`load_speed_profile` (same
    length as ``fast_line``). The optimal profile is scaled by ``pace`` and capped at
    ``max_speed_kmh`` (pure-pursuit's stable steering envelope), then a backward pass at ``brake_g``
    bakes in the braking points.
    """

    def __init__(
        self,
        fast_line: list[tuple[float, float, float]],
        speed_profile: list[float],
        *,
        pace: float = 0.55,
        max_speed_kmh: float = 62.0,
        min_speed_kmh: float = 20.0,
        brake_g: float = 1.2,
        lookahead_m: float = 16.0,
        lookahead_time_s: float = 0.5,
        max_steer_curvature: float = 0.20,
        wheelbase_m: float = 2.5,
        brake_band_ms: float = 0.5,
        brake_scale_ms: float = 4.0,
        throttle_scale_ms: float = 6.0,
        base_gas: float = 0.05,
        trail_release: float = 0.7,
        trail_min: float = 0.2,
        traction_lift: float = 0.6,
        rpm_up: float = 7600.0,
        rpm_dn: float = 3400.0,
        max_gear: int = 6,
        shift_cooldown_s: float = 0.3,
        out_gas: float = 0.35,
        out_steer_clamp: float = 0.4,
        merge_distance_m: float = 9.0,
        merge_speed_kmh: float = 12.0,
        stuck_speed_kmh: float = 3.0,
        stuck_seconds: float = 5.0,
        stuck_throttle: float = 0.1,
        min_lap_m: float = 1800.0,
        return_radius_m: float = 12.0,
    ) -> None:
        if len(fast_line) != len(speed_profile):
            raise ValueError(
                f"line ({len(fast_line)}) and speed_profile ({len(speed_profile)}) length mismatch"
            )
        if not 0.0 < pace <= 1.0:
            raise ValueError("pace must be in (0, 1]")
        if max_speed_kmh <= 0 or min_speed_kmh <= 0 or min_speed_kmh > max_speed_kmh:
            raise ValueError("require 0 < min_speed_kmh <= max_speed_kmh")
        if brake_g <= 0 or brake_scale_ms <= 0 or throttle_scale_ms <= 0:
            raise ValueError("brake_g, brake_scale_ms, throttle_scale_ms must be > 0")

        self.pursuit = PurePursuit(
            fast_line,
            lookahead_m=lookahead_m,
            target_speed_kmh=max(max_speed_kmh, 1.0),
            min_corner_speed_kmh=max(min(min_speed_kmh, max_speed_kmh), 1.0),
            max_steer_curvature=max_steer_curvature,
            wheelbase_m=wheelbase_m,
        )
        self.n = len(fast_line)
        self.lookahead_m = lookahead_m
        self.lookahead_time_s = lookahead_time_s
        self.brake_band_ms = brake_band_ms
        self.brake_scale_ms = brake_scale_ms
        self.throttle_scale_ms = throttle_scale_ms
        self.base_gas = base_gas
        self.trail_release = trail_release
        self.trail_min = trail_min
        self.traction_lift = traction_lift
        self.rpm_up = rpm_up
        self.rpm_dn = rpm_dn
        self.max_gear = max_gear
        self.shift_cooldown_s = shift_cooldown_s
        self.out_gas = out_gas
        self.out_steer_clamp = out_steer_clamp
        self.merge_distance_m = merge_distance_m
        self.merge_speed_kmh = merge_speed_kmh
        self.stuck_speed_kmh = stuck_speed_kmh
        self.stuck_seconds = stuck_seconds
        self.stuck_throttle = stuck_throttle
        self.min_lap_m = min_lap_m
        self.return_radius_m = return_radius_m

        # Scaled + capped target, then brake-feasible backward pass -> per-point m/s target.
        cap = max_speed_kmh / 3.6
        floor = min_speed_kmh / 3.6
        scaled = [_clamp(pace * s, floor, cap) for s in speed_profile]
        self.profile = self._backward_pass(scaled, brake_g)

        # Mutable run state (mirrors LapDriver).
        self.phase = PHASE_OUT
        self._last_shift_s = -1e9
        self._stuck_since: float | None = None
        self._lap_anchor: tuple[float, float] | None = None
        self._lap_distance_m = 0.0
        self._prev_plane: tuple[float, float] | None = None

    def _backward_pass(self, v: list[float], brake_g: float) -> list[float]:
        """Limit each point's speed so the car can still brake to the next (cyclic backward pass).

        ``v[i] <- min(v[i], sqrt(v[i+1]^2 + 2*a*ds))`` with ``a = brake_g*g``. Repeated a few times
        so the constraint propagates across the start/finish wrap of the closed line.
        """
        a = brake_g * 9.81
        seg = self.pursuit._seg_len
        n = self.n
        out = list(v)
        for _ in range(4):
            for j in range(n):
                i = (n - 1 - j) % n
                nxt = (i + 1) % n
                ds = seg[i]
                cap = math.sqrt(out[nxt] * out[nxt] + 2.0 * a * ds)
                if out[i] > cap:
                    out[i] = cap
        return out

    def target_speed_kmh(self, idx: int, speed_kmh: float) -> float:
        """Brake-feasible target (km/h) at ``idx`` with a speed-scaled look-ahead margin."""
        v_cur = speed_kmh / 3.6
        look_idx = self.pursuit._advance(idx, max(self.lookahead_m, v_cur * self.lookahead_time_s))
        return min(self.profile[idx], self.profile[look_idx]) * 3.6

    def _longitudinal(self, idx: int, speed_kmh: float, steer: float) -> tuple[float, float]:
        """Racing throttle/brake toward the brake-feasible profile (trail braking + traction)."""
        v_cur = speed_kmh / 3.6
        target = self.target_speed_kmh(idx, speed_kmh) / 3.6
        lat = abs(steer)  # cornering load proxy (steer fraction)
        err = v_cur - target
        if err > self.brake_band_ms:
            brake = _clamp((err - self.brake_band_ms) / self.brake_scale_ms, 0.0, 1.0)
            # trail braking: bleed brake off as steering loads the front, but keep some mid-corner.
            brake *= max(self.trail_min, 1.0 - self.trail_release * lat)
            return 0.0, brake
        # Under/at target: throttle toward it, lifting as steering loads the car (anti-wheelspin).
        gas = _clamp((target - v_cur) / self.throttle_scale_ms + self.base_gas, 0.0, 1.0)
        gas *= max(0.0, 1.0 - self.traction_lift * lat)
        return gas, 0.0

    def _gear_pulse(self, rpm: float, gear: int, speed_kmh: float, now: float) -> tuple[bool, bool]:
        """One-frame shift: out of neutral, up past ``rpm_up`` while moving, down at ``rpm_dn``."""
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
        """Distance travelled + position-return lap closure (anchored at first LAP position)."""
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
        """Pure: one racing control decision from the live pose + monotonic clock ``now`` (s)."""
        car = _horizontal(position_xyz)
        idx = self.pursuit.nearest_index(car)
        dist_to_line = math.hypot(
            self.pursuit._plane[idx][0] - car[0], self.pursuit._plane[idx][1] - car[1]
        )
        if (
            self.phase == PHASE_OUT
            and dist_to_line < self.merge_distance_m
            and speed_kmh > self.merge_speed_kmh
        ):
            self.phase = PHASE_LAP

        steer = self.pursuit.control(position_xyz, look_dir_xyz, speed_kmh).steer
        if self.phase == PHASE_OUT:
            gas, brake = self.out_gas, 0.0
            steer = _clamp(steer, -self.out_steer_clamp, self.out_steer_clamp)
        else:
            gas, brake = self._longitudinal(idx, speed_kmh, steer)

        gear_up, gear_dn = self._gear_pulse(rpm, gear, speed_kmh, now)

        needs_recovery = False
        if speed_kmh < self.stuck_speed_kmh and gas > self.stuck_throttle:
            if self._stuck_since is None:
                self._stuck_since = now
            elif now - self._stuck_since > self.stuck_seconds:
                needs_recovery = True
        else:
            self._stuck_since = None

        lap_completed = self._accumulate_lap(car) if self.phase == PHASE_LAP else False

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
        """Reset transient state after a teleport-to-pits recovery — re-enter OUT, clear timers."""
        self.phase = PHASE_OUT
        self._stuck_since = None
        self._lap_anchor = None
        self._lap_distance_m = 0.0
        self._prev_plane = None

    def run(self, controller, *, seconds: float, on_lap=None):  # pragma: no cover - rig-only
        """Drive ``controller`` (a ``custom_ai.CustomAIController``) for ``seconds`` at ~80 Hz."""
        import time

        laps = 0
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
            for _ in range(25):
                controller.write_controls(0.0, 0.8, 0.0)
                time.sleep(0.04)
        return laps
