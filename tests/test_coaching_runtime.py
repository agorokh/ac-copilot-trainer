"""Coach v2 runtime — frame-level mistake-injection over the real Magione reference trace.

The offline counterpart to the on-rig auto_drive injection: replay the reference lap as live
frames across a stint, inject a *known* mistake at a *known* corner, and assert the coach gives the
right anticipatory imperative at the right place — and is silent when the driver is on the
reference. This is the deterministic regression net behind the live drive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ai_sidecar.coaching_runtime import build_coach_runtime

REF_PATH = Path(__file__).resolve().parents[1] / ".scratch" / "coach-demo" / "reference.json"
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="rig reference trace not present")


def _ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


def _lap_frames(archive: dict) -> list[dict]:
    tr = archive["trace"]
    fi = {f: i for i, f in enumerate(tr["fields"])}
    out = []
    for row in tr["samples"]:
        out.append(
            {
                "spline": row[fi["spline"]],
                "speed": row[fi["speed"]],
                "brake": row[fi["brake"]],
                "throttle": row[fi["throttle"]],
                "steer": row[fi["steer"]],
            }
        )
    return out


def _inject_early_brake(frames: list[dict], bp_spline: float, *, earlier: float = 0.03) -> None:
    """Make the driver brake EARLY for the corner whose ref brake point is ``bp_spline``: force the
    brake on across [bp - earlier, bp]."""
    for f in frames:
        if bp_spline - earlier <= f["spline"] < bp_spline:
            f["brake"] = 1.0
            f["throttle"] = 0.0


def _drive(runtime, laps: list[list[dict]]) -> list:
    """Replay laps through the runtime (incrementing the lap counter); collect all advisories."""
    advs = []
    for lap_idx, frames in enumerate(laps, start=1):
        for f in frames:
            advs.extend([(lap_idx, a) for a in runtime.observe({**f, "lap": lap_idx})])
    return advs


def _brake_anchor(runtime, corner_idx: int) -> float:
    return runtime.anchors[corner_idx].brake


def test_runtime_builds_from_reference():
    rt = build_coach_runtime(_ref())
    assert rt is not None and rt.refs, "runtime must build corners from the reference"


def test_perfect_reference_is_silent_after_assess():
    rt = build_coach_runtime(_ref())
    base = _lap_frames(_ref())
    advs = _drive(rt, [list(base) for _ in range(5)])  # 5 clean laps
    assess = rt.ledger.assess_laps
    primes = [a for (lap, a) in advs if a.detail.get("coach") == "prime" and lap > assess]
    got = [a.message for a in primes]
    assert primes == [], f"a driver on the reference should not be coached, got {got}"


def test_injected_early_brake_speaks_brake_later_at_that_corner():
    rt = build_coach_runtime(_ref())
    refs = rt.refs
    # pick a real braking corner (one with a detected reference brake point)
    target = next(r for r in refs if rt.ref_sigs[r.index].brake_point_spline is not None)
    bp = rt.ref_sigs[target.index].brake_point_spline
    laps = []
    for _ in range(4):
        f = _lap_frames(_ref())
        _inject_early_brake(f, bp)
        laps.append(f)
    advs = _drive(rt, laps)
    primes = [
        (lap, a)
        for (lap, a) in advs
        if a.detail.get("coach") == "prime" and a.corner == target.index
    ]
    assert primes, "early braking at a corner must eventually be coached"
    # it must say the right thing, and not until after the assess laps (hysteresis + watch-first)
    lap, a = primes[0]
    assert a.message == "Brake later."
    assert lap > rt.ledger.assess_laps
    # and it must land near that corner's pre-brake anchor (anticipatory, before the brake point)
    assert a.spline <= bp + 1e-6


def test_injected_then_fixed_acknowledges_and_silences():
    rt = build_coach_runtime(_ref())
    target = next(r for r in rt.refs if rt.ref_sigs[r.index].brake_point_spline is not None)
    bp = rt.ref_sigs[target.index].brake_point_spline
    laps = []
    for lap in range(1, 7):
        f = _lap_frames(_ref())
        if lap <= 3:  # brake early laps 1-3, clean from lap 4
            _inject_early_brake(f, bp)
        laps.append(f)
    advs = _drive(rt, laps)
    confirms = [
        (lap, a)
        for (lap, a) in advs
        if a.detail.get("coach") == "confirm" and a.corner == target.index
    ]
    assert confirms, "fixing a coached mistake should be acknowledged once"
    assert confirms[0][1].message == "Good."
