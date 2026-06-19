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

Steering defaults to :class:`ai_line.StanleySteering`, which tracks path tangent + cross-track error
instead of cutting to a look-ahead point. The decision logic (:meth:`RacingDriver.step`) is pure and
deterministic — CI-verified with synthetic lines, exactly like :class:`lap_driver.LapDriver`.
"""

from __future__ import annotations

import csv
import math
import struct
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from tools.ac_harness.ai_line import PurePursuit, StanleySteering, _horizontal
from tools.ac_harness.lap_driver import PHASE_LAP, PHASE_OUT, DriveFrame

# fast_lane.ai AiPointExtra block: speed@0, gas@4, brake@8 — 72-byte stride. Ground-truthed live
# against magione (count 1754, speeds 0->61.9 m/s) and the actools AiPoint layout.
_HEADER_SIZE = 16
_POINT_SIZE = 20
_EXTRA_STRIDE = 72
_EXPECTED_VERSION = 7
# Repeated cyclic backward sweeps; 4 passes propagate brake-feasible caps across km-scale lines.
_BACKWARD_PASS_PASSES = 4


@dataclass(frozen=True)
class AiPointProfile:
    """Per-point AiPointExtra signals from ``fast_lane.ai`` (speed + gas + brake)."""

    speed_mps: float
    gas: float
    brake: float


@dataclass(frozen=True)
class HumanProfilePoint:
    """Per-normalized-track-position target distilled from human laps."""

    norm_pos: float
    speed_mps: float
    brake: float
    gas: float
    min_speed_mps: float


def _parse_fast_lane_extra(data: bytes) -> list[AiPointProfile]:
    """Shared header/extra-block parser for ``fast_lane.ai`` profile loaders."""
    if len(data) < _HEADER_SIZE:
        raise ValueError(f"fast_lane.ai too short: {len(data)} bytes")
    version, count, _lap, _samp = struct.unpack_from("<4i", data, 0)
    if version != _EXPECTED_VERSION:
        raise ValueError(
            f"fast_lane.ai version {version} unsupported (expected {_EXPECTED_VERSION})"
        )
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
    out: list[AiPointProfile] = []
    for i in range(count):
        base = extra_start + i * _EXTRA_STRIDE
        speed, gas, brake = struct.unpack_from("<3f", data, base)
        if not all(math.isfinite(x) for x in (speed, gas, brake)):
            raise ValueError(f"AiPointExtra[{i}] non-finite speed/gas/brake")
        if speed < 0:
            raise ValueError(f"AiPointExtra[{i}] negative speed: {speed}")
        if not 0.0 <= gas <= 1.0 or not 0.0 <= brake <= 1.0:
            raise ValueError(f"AiPointExtra[{i}] gas/brake out of range 0..1: {gas}, {brake}")
        out.append(AiPointProfile(speed_mps=speed, gas=gas, brake=brake))
    return out


def load_ai_profile(path: str | Path) -> list[AiPointProfile]:
    """Parse per-point speed/gas/brake from the AiPointExtra block in ``fast_lane.ai``."""
    return _parse_fast_lane_extra(Path(path).read_bytes())


def load_speed_profile(path: str | Path) -> list[float]:
    """Parse the per-point target SPEED (m/s) the game AI drives, from ``fast_lane.ai``.

    Returns one speed per main point, ordered along the racing direction (same length/order as
    :func:`ai_line.load_ai_line`). Raises :class:`ValueError` if the extra block is missing or its
    ``extraCount`` cross-check fails. For gas/brake too, use :func:`load_ai_profile`.
    """
    return [p.speed_mps for p in load_ai_profile(path)]


def load_human_profile(path: str | Path) -> list[HumanProfilePoint]:
    """Parse the human-lap profile CSV produced from ``racing_telemetry`` captures.

    The committed Magione fixture is keyed by ``normalizedCarPosition`` and carries the human
    speed/brake/gas targets used for #244. Values are returned sorted by ``norm_pos`` and speeds
    are converted to m/s so they can feed :class:`RacingDriver` directly.
    """
    rows: list[HumanProfilePoint] = []
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"norm_pos", "speed_kmh", "brake", "gas"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            cols = ", ".join(sorted(missing))
            raise ValueError(f"human profile missing required column(s): {cols}")
        for line_no, row in enumerate(reader, start=2):
            try:
                raw_norm_pos = float(row["norm_pos"])
                speed_kmh = float(row["speed_kmh"])
                brake = float(row["brake"])
                gas = float(row["gas"])
                min_speed_kmh = float(row.get("min_speed_kmh") or speed_kmh)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"human profile line {line_no} has non-numeric data") from exc
            values = (raw_norm_pos, speed_kmh, brake, gas, min_speed_kmh)
            if not all(math.isfinite(v) for v in values):
                raise ValueError(f"human profile line {line_no} has non-finite data")
            if not 0.0 <= raw_norm_pos <= 1.0:
                raise ValueError(f"human profile line {line_no} norm_pos out of range 0..1")
            if speed_kmh < 0 or min_speed_kmh < 0:
                raise ValueError(f"human profile line {line_no} has negative speed")
            if not 0.0 <= brake <= 1.0 or not 0.0 <= gas <= 1.0:
                raise ValueError(f"human profile line {line_no} gas/brake out of range 0..1")
            norm_pos = 0.0 if raw_norm_pos == 1.0 else raw_norm_pos
            rows.append(
                HumanProfilePoint(
                    norm_pos=norm_pos,
                    speed_mps=speed_kmh / 3.6,
                    brake=brake,
                    gas=gas,
                    min_speed_mps=min_speed_kmh / 3.6,
                )
            )
    if len(rows) < 2:
        raise ValueError("human profile needs at least two rows")
    rows.sort(key=lambda p: p.norm_pos)
    for prev, cur in zip(rows, rows[1:], strict=False):
        if abs(cur.norm_pos - prev.norm_pos) < 1e-9:
            raise ValueError(f"human profile duplicate norm_pos: {cur.norm_pos:.6f}")
    return rows


def _cyclic_interpolate(
    points: list[HumanProfilePoint],
    norms: list[float],
    norm_pos: float,
    field: str,
) -> float:
    """Interpolate a profile field on the cyclic ``0..1`` normalized track domain."""
    target = norm_pos % 1.0
    idx = bisect_right(norms, target)
    if idx == 0:
        left = points[-1]
        right = points[0]
        left_norm = left.norm_pos - 1.0
        right_norm = right.norm_pos
    elif idx == len(points):
        left = points[-1]
        right = points[0]
        left_norm = left.norm_pos
        right_norm = right.norm_pos + 1.0
    else:
        left = points[idx - 1]
        right = points[idx]
        left_norm = left.norm_pos
        right_norm = right.norm_pos
    span = right_norm - left_norm
    if span <= 1e-12:
        return float(getattr(left, field))
    frac = (target - left_norm) / span
    left_value = float(getattr(left, field))
    right_value = float(getattr(right, field))
    return left_value + frac * (right_value - left_value)


def _line_normalized_positions(fast_line: list[tuple[float, float, float]]) -> list[float]:
    """Return each racing-line point's distance fraction around the cyclic lap."""
    if len(fast_line) < 2:
        raise ValueError("fast_line needs at least two points")
    plane = [_horizontal(p) for p in fast_line]
    cumulative = [0.0]
    total = 0.0
    for i in range(1, len(plane)):
        prev = plane[i - 1]
        cur = plane[i]
        total += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        cumulative.append(total)
    first = plane[0]
    last = plane[-1]
    total += math.hypot(first[0] - last[0], first[1] - last[1])
    if total <= 1e-9:
        raise ValueError("fast_line has zero cyclic length")
    return [0.0 if total - d <= 1e-9 else d / total for d in cumulative]


def human_profile_speed_profile(
    points: list[HumanProfilePoint],
    point_count: int,
    *,
    norm_positions: list[float] | None = None,
) -> list[float]:
    """Resample a human profile to one target speed per racing-line point."""
    if point_count <= 0:
        raise ValueError("point_count must be > 0")
    if len(points) < 2:
        raise ValueError("human profile needs at least two rows")
    if norm_positions is None:
        norm_positions = [i / point_count for i in range(point_count)]
    if len(norm_positions) != point_count:
        raise ValueError("norm_positions length must equal point_count")
    for pos in norm_positions:
        if not math.isfinite(pos) or not 0.0 <= pos < 1.0:
            raise ValueError("norm_positions must be finite fractions in [0, 1)")
    norms = [p.norm_pos for p in points]
    return [_cyclic_interpolate(points, norms, pos, "speed_mps") for pos in norm_positions]


def load_human_speed_profile(path: str | Path, point_count: int) -> list[float]:
    """Load and resample a human-lap CSV into a ``RacingDriver`` speed profile."""
    return human_profile_speed_profile(load_human_profile(path), point_count)


def load_human_speed_profile_for_line(
    path: str | Path,
    fast_line: list[tuple[float, float, float]],
) -> list[float]:
    """Load a human-lap CSV and align it by distance fraction to ``fast_line`` points."""
    profile = load_human_profile(path)
    return human_profile_speed_profile(
        profile,
        len(fast_line),
        norm_positions=_line_normalized_positions(fast_line),
    )


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


class RacingDriver:
    """Drive ``fast_line`` at racing dynamics from any starting state (pits, off-line, on-line).

    ``speed_profile`` is the per-point target speed (m/s) from :func:`load_speed_profile` (same
    length as ``fast_line``). The optimal profile is scaled by ``pace`` and capped at
    ``max_speed_kmh`` (pure-pursuit's stable steering envelope), then a backward pass at ``brake_g``
    bakes in the braking points. Steering defaults to a Stanley cross-track controller so racing
    pace does not aim through apexes the way look-ahead pure pursuit did.
    """

    @classmethod
    def from_human_profile(
        cls,
        fast_line: list[tuple[float, float, float]],
        profile_csv: str | Path,
        **kwargs,
    ) -> RacingDriver:
        """Construct from a normalized-position human-lap profile CSV."""
        profile = load_human_profile(profile_csv)
        kwargs.setdefault("pace", 1.0)
        kwargs.setdefault("max_speed_kmh", max(p.speed_mps for p in profile) * 3.6)
        kwargs.setdefault("min_speed_kmh", max(min(p.min_speed_mps for p in profile) * 3.6, 1.0))
        return cls(
            fast_line,
            human_profile_speed_profile(
                profile,
                len(fast_line),
                norm_positions=_line_normalized_positions(fast_line),
            ),
            **kwargs,
        )

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
        brake_band_mps: float = 0.5,
        brake_scale_mps: float = 4.0,
        throttle_scale_mps: float = 6.0,
        base_gas: float = 0.05,
        trail_release: float = 0.7,
        trail_min: float = 0.2,
        traction_lift: float = 0.6,
        steering_mode: str = "stanley",
        stanley_cross_track_gain: float = 0.75,
        stanley_heading_gain: float = 1.0,
        stanley_speed_softening_mps: float = 5.0,
        stanley_max_steer_rad: float = 0.65,
        stanley_max_cross_track_m: float = 10.0,
        rpm_up: float = 7000.0,
        rpm_dn: float = 4200.0,
        max_gear: int = 7,
        shift_cooldown_s: float = 0.25,
        out_gas: float = 0.6,
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
        if brake_g <= 0 or brake_scale_mps <= 0 or throttle_scale_mps <= 0:
            raise ValueError("brake_g, brake_scale_mps, throttle_scale_mps must be > 0")
        if steering_mode not in {"stanley", "pure_pursuit"}:
            raise ValueError("steering_mode must be 'stanley' or 'pure_pursuit'")

        self.pursuit = PurePursuit(
            fast_line,
            lookahead_m=lookahead_m,
            target_speed_kmh=max(max_speed_kmh, 1.0),
            min_corner_speed_kmh=max(min(min_speed_kmh, max_speed_kmh), 1.0),
            max_steer_curvature=max_steer_curvature,
            wheelbase_m=wheelbase_m,
        )
        self.stanley = StanleySteering(
            fast_line,
            cross_track_gain=stanley_cross_track_gain,
            heading_gain=stanley_heading_gain,
            speed_softening_mps=stanley_speed_softening_mps,
            max_steer_rad=stanley_max_steer_rad,
            max_cross_track_m=stanley_max_cross_track_m,
        )
        self.n = len(fast_line)
        self.steering_mode = steering_mode
        self.lookahead_m = lookahead_m
        self.lookahead_time_s = lookahead_time_s
        self.brake_band_mps = brake_band_mps
        self.brake_scale_mps = brake_scale_mps
        self.throttle_scale_mps = throttle_scale_mps
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
        seg = self.pursuit.segment_lengths
        n = self.n
        out = list(v)
        for _ in range(_BACKWARD_PASS_PASSES):
            for j in range(n):
                i = (n - 1 - j) % n
                nxt = (i + 1) % n
                ds = seg[i]
                if ds <= 1e-6:
                    continue
                cap = math.sqrt(out[nxt] * out[nxt] + 2.0 * a * ds)
                out[i] = min(out[i], cap)
        return out

    def target_speed_kmh(self, idx: int, speed_kmh: float) -> float:
        """Brake-feasible target (km/h) at ``idx`` with a speed-scaled look-ahead margin.

        ``min(profile[idx], profile[look_idx])`` intentionally caps the target when a slower
        corner lies ahead along the cyclic line (braking-point semantics).
        """
        v_cur = speed_kmh / 3.6
        look_idx = self.pursuit.advance_index(
            idx, max(self.lookahead_m, v_cur * self.lookahead_time_s)
        )
        return min(self.profile[idx], self.profile[look_idx]) * 3.6

    def _longitudinal(self, idx: int, speed_kmh: float, steer: float) -> tuple[float, float]:
        """Racing throttle/brake toward the brake-feasible profile (trail braking + traction)."""
        v_cur = speed_kmh / 3.6
        target = self.target_speed_kmh(idx, speed_kmh) / 3.6
        lat = min(abs(steer), 1.0)  # cornering load proxy (steer fraction, saturated)
        err = v_cur - target
        if err > self.brake_band_mps:
            brake = _clamp((err - self.brake_band_mps) / self.brake_scale_mps, 0.0, 1.0)
            # trail braking: bleed brake off as steering loads the front, but keep some mid-corner.
            brake *= max(self.trail_min, 1.0 - self.trail_release * lat)
            return 0.0, brake
        # Under/at target: throttle toward it, lifting as steering loads the car (anti-wheelspin).
        gas = _clamp((target - v_cur) / self.throttle_scale_mps + self.base_gas, 0.0, 1.0)
        gas *= max(0.0, 1.0 - self.traction_lift * lat)
        return gas, 0.0

    def _gear_pulse(self, rpm: float, gear: int, speed_kmh: float, now: float) -> tuple[bool, bool]:
        """One-frame shift: out of neutral, up past ``rpm_up`` while moving, down at ``rpm_dn``."""
        if now - self._last_shift_s <= self.shift_cooldown_s:
            return (False, False)
        # AC gear: 0=reverse, 1=neutral, 2=1st — upshift from R/N only.
        if gear <= 1:
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
        line_pt = self.pursuit.plane_position(idx)
        dist_to_line = math.hypot(line_pt[0] - car[0], line_pt[1] - car[1])
        if (
            self.phase == PHASE_OUT
            and dist_to_line < self.merge_distance_m
            and speed_kmh > self.merge_speed_kmh
        ):
            self.phase = PHASE_LAP

        if self.steering_mode == "stanley":
            steer = self.stanley.steer(position_xyz, look_dir_xyz, speed_kmh)
        else:
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
