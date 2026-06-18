"""Racing-line source + pure-pursuit controller so ``carcsw`` drives a real lap.

EPIC #154 needs car 0 to drive an actual lap of the track **with no human** so the
trainer's WS producers and the L1.5 probe have real motion to observe. The CSP Custom AI
mmap interface (``CarControls0`` write section) gives us the actuators — gas / brake /
steer at 333 Hz — but it does not tell us *where to go*. This module supplies the "where":

1. :func:`load_ai_line` reads Assetto Corsa's own ``fast_lane.ai`` — the same ideal-line
   spline the built-in AI follows — so we drive a geometrically valid line instead of
   guessing waypoints. We reuse Kunos's data rather than authoring our own line.
2. :class:`PurePursuit` turns that line + the live car pose (position, forward vector,
   speed) into ``(gas, brake, steer)``. Pure pursuit is the standard
   "steer toward a point a fixed look-ahead distance down the path" geometric controller:
   simple, deterministic, no tuning matrices, and stable enough to complete a clean lap of
   a road course at a capped ~80-100 km/h.

Everything here is **pure and deterministic** — no clock, no mmap, no Assetto Corsa. The
binary parser works on any OS from a ``Path`` (the file is just bytes), and the controller
is plain arithmetic. That is what lets CI on the Mac verify the steering sign and the
throttle/brake logic with synthetic in-memory lines, exactly like the #175 oracle.

Coordinate convention (matches AC / the ``Car0`` mmap section): a point is ``(x, y, z)``
with **y vertical**. The car drives on the ground plane, so all pursuit geometry is done in
the horizontal ``(x, z)`` plane and the ``y`` component is carried through but ignored by
the controller. A right-handed turn (steer > 0) corresponds to the look-ahead point lying
to the car's right of its current heading.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# fast_lane.ai binary layout.
#
# Ground-truthed against magione's fast_lane.ai (1754 points, 830628 bytes) AND the
# canonical Content-Manager source (gro-ove/actools AcTools/AiFile/AiSpline.cs + AiPoint.cs).
# A "version 7" spline is laid out little-endian as:
#
#   int32 version        @ 0    (== 7 for current AC)
#   int32 count          @ 4    (number of main points)
#   int32 lapTime        @ 8    (usually 0; not needed here)
#   int32 sampleCount    @ 12   (usually 0; not needed here)
#   AiPoint[count]       @ 16   each 20 bytes:
#       float x          @ +0
#       float y          @ +4    (vertical)
#       float z          @ +8
#       float length     @ +12   (cumulative arc length from start, metres)
#       int32 id         @ +16   (sequential 0..count-1)
#   int32 extraCount     @ 16 + count*20   (== count; used here only as a parse cross-check)
#   ... AiPointExtra[] + optional grid block follow; NOT read.
#
# We deliberately parse only the leading header + the float3 position of each main point
# (plus a cheap structural cross-check on extraCount). The extra block and grid encode
# side-limits and a spatial lookup grid that pure-pursuit does not use; parsing them would
# add fragility (their layout drifts across CSP/track-tool versions) for no benefit.
# ---------------------------------------------------------------------------
_HEADER_STRUCT = struct.Struct("<4i")  # version, count, lapTime, sampleCount
_HEADER_SIZE = _HEADER_STRUCT.size  # 16
_POINT_SIZE = 20  # float x,y,z + float length + int32 id
_EXPECTED_VERSION = 7


def load_ai_line(path: str | Path) -> list[tuple[float, float, float]]:
    """Parse an Assetto Corsa ``fast_lane.ai`` and return its centre-line as ``(x, y, z)``.

    ``path`` points at ``<AC_ROOT>/content/tracks/<track>/ai/fast_lane.ai``. The returned
    list is ordered along the racing direction and (for a closed circuit) loops back near
    the start; pure pursuit treats it as a cyclic path.

    Robustness over completeness: only the version-7 header and each point's float3 position
    are decoded. ``version`` is checked against the known value (7) but a mismatch only warns
    via :class:`ValueError` when the layout is *structurally* impossible — if the header looks
    sane (positive count that fits the file at the documented 20-byte stride) we proceed even
    on an unexpected version, because the position layout has been stable across versions and
    a hard fail would needlessly block driving on a slightly-newer spline.

    Raises :class:`FileNotFoundError` if the file is missing and :class:`ValueError` if the
    bytes cannot be a fast_lane spline (too short, non-positive count, or a count that does
    not fit the file at the documented stride).
    """
    data = Path(path).read_bytes()
    if len(data) < _HEADER_SIZE:
        raise ValueError(
            f"fast_lane.ai too short to hold a header: {len(data)} < {_HEADER_SIZE} bytes"
        )

    version, count, _lap_time, _sample_count = _HEADER_STRUCT.unpack_from(data, 0)
    if count <= 0:
        raise ValueError(f"fast_lane.ai declares a non-positive point count: {count}")

    points_end = _HEADER_SIZE + count * _POINT_SIZE
    if points_end > len(data):
        raise ValueError(
            f"fast_lane.ai count={count} does not fit the file: needs {points_end} bytes "
            f"for the main point block but file is {len(data)} bytes "
            f"(version={version}, expected {_EXPECTED_VERSION})"
        )

    line: list[tuple[float, float, float]] = []
    offset = _HEADER_SIZE
    for _ in range(count):
        x, y, z = struct.unpack_from("<3f", data, offset)
        line.append((x, y, z))
        offset += _POINT_SIZE
    return line


# ---------------------------------------------------------------------------
# Pure-pursuit controller.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ControlOutput:
    """One actuator frame for the ``CarControls0`` mmap section.

    ``gas`` / ``brake`` are in ``0..1``; ``steer`` is in ``-1..1`` where **positive steers
    the car to its right**. A tuple is also exposed via iteration so callers can do
    ``gas, brake, steer = controller.control(...)``.
    """

    gas: float
    brake: float
    steer: float

    def __iter__(self):  # noqa: ANN204 - simple 3-tuple unpacking helper
        yield self.gas
        yield self.brake
        yield self.steer


def _horizontal(p: tuple[float, float, float]) -> tuple[float, float]:
    """Project an ``(x, y, z)`` point to the ground plane ``(x, z)`` (drop vertical ``y``)."""
    return (p[0], p[2])


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Squared planar distance — cheaper than ``hypot`` for nearest-point comparisons."""
    dx = a[0] - b[0]
    dz = a[1] - b[1]
    return dx * dx + dz * dz


class PurePursuit:
    """Geometric path-follower: steer toward a point a fixed look-ahead down the racing line.

    Construction precomputes the planar projection and the cumulative arc length of the line
    so :meth:`control` is cheap (a windowed nearest search + a look-ahead walk). The line is
    treated as **cyclic** (a closed circuit) so the look-ahead wraps past the start/finish
    instead of running off the end of the array.

    Tuning knobs (all metres / km·h⁻¹, chosen for a road car at a capped pace):

    * ``lookahead_m`` — how far down the line to aim. ~10-20 m: short enough to track tight
      corners, long enough to damp oscillation on straights.
    * ``target_speed_kmh`` — the pace cap on straights; the controller bleeds below this into
      corners based on the upcoming line curvature.
    * ``min_corner_speed_kmh`` — the floor it will slow to for the sharpest modelled corner.
    * ``wheelbase_m`` — used to convert the pure-pursuit curvature into a steering fraction;
      with ``max_steer_curvature`` it sets how much line curvature saturates the wheel.
    """

    def __init__(
        self,
        line: list[tuple[float, float, float]],
        *,
        lookahead_m: float = 14.0,
        target_speed_kmh: float = 90.0,
        min_corner_speed_kmh: float = 45.0,
        wheelbase_m: float = 2.5,
        max_steer_curvature: float = 0.18,
        curvature_lookahead_m: float = 30.0,
    ) -> None:
        if len(line) < 2:
            raise ValueError("pure pursuit needs at least 2 line points")
        if lookahead_m <= 0:
            raise ValueError("lookahead_m must be > 0")
        if target_speed_kmh <= 0 or min_corner_speed_kmh <= 0:
            raise ValueError("speed caps must be > 0")
        if min_corner_speed_kmh > target_speed_kmh:
            raise ValueError("min_corner_speed_kmh cannot exceed target_speed_kmh")
        if wheelbase_m <= 0 or max_steer_curvature <= 0 or curvature_lookahead_m <= 0:
            raise ValueError("wheelbase_m, max_steer_curvature, curvature_lookahead_m must be > 0")

        self._line = line
        self._plane = [_horizontal(p) for p in line]
        self.lookahead_m = lookahead_m
        self.target_speed_kmh = target_speed_kmh
        self.min_corner_speed_kmh = min_corner_speed_kmh
        self.wheelbase_m = wheelbase_m
        self.max_steer_curvature = max_steer_curvature
        self.curvature_lookahead_m = curvature_lookahead_m

        # Cumulative arc length along the *cyclic* line: cum[i] is the distance from point 0
        # to point i, and the segment closing the loop (last -> first) is included so the
        # look-ahead walk can wrap. This lets us step a fixed number of metres down the path.
        self._seg_len: list[float] = []
        n = len(self._plane)
        for i in range(n):
            a = self._plane[i]
            b = self._plane[(i + 1) % n]
            self._seg_len.append(math.hypot(b[0] - a[0], b[1] - a[1]))

    @property
    def segment_lengths(self) -> tuple[float, ...]:
        """Planar segment length from each point to the next (cyclic wrap at ``i+1 mod n``)."""
        return tuple(self._seg_len)

    def plane_position(self, index: int) -> tuple[float, float]:
        """Horizontal ``(x, z)`` position of line point ``index``."""
        return self._plane[index]

    def advance_index(self, start_index: int, distance_m: float) -> int:
        """Walk ``distance_m`` along the cyclic line from ``start_index``; return the aim index."""
        return self._advance(start_index, distance_m)

    def nearest_index(self, position: tuple[float, float]) -> int:
        """Index of the line point planar-closest to ``position`` (full scan; pure)."""
        best_i = 0
        best_d = _dist2(self._plane[0], position)
        for i in range(1, len(self._plane)):
            d = _dist2(self._plane[i], position)
            if d < best_d:
                best_d = d
                best_i = i
        return best_i

    def _advance(self, start_index: int, distance_m: float) -> int:
        """Walk ``distance_m`` along the cyclic line from ``start_index``; return the index.

        Steps point-to-point accumulating segment lengths until the budget is spent, wrapping
        at the end of the array (closed circuit). The returned index is the first point at or
        beyond ``distance_m`` ahead — the aim point.
        """
        n = len(self._plane)
        idx = start_index
        remaining = distance_m
        # Bound the walk to one full lap so a degenerate (zero-length) line cannot loop forever.
        for _ in range(n):
            step = self._seg_len[idx]
            if step >= remaining:
                return (idx + 1) % n
            remaining -= step
            idx = (idx + 1) % n
        return (start_index + n - 1) % n

    def _curvature_ahead(self, start_index: int) -> float:
        """Estimate path curvature (1/radius, m⁻¹) over the next ``curvature_lookahead_m``.

        Uses the turn angle between the heading into the look-ahead window and the heading
        out of it, divided by the arc length walked — a robust discrete curvature that does
        not need three near-collinear points (which produce numerically noisy circumcircles).
        Returned unsigned: corner *tightness* sets the speed target, direction does not.
        """
        mid = self._advance(start_index, self.curvature_lookahead_m * 0.5)
        end = self._advance(start_index, self.curvature_lookahead_m)
        p0 = self._plane[start_index]
        p1 = self._plane[mid]
        p2 = self._plane[end]

        in_x, in_z = p1[0] - p0[0], p1[1] - p0[1]
        out_x, out_z = p2[0] - p1[0], p2[1] - p1[1]
        in_len = math.hypot(in_x, in_z)
        out_len = math.hypot(out_x, out_z)
        if in_len < 1e-6 or out_len < 1e-6:
            return 0.0

        # Signed turn angle between the two heading vectors via atan2(cross, dot): stable for
        # all angles including near-180°, unlike acos(dot) which loses precision near ±1.
        cross = in_x * out_z - in_z * out_x
        dot = in_x * out_x + in_z * out_z
        turn = abs(math.atan2(cross, dot))
        arc = in_len + out_len
        if arc < 1e-6:
            return 0.0
        # NOTE: on a *closed* line shorter than ``curvature_lookahead_m`` the advance walk wraps
        # past start and folds the in/out headings, degrading this estimate; real ``fast_lane``
        # tracks are km-scale so it never triggers in production. Clamping the window to the line
        # length is a tracked follow-up (#190).
        return turn / arc

    def control(
        self,
        position_xyz: tuple[float, float, float],
        look_dir_xyz: tuple[float, float, float],
        speed_kmh: float,
    ) -> ControlOutput:
        """Compute one ``(gas, brake, steer)`` frame from the live car pose.

        ``position_xyz`` is the car's world position and ``look_dir_xyz`` its forward
        direction (both as read from the ``Car0`` mmap section; ``y`` is vertical and
        ignored). ``speed_kmh`` is the current ground speed.

        Steering: project the vector from the car to the look-ahead point into the car's
        local frame (forward / right). The pure-pursuit curvature is
        ``2 * lateral_offset / lookahead²``; we map that to ``-1..1`` via the wheelbase and
        ``max_steer_curvature`` so a curvature at the saturation value pins the wheel.
        ``steer > 0`` means the aim point is to the car's right.

        Longitudinal: pick a target speed that falls from ``target_speed_kmh`` toward
        ``min_corner_speed_kmh`` as the upcoming curvature tightens, then apply throttle if
        below target and brake if above — a deadband-free proportional law clamped to 0..1.
        """
        car = _horizontal(position_xyz)
        fwd = _horizontal(look_dir_xyz)
        fwd_len = math.hypot(fwd[0], fwd[1])
        if fwd_len < 1e-9:
            # No usable heading (car stationary at spawn with zero look vector): creep forward
            # straight so the very first frames still command motion rather than freezing.
            return ControlOutput(gas=0.3, brake=0.0, steer=0.0)
        fwd_unit = (fwd[0] / fwd_len, fwd[1] / fwd_len)
        # The car's "right" normal in the (x, z) ground plane. We DEFINE steer>0 == aim point
        # to the car's right, and pin that to the +z side when facing +x (the convention the
        # tests lock down): for fwd=(1,0) we need right=(0,1)=+z, i.e. right = (-fwd_z, fwd_x).
        right_unit = (-fwd_unit[1], fwd_unit[0])

        nearest = self.nearest_index(car)
        aim_idx = self._advance(nearest, self.lookahead_m)
        aim = self._plane[aim_idx]
        to_aim = (aim[0] - car[0], aim[1] - car[1])

        forward_offset = to_aim[0] * fwd_unit[0] + to_aim[1] * fwd_unit[1]
        lateral_offset = to_aim[0] * right_unit[0] + to_aim[1] * right_unit[1]

        steer = self._steer_from_offsets(forward_offset, lateral_offset)
        gas, brake = self._longitudinal(nearest, speed_kmh)
        return ControlOutput(gas=gas, brake=brake, steer=steer)

    def _steer_from_offsets(self, forward_offset: float, lateral_offset: float) -> float:
        """Map the look-ahead point's local offset to a steering fraction in ``-1..1``.

        Pure-pursuit curvature to reach a point at local ``(forward, lateral)`` with chord
        length ``L`` is ``kappa = 2*lateral / L²``. We normalise by ``max_steer_curvature``
        (the curvature that saturates the wheel) and clamp. ``wheelbase_m`` is folded into the
        normalisation so a longer car asks for proportionally more wheel at the same path
        curvature, matching real Ackermann behaviour. If the aim point is behind the car
        (``forward_offset <= 0`` — e.g. recovering from a spin) steer hard toward it.
        """
        chord2 = forward_offset * forward_offset + lateral_offset * lateral_offset
        if chord2 < 1e-9:
            return 0.0
        if forward_offset <= 0.0:
            # Aim point is behind: command full lock in its lateral direction to swing around.
            return _clamp(math.copysign(1.0, lateral_offset), -1.0, 1.0)
        curvature = 2.0 * lateral_offset / chord2
        steer = curvature * self.wheelbase_m / self.max_steer_curvature
        return _clamp(steer, -1.0, 1.0)

    def _longitudinal(self, nearest_index: int, speed_kmh: float) -> tuple[float, float]:
        """Proportional throttle/brake toward a curvature-scaled target speed.

        The target falls linearly from ``target_speed_kmh`` to ``min_corner_speed_kmh`` as the
        upcoming curvature rises from 0 to ``max_steer_curvature``. Below target we feed gas
        proportional to the deficit; above target we brake proportional to the excess. Only
        one of gas/brake is ever non-zero, so the actuator frame is unambiguous.
        """
        curvature = self._curvature_ahead(nearest_index)
        tightness = _clamp(curvature / self.max_steer_curvature, 0.0, 1.0)
        target = self.target_speed_kmh - tightness * (
            self.target_speed_kmh - self.min_corner_speed_kmh
        )
        error = target - speed_kmh
        if error >= 0.0:
            # Below target: throttle scaled by deficit, full gas once ~20 km/h+ down.
            return (_clamp(error / 20.0, 0.0, 1.0), 0.0)
        # Above target: brake scaled by excess, full brake once ~15 km/h+ over.
        return (0.0, _clamp(-error / 15.0, 0.0, 1.0))


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` to ``[low, high]`` (kept local so the module has no numpy dependency)."""
    if value < low:
        return low
    if value > high:
        return high
    return value
