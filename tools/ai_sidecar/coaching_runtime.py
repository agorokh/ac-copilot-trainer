"""Coach v2 runtime: live telemetry frames → anticipatory, diagnosed, paced spoken cues.

This is the live engine that ties the keystones together. It reuses the existing corner geometry
(:func:`tools.ai_sidecar.track_reference.build_references` + the reference lap's
:class:`~tools.ai_sidecar.lap_dynamics.CornerSignature`) and, per live frame:

1. accumulates the driver's technique for the corner currently being driven,
2. on corner exit, diagnoses the single ROOT error (:mod:`coaching_diagnosis`) and records it in the
   :class:`~tools.ai_sidecar.coaching_ledger.CoachingLedger`,
3. fires a **PRIME** imperative ("Brake later.") when the car crosses that root's pre-computed
   reference anchor — *before* the action point, so the driver can still act,
4. fires a **SAVE** ("Brake!") live when an unfolding gross error needs an instant barge-in,
5. fires a **CONFIRM** ("Good.") once when a coached mistake is fixed, then goes silent.

Deliberately a SEPARATE engine from the battle-tested :class:`RealtimeObserver` (which stays for the
geometry); the server wires whichever producer is active. Pure stdlib + the keystone modules — no
I/O — so it is unit-tested by feeding synthetic injected-mistake frame streams.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from tools.ai_sidecar.coaching_diagnosis import (
    ANCHOR,
    PHRASE,
    Diagnosis,
    RootError,
    classify_root_error,
)
from tools.ai_sidecar.coaching_ledger import (
    ASSESS_LAPS,
    HYSTERESIS_PASSES,
    LAP_CUE_BUDGET,
    CoachingLedger,
)
from tools.ai_sidecar.lap_dynamics import CornerSignature, corner_signatures, lap_trace_from_archive
from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.track_reference import CornerReference, build_references

#: Roots that demand more speed / later braking — suppressed at the grip ceiling (P3).
_GRIP_GATED_ROOTS = frozenset({RootError.SLOW_APEX, RootError.EARLY_BRAKE, RootError.LATE_BRAKE})

# live thresholds
_BRAKE_ON = 0.05
_THROTTLE_ON = 0.20
_STEER_ON = 0.05
_GRIP_CEILING_G = 1.55  # GT3 peak lateral g (the Magione reference corners at 1.40–1.56 g)
# At/above this fraction of the grip ceiling the corner is grip-limited (setup/tyre), NOT technique,
# so "carry more"/"brake later" would be a lie and is suppressed. HONEST GATE: needs a real
# grip/lateral-g signal on the frame (grip/grip_used/lat_g); the live telemetry carries none today,
# so it is fail-open (never suppresses) on the rig and activates only when the telemetry provides
# tyre-slip or lateral-g. We do NOT fabricate it from v²·κ against an at-the-limit reference (which
# can never fire honestly). See council P3.
_GRIP_GATE_FRAC = 0.95
_DEFAULT_TRACK_M = 2455.7
_DEFAULT_LEAD_S = 1.3  # reference-travel seconds before the action point a PRIME audio onset lands
_LAP_WRAP_DROP = 0.5  # backward spline jump that means a start/finish wrap

# SAVE: gross late brake — past the reference brake point, still not braking, carrying speed.
_SAVE_LATE_BRAKE_MARGIN = 0.01  # spline past the ref brake point before it's "gross"


@dataclass
class _Anchors:
    """Pre-computed reference spline points a corner's PRIME fires at, by action-point type."""

    brake: float
    turn_in: float
    apex: float

    def for_root(self, root: RootError) -> float:
        return {"brake": self.brake, "turn_in": self.turn_in, "apex": self.apex}[ANCHOR[root]]


@dataclass
class _PassState:
    """Per-corner accumulation for the current pass (reset when the car leaves the window)."""

    active: bool = False
    brake_onset_spline: float | None = None
    min_speed_kmh: float = 1e9
    apex_spline: float = 0.0
    throttle_on_spline: float | None = None
    entry_speed_kmh: float = 0.0
    exit_speed_kmh: float = 0.0
    trail_count: int = 0
    entry_count: int = 0
    save_fired: bool = False
    max_grip_used: float = 0.0  # peak grip-utilisation fraction this pass (0 if no signal)

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


def _lead_spline(ref_speed_kmh: float, track_m: float, lead_s: float) -> float:
    if ref_speed_kmh <= 0 or lead_s <= 0:
        return 0.005
    return max(0.003, min(0.10, (ref_speed_kmh / 3.6) * lead_s / max(track_m, 1.0)))


@dataclass
class CoachRuntime:
    """Live coach: feed normalized frames via :meth:`observe`; returns spoken-cue advisories."""

    refs: list[CornerReference]
    ref_sigs: dict[int, CornerSignature]
    anchors: dict[int, _Anchors]
    track_length_m: float = _DEFAULT_TRACK_M
    ledger: CoachingLedger = field(default_factory=CoachingLedger)
    _pass: dict[int, _PassState] = field(default_factory=dict)
    _last_spline: float | None = None
    _last_lap: float | None = None
    _lap: int = 1

    def __post_init__(self) -> None:
        self.refs = sorted(self.refs, key=lambda r: r.spline_lo)
        self._pass = {r.index: _PassState() for r in self.refs}
        self.ledger.begin_lap(self._lap)

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        spline, speed, brake, throttle, steer, lap, grip = _normalize(frame)
        if spline is None or speed is None:
            return []
        out: list[Advisory] = []

        # lap wrap → new lap: finalize any open pass, advance the ledger's lap.
        if self._last_spline is not None and self._last_spline - spline > _LAP_WRAP_DROP:
            self._lap += 1
            self.ledger.begin_lap(self._lap)
            for r in self.refs:  # close any pass left open across the line
                if self._pass[r.index].active:
                    out.extend(self._finalize_pass(r))

        for r in self.refs:
            st = self._pass[r.index]
            anc = self.anchors[r.index]

            # 1. PRIME — fire on crossing the armed root's anchor (before the action point).
            root = self.ledger.armed_root(r.index)
            if root is not None and _crossed(self._last_spline, spline, anc.for_root(root)):
                spoken = self.ledger.due_prime(r.index)
                if spoken is not None:
                    gst = self.ledger.state(r.index)
                    reg = gst.register if gst else "firm"
                    inten = gst.intensity if gst else 0.5
                    out.append(_prime(r, spoken, spline, register=reg, intensity=inten))

            # 2. accumulate technique within the pass window, finalize on exit.
            in_window = (anc.brake - 0.04) <= spline <= r.spline_hi or st.active
            if r.spline_lo <= spline <= r.spline_hi or in_window:
                self._accumulate(st, r, spline, speed, brake, throttle, steer, out)
                if grip is not None and st.active:
                    st.max_grip_used = max(st.max_grip_used, grip)
            elif st.active and spline > r.spline_hi:
                out.extend(self._finalize_pass(r))

        self._last_spline = spline
        if lap is not None:
            self._last_lap = lap
        return out

    def _accumulate(
        self,
        st: _PassState,
        r: CornerReference,
        spline: float,
        speed: float,
        brake: float,
        throttle: float,
        steer: float,
        out: list[Advisory],
    ) -> None:
        _accumulate_core(st, r, spline, speed, brake, throttle, steer)

        # SAVE: past the reference brake point, still coasting (no brake), carrying speed → "Brake!"
        ref_sig = self.ref_sigs.get(r.index)
        ref_bp = ref_sig.brake_point_spline if ref_sig else None
        if (
            not st.save_fired
            and ref_bp is not None
            and spline > ref_bp + _SAVE_LATE_BRAKE_MARGIN
            and spline < r.apex_spline
            and brake < _BRAKE_ON
            and throttle > 0.5
        ):
            st.save_fired = True
            out.append(_save(r, "Brake!", spline))

    def _finalize_pass(self, r: CornerReference) -> list[Advisory]:
        st = self._pass[r.index]
        ref_sig = self.ref_sigs.get(r.index)
        if ref_sig is None:  # no reference technique for this corner → can't diagnose
            st.reset()
            return []
        sig = _signature_from_pass(st, r)
        diag = classify_root_error(sig, ref_sig)
        # GRIP-GATE (P3): at the lateral-grip ceiling the loss is setup/tyre, not technique —
        # demanding more speed/later braking would lie, so suppress. Fail-open: fires only when a
        # real grip signal was present this pass (see _GRIP_GATE_FRAC).
        if diag.root in _GRIP_GATED_ROOTS and st.max_grip_used >= _GRIP_GATE_FRAC:
            diag = Diagnosis(RootError.NONE, {"grip_gated": round(st.max_grip_used, 3)})
        # time-lost proxy: apex-speed deficit (km/h) stands in until lap-time deltas are wired
        time_lost = max(0.0, ref_sig.min_speed_kmh - st.min_speed_kmh)
        events = self.ledger.record_pass(r.index, diag, time_lost_s=time_lost, valid=True)
        st.reset()
        return [_confirm(r) for e in events if e.kind == "confirm"]


def _accumulate_core(
    st: _PassState,
    r: CornerReference,
    spline: float,
    speed: float,
    brake: float,
    throttle: float,
    steer: float,
) -> None:
    """Technique accumulation for one in-window frame (no emit) — shared by the live path and the
    reference-signature pre-pass, so a driver ON the reference diagnoses to NONE (self-consistent).
    """
    if not st.active:
        st.active = True
        st.entry_speed_kmh = speed
    st.exit_speed_kmh = speed
    if brake >= _BRAKE_ON and st.brake_onset_spline is None:
        st.brake_onset_spline = spline
    if speed < st.min_speed_kmh:
        st.min_speed_kmh = speed
        st.apex_spline = spline
    if spline <= r.apex_spline:
        st.entry_count += 1
        if brake > _BRAKE_ON and abs(steer) > _STEER_ON:
            st.trail_count += 1
    elif throttle >= _THROTTLE_ON and st.throttle_on_spline is None:
        st.throttle_on_spline = spline


def _reference_signatures(
    refs: list[CornerReference], anchors: dict[int, _Anchors], frames: list[dict[str, Any]]
) -> dict[int, CornerSignature]:
    """Derive the reference corner signatures with the SAME accumulation the live path uses, so the
    diagnosis compares like-with-like (replaying the reference yields RootError.NONE everywhere)."""
    states = {r.index: _PassState() for r in refs}
    sigs: dict[int, CornerSignature] = {}
    for fr in frames:
        spline, speed, brake, throttle, steer, _, _ = _normalize(fr)
        if spline is None or speed is None:
            continue
        for r in refs:
            st = states[r.index]
            anc = anchors[r.index]
            in_window = (anc.brake - 0.04) <= spline <= r.spline_hi or st.active
            if r.spline_lo <= spline <= r.spline_hi or in_window:
                _accumulate_core(st, r, spline, speed, brake, throttle, steer)
            elif st.active and spline > r.spline_hi:
                sigs[r.index] = _signature_from_pass(st, r)
                st.reset()
    for r in refs:
        if r.index not in sigs and states[r.index].active:
            sigs[r.index] = _signature_from_pass(states[r.index], r)
    return sigs


# --- advisory builders (message carries the exact spoken phrase) ---
def _prime(
    r: CornerReference, root: RootError, spline: float, *, register: str = "firm",
    intensity: float = 0.5,
) -> Advisory:
    return Advisory(
        kind=str(root),
        corner=r.index,
        spline=round(spline, 4),
        urgency="act" if ANCHOR[root] == "apex" else "prepare",
        message=PHRASE[root],
        detail={"coach": "prime", "root": str(root)},
        intensity=intensity,
        register=register,
    )


def _save(r: CornerReference, phrase: str, spline: float) -> Advisory:
    return Advisory(
        kind="save",
        corner=r.index,
        spline=round(spline, 4),
        urgency="act",
        message=phrase,
        detail={"coach": "save"},
        intensity=1.0,
        register="critical",
    )


def _confirm(r: CornerReference) -> Advisory:
    return Advisory(
        kind="confirm",
        corner=r.index,
        spline=round(r.spline_hi, 4),
        urgency="info",
        message="Good.",
        detail={"coach": "confirm"},
        intensity=0.0,
        register="calm",
    )


def _signature_from_pass(st: _PassState, r: CornerReference) -> CornerSignature:
    trail = st.trail_count / max(1, st.entry_count)
    return CornerSignature(
        index=r.index,
        entry_i=0,
        apex_i=0,
        exit_i=0,
        apex_spline=st.apex_spline,
        min_speed_kmh=0.0 if st.min_speed_kmh >= 1e9 else st.min_speed_kmh,
        entry_speed_kmh=st.entry_speed_kmh,
        exit_speed_kmh=st.exit_speed_kmh,
        peak_lat_g=0.0,
        peak_brake_g=0.0,
        peak_accel_g=0.0,
        brake_point_spline=st.brake_onset_spline,
        brake_to_apex_m=None,
        throttle_on_spline=st.throttle_on_spline,
        apex_to_throttle_m=None,
        trail_brake_frac=trail,
        max_abs_steer=0.0,
        direction="straightish",
    )


def _crossed(prev: float | None, cur: float, target: float) -> bool:
    """True if the car crossed ``target`` between ``prev`` and ``cur`` (no wrap within a pass)."""
    if prev is None:
        return False
    return prev < target <= cur


def _normalize(
    frame: dict[str, Any],
) -> tuple[float | None, float | None, float, float, float, float | None, float | None]:
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}

    def pick(*keys: str) -> Any:
        for src in (frame, payload):
            for k in keys:
                if k in src:
                    return src[k]
        return None

    def num(v: Any, default: float = 0.0) -> float:
        if isinstance(v, bool):
            return default
        try:
            f = float(v)
        except (TypeError, ValueError):
            return default
        return f if f == f and abs(f) != float("inf") else default

    spline = pick("spline", "normalizedSplinePosition")
    speed = pick("speed", "speed_kmh")
    spline = None if spline is None else num(spline)
    speed = None if speed is None else num(speed)
    # grip utilisation: a direct fraction if supplied, else derived from a lateral-g channel; None
    # when the frame carries neither (the live telemetry today) → the grip-gate stays fail-open.
    grip = pick("grip", "grip_used")
    if grip is None:
        latg = pick("lat_g", "latg", "accG")
        grip = None if latg is None else abs(num(latg)) / _GRIP_CEILING_G
    return (
        spline,
        speed,
        num(pick("brake")),
        num(pick("throttle", "gas")),
        num(pick("steer")),
        (None if pick("lap", "lapCount", "lap_count", "completedLaps") is None
         else num(pick("lap", "lapCount", "lap_count", "completedLaps"))),
        None if grip is None else num(grip),
    )


def build_coach_runtime(
    reference_archive: dict, *, lead_s: float = _DEFAULT_LEAD_S
) -> CoachRuntime | None:
    """Build a :class:`CoachRuntime` from a reference archive (same input as the observer)."""
    try:
        ref_lap = lap_trace_from_archive(reference_archive)
    except ValueError:
        return None
    refs = build_references(ref_lap)
    if not refs:
        return None
    geom = {s.index: s for s in corner_signatures(ref_lap)}  # for anchor timing only
    track_obj = reference_archive.get("track")
    track_m = _DEFAULT_TRACK_M
    if isinstance(track_obj, dict):
        try:
            track_m = float(track_obj.get("lengthM") or _DEFAULT_TRACK_M)
        except (TypeError, ValueError):
            track_m = _DEFAULT_TRACK_M
    anchors: dict[int, _Anchors] = {}
    for r in refs:
        sig = geom.get(r.index)
        v_ref = sig.entry_speed_kmh if sig else 150.0
        lead = _lead_spline(v_ref, track_m, lead_s)
        bp = (sig.brake_point_spline if sig and sig.brake_point_spline is not None else r.spline_lo)
        anchors[r.index] = _Anchors(
            brake=(bp - lead) % 1.0,
            turn_in=(r.spline_lo - lead) % 1.0,
            apex=r.apex_spline,
        )
    # reference signatures derived with the live accumulation (self-consistent diagnosis baseline)
    tr = reference_archive.get("trace") or {}
    fields = tr.get("fields") or []
    fi = {f: i for i, f in enumerate(fields)}
    ref_frames = [
        {k: row[fi[k]] for k in ("spline", "speed", "brake", "throttle", "steer") if k in fi}
        for row in tr.get("samples") or []
    ]
    ref_sigs = _reference_signatures(refs, anchors, ref_frames)
    # Pacing thresholds are env-tunable so the autonomous harness can verify PRIMEs in a few laps
    # (lower assess/hysteresis); production defaults stay conservative.
    ledger = CoachingLedger(
        hysteresis=_env_int("AC_COPILOT_COACH_HYSTERESIS", HYSTERESIS_PASSES),
        assess_laps=_env_int("AC_COPILOT_COACH_ASSESS_LAPS", ASSESS_LAPS),
        lap_budget=_env_int("AC_COPILOT_COACH_LAP_BUDGET", LAP_CUE_BUDGET),
    )
    return CoachRuntime(
        refs=refs, ref_sigs=ref_sigs, anchors=anchors, track_length_m=track_m, ledger=ledger
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default
