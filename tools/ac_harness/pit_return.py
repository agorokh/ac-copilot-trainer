"""Bounded natural pit navigation for the canonical external driver (#956).

This route is navigation, never proof of arrival or setup-write authority. Only
fresh native pit packets and unchanged native identity can establish arrival.
No teleport, recovery, setup mutation or native-AI takeover is used here.
"""

from __future__ import annotations

import asyncio
import math
import os
import threading
from dataclasses import dataclass

from tools.ac_harness.ai_line import PurePursuit
from tools.ac_harness.lap_driver import DriveFrame

MAX_ROUTE_OFFSET_M = 8.0


class PitReturnStop(threading.Event):
    """Keep abort distinct from the successful lap observer's return request."""

    def __init__(self) -> None:
        super().__init__()
        self.return_requested = threading.Event()
        self.pit_box: PitBox | None = None


async def observe_until_drive_ends(observer, drive_task):
    """Do not wait a full lap deadline when navigation initialization already failed."""
    observer_task = asyncio.create_task(observer)
    try:
        done, _ = await asyncio.wait(
            (observer_task, drive_task), return_when=asyncio.FIRST_COMPLETED
        )
        if observer_task in done:
            return await observer_task
        # A natural-return drive can only finish cleanly after its observer has
        # requested return. An early exit therefore cannot establish a lap window.
        driven = await drive_task  # Preserve an actual driver exception when present.
        reason = getattr(driven, "reason", "")
        detail = f": {reason}" if reason else ""
        raise ValueError(f"drive ended before the requested lap observation completed{detail}")
    finally:
        if not observer_task.done():
            observer_task.cancel()
        await asyncio.gather(observer_task, return_exceptions=True)


def vector(value: object) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("native pit geometry requires three coordinates")
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in value):
        raise ValueError("native pit geometry must be finite")
    return tuple(float(v) for v in value)


def distance(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def nearest(points: list, position: tuple) -> int:
    return min(range(len(points)), key=lambda i: distance(points[i], position))


@dataclass(frozen=True)
class PitBox:
    session_id: str
    position: tuple[float, float, float]
    look: tuple[float, float, float]

    @classmethod
    def from_native(cls, value: object, car_id: str, track_id: str, layout: str) -> PitBox:
        if not isinstance(value, dict) or value.get("offline") is not True:
            raise ValueError("offline native pit geometry unavailable")
        if (value.get("car_id"), value.get("track_id"), value.get("layout_id")) != (
            car_id,
            track_id,
            layout,
        ):
            raise ValueError("native pit geometry combo mismatch")
        sid = value.get("session_id")
        if not isinstance(sid, str) or not sid or len(sid) > 64:
            raise ValueError("native pit geometry session unavailable")
        position, look = vector(value.get("position")), vector(value.get("look"))
        norm = math.hypot(look[0], look[2])
        if not 0.9 <= norm <= 1.1:
            raise ValueError("native pit heading is not a unit direction")
        return cls(sid, position, (look[0] / norm, 0.0, look[2] / norm))


async def read_pit_box(url: str, car_id: str, track_id: str, layout: str) -> PitBox:
    """Read the actual car's assigned pit transform through the existing config bridge."""
    from tools.ai_sidecar.harness_client import HarnessClient

    async with asyncio.timeout(8):
        async with HarnessClient(
            url,
            token=os.environ.get("AC_COPILOT_SIDECAR_TOKEN"),
            client_id="ac-harness-pit-geometry",
        ) as client:
            if not await client.hello():
                raise ValueError("pit geometry hello unavailable")
            await client.send({"v": 1, "type": "config.get", "key": "harnessPitBox"})
            frame = await client.wait_for(
                lambda f: f.get("type") == "config.value" and f.get("key") == "harnessPitBox",
                timeout=5,
            )
            return PitBox.from_native(
                frame.get("value") if frame else None, car_id, track_id, layout
            )


def build_route(fast: list, pit: list, position: tuple, box: PitBox) -> list:
    """Follow authored forward geometry, then smoothly offset into the assigned box.

    Pit splines are open. Never close them into a loop or steer across the track
    to an arbitrary nearest point. Reject a missing connection or incompatible box.
    """
    fast, pit = [vector(p) for p in fast], [vector(p) for p in pit]
    position = vector(position)
    if len(fast) < 20 or len(pit) < 20:
        raise ValueError("authored pit/racing route too short")
    if any(distance(a, b) > 5 for a, b in zip(pit, pit[1:], strict=False)):
        raise ValueError("authored pit route is discontinuous")
    start, entry, end = nearest(fast, position), nearest(fast, pit[0]), nearest(pit, box.position)
    if distance(fast[start], position) > MAX_ROUTE_OFFSET_M or distance(fast[entry], pit[0]) > 2:
        raise ValueError("pit entry is not connected to current racing route")
    if end < 40 or end >= len(pit) - 5 or distance(pit[end], box.position) > 15:
        raise ValueError("assigned box is not beside the interior of the pit route")
    dx, dz = pit[end][0] - pit[end - 4][0], pit[end][2] - pit[end - 4][2]
    norm = math.hypot(dx, dz)
    if norm < 0.1 or (dx * box.look[0] + dz * box.look[2]) / norm < 0.9:
        raise ValueError("assigned box heading conflicts with authored pit direction")
    if abs(pit[end][1] - box.position[1]) > 2:
        raise ValueError("assigned box elevation conflicts with pit route")
    route = []
    index = start
    for _ in range(len(fast)):
        route.append(fast[index])
        if index == entry:
            break
        index = (index + 1) % len(fast)
    blend = end
    while blend > 0 and distance(pit[blend], pit[end]) < 45:
        blend -= 1
    if end - blend < 20:
        raise ValueError("insufficient authored approach to assigned box")
    offset = tuple(box.position[j] - pit[end][j] for j in range(3))
    for i, point in enumerate(pit[: end + 1]):
        fraction = max(0.0, min(1.0, (i - blend) / (end - blend)))
        smooth = fraction * fraction * (3 - 2 * fraction)
        moved = tuple(point[j] + offset[j] * smooth for j in range(3))
        if not route or distance(route[-1], moved) > 0.05:
            route.append(moved)
    if any(distance(a, b) > 5 for a, b in zip(route, route[1:], strict=False)):
        raise ValueError("natural pit route contains a gap")
    # Even ideal motion at the speed cap cannot finish a longer route within
    # the return deadline. Reserve 30s for braking, the box approach and proof.
    route_length = sum(distance(a, b) for a, b in zip(route, route[1:], strict=False))
    if route_length > (60 / 3.6) * 210:
        raise ValueError("authored pit route cannot fit the bounded return budget")
    return route


class PitReturnDriver:
    """Open forward path follower with bounded approach, progress and stop time.

    A geometric terminal point only requests braking. It never means native pit
    arrival; the caller independently confirms live pit/packet/session evidence.
    """

    def __init__(self, route: list, *, started_at: float) -> None:
        self.route = route
        self.pursuit = PurePursuit(route)
        self.started_at = started_at
        self.index = 0
        self.last_progress = started_at
        self._shift_at = -math.inf
        self.stationary_since: float | None = None
        self.remaining = [0.0] * len(route)
        for i in range(len(route) - 2, -1, -1):
            self.remaining[i] = self.remaining[i + 1] + distance(route[i], route[i + 1])

    def step(
        self, position: tuple, look: tuple, speed: float, rpm: float, gear: int, now: float
    ) -> DriveFrame:
        position, look = vector(position), vector(look)
        if (
            type(speed) not in (float, int)
            or not math.isfinite(speed)
            or speed < -1
            or not math.isfinite(now)
            or now - self.started_at > 240
        ):
            raise ValueError("natural pit return exceeded motion/time bounds")
        previous = self.index
        search_end = min(len(self.route), self.index + 20)
        self.index = min(
            range(self.index, search_end), key=lambda i: distance(self.route[i], position)
        )
        if self.index > previous:
            self.last_progress = now
        if distance(self.route[self.index], position) > MAX_ROUTE_OFFSET_M:
            raise ValueError("natural pit return left authored corridor")
        if distance(position, self.route[-1]) <= 1.5 and abs(speed) <= 0.1:
            if self.stationary_since is None:
                self.stationary_since = now
            elif now - self.stationary_since > 5:
                raise ValueError("native pit arrival not confirmed at geometric stop")
        else:
            self.stationary_since = None
        if now - self.last_progress > 12 and distance(position, self.route[-1]) > 1:
            raise ValueError("natural pit return made no forward progress")
        aim = self.index
        horizon = min(10.0, max(3.0, speed / 6.0))
        while (
            aim + 1 < len(self.route) and self.remaining[self.index] - self.remaining[aim] < horizon
        ):
            aim += 1
        target = self.route[aim]
        dx, dz = target[0] - position[0], target[2] - position[2]
        heading_norm = math.hypot(look[0], look[2])
        if heading_norm < 0.9:
            raise ValueError("natural pit heading unavailable")
        # Same AC x/z and right-steering convention as the canonical pursuit controller.
        forward = (look[0] * dx + look[2] * dz) / heading_norm
        lateral = (look[0] * dz - look[2] * dx) / heading_norm
        steer = max(-0.65, min(0.65, self.pursuit._steer_from_offsets(forward, lateral)))
        remaining = self.remaining[self.index]
        limit = min(60.0, math.sqrt(max(0.0, 2 * 1.2 * (remaining - 0.8))) * 3.6)
        if remaining < 15:
            limit = min(limit, 12.0)
        if distance(position, self.route[-1]) < 1.2:
            limit = 0.0
        error = limit - speed
        gas = min(0.3, max(0.0, error / 20.0))
        brake = min(0.7, max(0.0, -error / 12.0))
        if limit == 0:
            gas, brake = 0.0, 0.6
        up = down = False
        if now - self._shift_at > 0.35:
            up = gear < 2 or (rpm > 7000 and gear < 4 and speed > 20)
            down = gear > 2 and (rpm < 4200 or speed < 25)
            if up or down:
                self._shift_at = now
        return DriveFrame(gas, brake, steer, up, down, "PIT_RETURN", False, False)


class PitArrivalProof:
    """Require dual-advancing live native packets; geometric proximity is insufficient."""

    def __init__(self) -> None:
        self.samples = 0
        self.previous: tuple | None = None
        self.last_at = -math.inf
        self.completed_laps: int | None = None

    def observe(
        self,
        graphics: object,
        physics_packet: int | None,
        speed: float,
        box_distance: float,
        now: float,
    ) -> bool:
        if graphics is None or not graphics.is_live or type(physics_packet) is not int:
            raise ValueError("fresh native pit packets unavailable")
        laps = graphics.completed_laps
        if type(laps) is not int or (
            self.completed_laps is not None and laps < self.completed_laps
        ):
            raise ValueError("native lap count changed backwards during return")
        self.completed_laps = laps
        pair = (graphics.packet_id, physics_packet)
        if self.previous is not None and (
            pair[0] == self.previous[0] or pair[1] == self.previous[1]
        ):
            return False
        if now - self.last_at < 0.15:
            return False
        self.previous, self.last_at = pair, now
        if graphics.is_in_pit and abs(speed) <= 0.1 and box_distance <= 1.5:
            self.samples += 1
        else:
            self.samples = 0
        return self.samples >= 3
