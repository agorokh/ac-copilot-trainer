"""Coach v2 END-TO-END deterministic harness (council P0 — the gate every other criterion is
measured against).

Drives the REAL ``CoachRuntime.observe()`` with the real Magione reference trace, injecting a KNOWN
driver error at a KNOWN corner, across a multi-lap stint, and asserts the RIGHT phrase at the RIGHT
place with the RIGHT pacing — the full scenario matrix the ~1-lap autonomous driver cannot cover.

No clock, no sleeps, no I/O: array iteration over a frozen trace → <100 ms, zero flakiness.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.ai_sidecar.coaching_runtime import build_coach_runtime


@pytest.fixture
def display_lua():
    """Exercise the real Lua producer, independently of the voice coach."""
    lupa = pytest.importorskip("lupa")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    modules = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"
    lua.execute(f'package.path = package.path .. ";{modules.as_posix()}/?.lua"')
    lua.execute("rtc = require('realtime_coaching'); publisher = require('coaching_publisher')")
    return lua


def _display_view(lua, *, spline=0.11, speed=130, rpm=3000, reference=True):
    opts = lua.eval("""{
      splinePos=0.11, currentSpeedKmh=130, trackLengthM=2000,
      rpm=3000, rpmLimiter=8000, gear=3, gearCount=6, gas=0.95,
      bestSortedTrace={{spline=0,speed=100},{spline=1,speed=100}},
      brakingPoints={{spline=0.1,entrySpeed=180,label='T1'},
        {spline=0.5,entrySpeed=230,label='T2'}},
      segments={{kind='corner',s0=0.105,s1=0.49,label='T1'},
        {kind='corner',s0=0.505,s1=0.9,label='T2'}}
    }""")
    opts["splinePos"], opts["currentSpeedKmh"], opts["rpm"] = spline, speed, rpm
    if not reference:
        opts["bestSortedTrace"], opts["brakingPoints"], opts["segments"] = None, None, None
    return lua.globals().rtc.tick(opts)


def _publish_display(lua, view):
    lua.globals().view = view
    payload = lua.execute("""
      publisher.reset()
      local frame
      assert(publisher.publishIfDue({dt=0.1,view=view,car={speedKmh=130},
        wsBridge={publishTopic=function(topic,payload)
          assert(topic=='coaching.snapshot'); frame=payload; return true end}}))
      return frame
    """)
    return dict(payload.items())


@pytest.mark.parametrize(
    ("spline", "speed", "rpm", "action", "kind"),
    [
        (0.11, 130, 3000, "LIFT", "line"),
        (0.11, 70, 3000, "CARRY_MORE_SPEED", "line"),
        (0.3, 130, 7800, "UPSHIFT", "line"),
        (0.485, 250, 7800, "BRAKE", "brake"),
        (0.46, 230, 3000, "HOLD", "info"),
        (0.3, 130, 3000, "CLEAR", "info"),
    ],
)
def test_display_actions_survive_producer(display_lua, spline, speed, rpm, action, kind):
    frame = _publish_display(
        display_lua, _display_view(display_lua, spline=spline, speed=speed, rpm=rpm)
    )
    assert frame["action"] == action
    assert frame["kind"] == kind


def test_display_current_corner_never_uses_future_brake_speed(display_lua):
    frame = _publish_display(display_lua, _display_view(display_lua))
    assert frame["action"] == "LIFT"  # 130 is too fast for current 100, below future 230
    assert frame["current_corner_label"] == "T1"
    assert frame["approach_corner_label"] == frame["target_corner_id"] == "T2"
    assert frame["target_speed_kmh"] == 230
    assert frame["target_phase"] == "brake_onset"
    assert frame["target_provenance"] == "reference_brake"
    assert frame["selected_target_speed_kmh"] == frame["current_target_speed_kmh"] == 100
    assert frame["selected_target_corner_id"] == "T1"
    assert frame["selected_target_phase"] == "reference_at_position"


def test_display_phase_transition_clears_current_target(display_lua):
    current = _publish_display(display_lua, _display_view(display_lua))
    straight = _publish_display(display_lua, _display_view(display_lua, spline=0.3))
    assert current["current_target_available"] is True
    assert straight["action"] == "CLEAR"
    assert straight.get("current_corner_label") is None
    assert straight.get("current_target_speed_kmh") is None
    assert straight["current_target_available"] is False
    assert straight["current_target_phase"] == "unavailable"
    assert straight["target_speed_kmh"] == 230


def test_display_missing_reference_and_independent_shift(display_lua):
    empty = _publish_display(display_lua, _display_view(display_lua, reference=False))
    assert empty["action"] == "UNAVAILABLE"
    assert empty["target_available"] is False
    assert empty.get("target_speed_kmh") is None
    shift = _publish_display(display_lua, _display_view(display_lua, reference=False, rpm=7800))
    assert shift["action"] == "UPSHIFT"
    assert shift["selected_target_available"] is False


def test_display_legacy_line_kind_fails_safe_and_exact_verb_survives(display_lua):
    for primary, action in [
        ("SHIFT UP", "UPSHIFT"),
        ("CARRY MORE SPEED", "CARRY_MORE_SPEED"),
        ("UNKNOWN", "UNAVAILABLE"),
    ]:
        frame = _publish_display(
            display_lua,
            display_lua.table_from({"primaryLine": primary, "kind": "line", "targetSpeedKmh": 230}),
        )
        assert frame["action"] == action
        assert frame["target_available"] is False
        assert frame.get("target_speed_kmh") is None


def test_display_action_and_target_reach_both_sidecar_consumers(display_lua, monkeypatch):
    from tools.ai_sidecar import server

    class Peer:
        remote_address = ("127.0.0.1", 5000)

        def __init__(self):
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

    producer, tablet, screen = Peer(), Peer(), Peer()
    monkeypatch.setattr(server, "_external_peers", {producer, tablet, screen})
    monkeypatch.setattr(server, "_external_peer_classes", {})

    async def relay():
        for spline, speed, rpm in [
            (0.11, 130, 3000),
            (0.11, 70, 3000),
            (0.3, 130, 7800),
            (0.485, 250, 7800),
            (0.46, 230, 3000),
            (0.3, 130, 3000),
        ]:
            payload = _publish_display(
                display_lua, _display_view(display_lua, spline=spline, speed=speed, rpm=rpm)
            )
            frame = {
                "v": 1,
                "type": "state.snapshot",
                "topic": "coaching.snapshot",
                "payload": payload,
            }
            await server._handle_external_frame(producer, frame)
            assert tablet.sent[-1] == screen.sent[-1] == frame

    asyncio.run(relay())
    assert [f["payload"]["action"] for f in tablet.sent] == [
        "LIFT",
        "CARRY_MORE_SPEED",
        "UPSHIFT",
        "BRAKE",
        "HOLD",
        "CLEAR",
    ]


def test_display_segment_fallback_reports_entry_and_zero_is_valid(display_lua):
    view = display_lua.execute("""
      return rtc.tick({splinePos=0.1,currentSpeedKmh=0,trackLengthM=2000,
        segments={{kind='corner',s0=0.5,s1=0.8,label='T1',entrySpeed=0}}})
    """)
    frame = _publish_display(display_lua, view)
    assert frame["target_speed_kmh"] == 0
    assert frame["target_available"] is True
    assert frame["target_phase"] == "entry"
    assert frame["target_provenance"] == "segment_entry"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1001])
def test_display_invalid_targets_are_explicitly_unavailable(display_lua, value):
    frame = _publish_display(
        display_lua,
        display_lua.table_from(
            {
                "action": "HOLD",
                "targetSpeedKmh": value,
                "targetAvailable": True,
                "targetPhase": "brake_onset",
                "targetProvenance": "reference_brake",
            }
        ),
    )
    assert frame.get("target_speed_kmh") is None
    assert frame["target_available"] is False
    assert frame["target_phase"] == frame["target_provenance"] == "unavailable"


def test_display_incompatible_target_phase_and_provenance_fails_safe(display_lua):
    frame = _publish_display(
        display_lua,
        display_lua.table_from(
            {
                "action": "HOLD",
                "targetSpeedKmh": 100,
                "targetAvailable": True,
                "targetPhase": "brake_onset",
                "targetProvenance": "reference_trace",
            }
        ),
    )
    assert frame["target_available"] is False
    assert frame.get("target_speed_kmh") is None


def test_display_speed_distinguishes_stopped_cached_and_missing(display_lua):
    display_lua.execute("""
      publisher.reset()
      local payload
      local bridge={publishTopic=function(topic,p) payload=p; return true end}
      publisher.publishIfDue({dt=0.1,car={speedKmh=0},wsBridge=bridge})
      assert(payload.current_speed_kmh==0 and payload.current_speed_available)
      assert(payload.current_speed_source=='live')
      publisher.publishIfDue({dt=0.1,car={speedKmh=0/0},wsBridge=bridge})
      assert(payload.current_speed_kmh==0 and not payload.current_speed_available)
      assert(payload.current_speed_source=='cached')
      publisher.publishIfDue({dt=0.1,car=nil,wsBridge=bridge})
      assert(payload.current_speed_kmh==-1 and not payload.current_speed_available)
      assert(payload.current_speed_source=='unavailable')
    """)


def test_display_corner_query_pairs_future_speed_with_future_identity(display_lua):
    display_lua.execute("""
      rtc.reset()
      _query = nil
      local view = rtc.tick({splinePos=0.11,currentSpeedKmh=130,trackLengthM=2000,
        approachMeters=1000,bestSortedTrace={{spline=0,speed=100},{spline=1,speed=100}},
        brakingPoints={{spline=0.5,entrySpeed=230,label='T2'}},
        segments={{kind='corner',s0=0.105,s1=0.49,label='T1'}},
        wsBridge={sendCornerQuery=function(label,cur,target,dist,lap)
          _query={label=label,target=target}; return true end}})
      assert(view.currentCornerLabel=='T1')
    """)
    query = display_lua.globals()._query
    assert query["label"] == "T2"
    assert query["target"] == 230


# Prefer the committed fixture (so this CI gate actually RUNS on a clean checkout); fall back to the
# rig capture under .scratch (gitignored) when iterating on the rig.
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "magione_gt3r_reference.json"
_RIG = Path(__file__).resolve().parents[1] / ".scratch" / "coach-demo" / "reference.json"
REF_PATH = _FIXTURE if _FIXTURE.exists() else _RIG
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="reference trace fixture missing")


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
@pytest.mark.parametrize(
    "amount, expect_register",
    [(0.008, "alert"), (0.012, "urgent"), (0.030, "critical")],
)
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
    # T3, where late_throttle DOES fire in isolation (see test_root_error_spoken_at_anchor) — so the
    # "Power. not coached" assertion is non-vacuous: it proves the earliest-in-chain suppression.
    sim = CoachSim()
    idx, ref = sim.corner(3)

    def both(f):
        early_brake(f, ref)
        late_throttle(f, ref)

    cues = sim.drive(_laps(sim, {lap: [both] for lap in (1, 2, 3)}, 3))
    phrases = {c.phrase for c in _primes(cues, corner=idx)}
    assert "Brake later." in phrases  # the cause is coached
    assert "Power." not in phrases  # the downstream symptom (late throttle) is suppressed


# --- B1/B2 guard: the pass window must CLOSE per-corner (no lap-wide accumulation) ---------------
def test_no_cross_corner_false_positive():
    """A slow apex injected at ONE corner must not be coached at OTHER corners. If the per-corner
    pass window never closes (accumulates to lap-end), an injection bleeds into every upstream
    corner's apex and false-positives there. This fails before the window-latch fix (B1/B2)."""
    sim = CoachSim()
    idx5, ref5 = sim.corner(5)
    cues = sim.drive(
        _laps(sim, {lap: [lambda f: slow_apex(f, ref5, kmh=12.0)] for lap in (1, 2, 3)}, 3)
    )
    coached = {c.corner for c in _primes(cues)}
    assert coached <= {idx5}, f"slow apex at T5 leaked to corners {coached - {idx5}}"


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
    assert saves[0].register == "critical"  # SAVE is always a critical-register barge-in


# --- pacing: hysteresis, assess, budget, acknowledge-then-silence, regression --------------------
def test_assess_laps_silent_then_arms():
    sim = CoachSim(assess=2, hysteresis=1)
    idx, ref = sim.corner(1)
    cues = sim.drive(_laps(sim, {lap: [lambda f: early_brake(f, ref)] for lap in range(1, 5)}, 4))
    laps_spoken = {c.lap for c in _primes(cues, corner=idx)}
    assert laps_spoken, "the error must eventually be coached (guard against a vacuous pass)"
    assert all(lap > 2 for lap in laps_spoken), f"spoke on an assess lap: {laps_spoken}"


def test_hysteresis_needs_two_passes():
    sim = CoachSim(assess=1, hysteresis=2)
    idx, ref = sim.corner(1)
    # error only on lap 3 → one pass → never two consecutive → silent
    cues = sim.drive(_laps(sim, {3: [lambda f: early_brake(f, ref)]}, 4))
    assert _primes(cues, corner=idx) == []


def test_budget_caps_cues_per_lap():
    sim = CoachSim(assess=1, hysteresis=1, budget=2)
    big = [sim.corner(3)[1], sim.corner(5)[1]]  # T3 + T5 get the BIG deficits (most time lost)

    def inject(f):
        for r in sim.rt.refs:  # small deficit at every corner
            slow_apex(f, r, kmh=4.0)
        for info in big:  # extra slow at T3/T5 → they lose the most time
            slow_apex(f, info, kmh=18.0)

    cues = sim.drive(_laps(sim, {lap: [inject] for lap in (1, 2, 3)}, 3))
    by_lap: dict[int, int] = {}
    for c in _primes(cues):
        if c.lap >= 2:
            by_lap[c.lap] = by_lap.get(c.lap, 0) + 1
    assert by_lap and all(n <= 2 for n in by_lap.values()), by_lap  # budget cap honoured
    # the budget is spent on the two BIGGEST-loss corners (T3=idx2, T5=idx4), not arbitrary ones
    spoken_idx = {c.corner for c in _primes(cues) if c.lap >= 2}
    assert spoken_idx <= {2, 4}, f"budget spent off the biggest losses: {spoken_idx - {2, 4}}"


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
