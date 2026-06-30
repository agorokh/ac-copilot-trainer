"""Coach v2 END-TO-END deterministic harness (council P0 — the gate every other criterion is
measured against).

Drives the REAL ``CoachRuntime.observe()`` with the real Magione reference trace, injecting a KNOWN
driver error at a KNOWN corner, across a multi-lap stint, and asserts the RIGHT phrase at the RIGHT
place with the RIGHT pacing — the full scenario matrix the ~1-lap autonomous driver cannot cover.

No clock, no sleeps, no I/O: array iteration over a frozen trace → <100 ms, zero flakiness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.ai_sidecar.coaching_runtime import build_coach_runtime

REF_PATH = Path(__file__).resolve().parents[1] / ".scratch" / "coach-demo" / "reference.json"
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="rig reference trace not present")


# --- fixtures / frame plumbing --------------------------------------------------------------------
def _archive() -> dict:
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


def _lap_frames(archive: dict) -> list[dict]:
    tr = archive["trace"]
    fi = {f: i for i, f in enumerate(tr["fields"])}
    keys = ("spline", "speed", "brake", "throttle", "steer")
    return [{k: row[fi[k]] for k in keys if k in fi} for row in tr["samples"]]


@dataclass
class Cue:
    lap: int
    spline: float
    kind: str
    phrase: str
    register: str
    corner: int
    coach: str


@dataclass
class CornerInfo:
    """Everything an injector needs about one corner: brake/throttle points + the window."""

    brake_point_spline: float | None
    throttle_on_spline: float | None
    apex_spline: float
    spline_lo: float
    spline_hi: float


class CoachSim:
    """A built CoachRuntime + deterministic multi-lap replay with explicit pacing thresholds."""

    def __init__(self, *, assess=1, hysteresis=1, budget=4):
        self.rt = build_coach_runtime(_archive())
        assert self.rt is not None
        self.rt.ledger.assess_laps = assess
        self.rt.ledger.hysteresis = hysteresis
        self.rt.ledger.lap_budget = budget
        self.rt.ledger.begin_lap(1)
        self.rt.refs_by_index = {r.index: r for r in self.rt.refs}

    def corner(self, t_number: int) -> tuple[int, CornerInfo]:
        """Return (index, CornerInfo) for a 1-based turn number."""
        idx = t_number - 1
        sig, geom = self.rt.ref_sigs[idx], self.rt.refs_by_index[idx]
        return idx, CornerInfo(
            brake_point_spline=sig.brake_point_spline,
            throttle_on_spline=sig.throttle_on_spline,
            apex_spline=geom.apex_spline,
            spline_lo=geom.spline_lo,
            spline_hi=geom.spline_hi,
        )

    def drive(self, laps: list[list[dict]]) -> list[Cue]:
        out: list[Cue] = []
        for lap_i, frames in enumerate(laps, start=1):
            for f in frames:
                for a in self.rt.observe({**f, "lap": lap_i}):
                    out.append(
                        Cue(
                            lap_i,
                            a.spline,
                            a.kind,
                            a.message,
                            a.register,
                            a.corner,
                            a.detail.get("coach", ""),
                        )
                    )
        return out


# --- perturbation engine (inject a known error at a known corner) ---------------------------------
def early_brake(frames, ref_sig, *, amount=0.02):
    bp = ref_sig.brake_point_spline
    for f in frames:
        if bp is not None and bp - amount <= f["spline"] < bp:
            f["brake"], f["throttle"] = 1.0, 0.0


def late_brake(frames, ref_sig, *, amount=0.015):
    bp = ref_sig.brake_point_spline
    for f in frames:
        if bp is not None and bp <= f["spline"] < bp + amount:
            f["brake"] = 0.0  # suppress the early braking → onset lands later


def no_trail(frames, ref_sig):
    for f in frames:
        if ref_sig.spline_lo <= f["spline"] <= ref_sig.apex_spline and abs(f["steer"]) > 0.1:
            f["brake"] = 0.0  # brake released the moment any steering is in → no trail overlap


def slow_apex(frames, ref_sig, *, kmh=10.0):
    lo, hi = ref_sig.spline_lo, ref_sig.spline_hi
    for f in frames:
        if lo <= f["spline"] <= hi:
            f["speed"] = max(5.0, f["speed"] - kmh)


def late_throttle(frames, ref_sig, *, amount=0.02):
    apex, hi = ref_sig.apex_spline, ref_sig.spline_hi
    for f in frames:
        if apex < f["spline"] <= min(hi, apex + amount):
            f["throttle"] = 0.0  # delay throttle re-application past the apex


def gross_late_brake(frames, ref_sig, *, past=0.015):
    bp = ref_sig.brake_point_spline
    for f in frames:
        if bp is not None and bp <= f["spline"] <= bp + past:
            f["brake"], f["throttle"] = 0.0, 1.0  # blow past the brake point on the gas → SAVE


def at_grip_limit(frames, info, *, grip=0.97):
    """Stamp a high grip-utilisation signal across the corner — the car is at the lateral limit."""
    for f in frames:
        if info.spline_lo <= f["spline"] <= info.spline_hi:
            f["grip"] = grip


def _laps(sim: CoachSim, injectors_by_lap: dict[int, list], n: int) -> list[list[dict]]:
    laps = []
    for lap in range(1, n + 1):
        f = _lap_frames(_archive())
        for inj in injectors_by_lap.get(lap, []):
            inj(f)
        laps.append(f)
    return laps


def _primes(cues, corner=None):
    return [c for c in cues if c.coach == "prime" and (corner is None or c.corner == corner)]


# --- SANITY_00: a driver on the reference is coached NOTHING (no false positives) -----------------
def test_sanity_reference_is_total_silence():
    sim = CoachSim()
    cues = sim.drive([_lap_frames(_archive()) for _ in range(5)])
    assert _primes(cues) == [], [c.phrase for c in _primes(cues)]


# --- the five root errors, each diagnosed + spoken at the right anchor on the armed lap ----------
@pytest.mark.parametrize(
    "t, inject, phrase, anchor_attr",
    [
        (1, early_brake, "Brake later.", "brake"),
        (1, late_brake, "Brake earlier.", "brake"),
        (3, slow_apex, "Carry more.", "turn_in"),
        (3, late_throttle, "Power.", "apex"),
    ],
)
def test_root_error_spoken_at_anchor(t, inject, phrase, anchor_attr):
    sim = CoachSim()
    idx, ref = sim.corner(t)
    laps = _laps(sim, {lap: [lambda f, r=ref: inject(f, r)] for lap in (1, 2, 3)}, 3)
    cues = sim.drive(laps)
    mine = _primes(cues, corner=idx)
    assert mine, f"T{t} {inject.__name__} must be coached"
    first = mine[0]
    assert first.phrase == phrase
    assert first.lap >= 2  # after the assess lap
    anchor = getattr(sim.rt.anchors[idx], anchor_attr)
    assert abs(first.spline - anchor) < 0.03, f"fired @{first.spline:.3f} not near {anchor:.3f}"


# --- magnitude grading (P2): same word, register escalates with the size of the miss -------------
@pytest.mark.parametrize("amount, expect_register", [(0.008, "firm"), (0.030, "critical")])
def test_magnitude_grades_register(amount, expect_register):
    sim = CoachSim()
    idx, ref = sim.corner(1)
    laps = _laps(
        sim,
        {lap: [lambda f, a=amount, r=ref: early_brake(f, r, amount=a)] for lap in (1, 2, 3)},
        3,
    )
    mine = _primes(sim.drive(laps), corner=idx)
    assert mine, "an early brake must be coached"
    assert mine[0].phrase == "Brake later."  # word unchanged
    assert mine[0].register == expect_register  # tone reflects magnitude


# --- ROOT_NOT_SYMPTOM: early brake CAUSES late throttle → coach only the cause -------------------
def test_root_not_symptom():
    sim = CoachSim()
    idx, ref = sim.corner(1)

    def both(f):
        early_brake(f, ref)
        late_throttle(f, ref)

    cues = sim.drive(_laps(sim, {lap: [both] for lap in (1, 2, 3)}, 3))
    phrases = {c.phrase for c in _primes(cues, corner=idx)}
    assert "Brake later." in phrases
    assert "Power." not in phrases  # downstream symptom suppressed


# --- GRIP_GATE (P3): at the lateral limit, a slow apex is setup/tyre — stay SILENT, don't lie -----
def test_grip_gate_silences_slow_apex_at_the_limit():
    sim = CoachSim()
    idx, ref = sim.corner(3)

    def slow_but_at_limit(f):
        slow_apex(f, ref, kmh=10.0)
        at_grip_limit(f, ref)

    cues = sim.drive(_laps(sim, {lap: [slow_but_at_limit] for lap in (1, 2, 3)}, 3))
    assert _primes(cues, corner=idx) == []  # at the grip ceiling → no "Carry more."


def test_grip_gate_fail_open_without_signal():
    # the SAME slow apex WITHOUT a grip signal must still be coached (gate is honest/fail-open)
    sim = CoachSim()
    idx, ref = sim.corner(3)
    inj = {lap: [lambda f: slow_apex(f, ref, kmh=10.0)] for lap in (1, 2, 3)}
    cues = sim.drive(_laps(sim, inj, 3))
    assert any(c.phrase == "Carry more." for c in _primes(cues, corner=idx))


# --- SAVE_GROSS: blow past the brake point on the gas → instant "Brake!" -------------------------
def test_save_gross_late_brake():
    sim = CoachSim()
    idx, ref = sim.corner(1)
    cues = sim.drive(_laps(sim, {1: [lambda f: gross_late_brake(f, ref)]}, 2))
    saves = [c for c in cues if c.coach == "save" and c.corner == idx]
    assert saves and saves[0].phrase == "Brake!"


# --- pacing: hysteresis, assess, budget, acknowledge-then-silence, regression --------------------
def test_assess_laps_silent_then_arms():
    sim = CoachSim(assess=2, hysteresis=1)
    idx, ref = sim.corner(1)
    cues = sim.drive(_laps(sim, {lap: [lambda f: early_brake(f, ref)] for lap in range(1, 5)}, 4))
    laps_spoken = {c.lap for c in _primes(cues, corner=idx)}
    assert all(lap > 2 for lap in laps_spoken), f"spoke on an assess lap: {laps_spoken}"


def test_hysteresis_needs_two_passes():
    sim = CoachSim(assess=1, hysteresis=2)
    idx, ref = sim.corner(1)
    # error only on lap 3 → one pass → never two consecutive → silent
    cues = sim.drive(_laps(sim, {3: [lambda f: early_brake(f, ref)]}, 4))
    assert _primes(cues, corner=idx) == []


def test_budget_caps_cues_per_lap():
    sim = CoachSim(assess=1, hysteresis=1, budget=2)

    # slow every corner; only the 2 biggest losses should speak per lap
    def slow_all(f):
        for r in sim.rt.refs:  # CornerReference has spline_lo/spline_hi/apex_spline
            slow_apex(f, r, kmh=12.0)

    cues = sim.drive(_laps(sim, {lap: [slow_all] for lap in (1, 2, 3)}, 3))
    by_lap: dict[int, int] = {}
    for c in _primes(cues):
        if c.lap >= 2:
            by_lap[c.lap] = by_lap.get(c.lap, 0) + 1
    assert by_lap and all(n <= 2 for n in by_lap.values()), by_lap


def test_acknowledge_once_then_silence():
    sim = CoachSim(assess=1, hysteresis=1)
    idx, ref = sim.corner(1)
    inj = {
        1: [lambda f: early_brake(f, ref)],
        2: [lambda f: early_brake(f, ref)],
        3: [lambda f: early_brake(f, ref)],
    }  # clean from lap 4
    cues = sim.drive(_laps(sim, inj, 6))
    confirms = [c for c in cues if c.coach == "confirm" and c.corner == idx]
    assert len(confirms) == 1 and confirms[0].phrase == "Good."
