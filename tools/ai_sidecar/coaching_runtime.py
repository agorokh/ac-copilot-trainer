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
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.ai_sidecar.coaching_diagnosis import (
    ANCHOR,
    PHRASE,
    Diagnosis,
    RootError,
    classify_root_error,
)
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.driver_profile import DEFAULT_PROFILE_PATH, load_profile
from tools.ai_sidecar.driver_progression import (
    DriverCuePolicy,
    cue_policy_from_profile,
    default_cue_policy,
)
from tools.ai_sidecar.lap_dynamics import CornerSignature, corner_signatures, lap_trace_from_archive
from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.track_reference import CornerReference, build_references

#: Roots that demand more speed / later braking — suppressed at the grip ceiling (P3).
#: LATE_BRAKE maps to "Brake earlier." and is NOT grip-gated (still valid at the grip ceiling).
_GRIP_GATED_ROOTS = frozenset({RootError.SLOW_APEX, RootError.EARLY_BRAKE})

# live thresholds
_BRAKE_ON = 0.05
_THROTTLE_ON = 0.20
_STEER_ON = 0.05
_GRIP_CEILING_G = 1.55  # GT3 peak lateral g (the Magione reference corners at 1.40–1.56 g)
# At/above this fraction of the grip ceiling the corner is grip-limited (setup/tyre), not
# technique, so "carry more"/"brake later" would lie and is suppressed. The signal is the frame's
# lateral-g: lat_g is REQUIRED by the telemetry_tick contract (external_protocol), so the gate is
# LIVE-ACTIVE with the real producer; fail-open only for a producer that omits it (contract forbids
# that). We do NOT fabricate grip from v²·κ against an at-the-limit reference (can never fire
# honestly — the Magione reference itself corners at 1.40–1.56 g). See council P3.
_GRIP_GATE_FRAC = 0.95
_DEFAULT_TRACK_M = 2455.7
_DEFAULT_LEAD_S = 1.3  # reference-travel seconds before the action point a PRIME audio onset lands
_LAP_WRAP_DROP = 0.5  # backward spline jump that means a start/finish wrap OR same-lap rewind
_WRAP_PREV_MIN = 0.8  # prev spline must be high for a true start/finish wrap (codex #294)
_WRAP_CUR_MAX = 0.25  # current spline must be low for a true start/finish wrap

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
    cue_policy: DriverCuePolicy = field(default_factory=default_cue_policy)
    _pass: dict[int, _PassState] = field(default_factory=dict)
    _last_spline: float | None = None
    _last_lap: float | None = None
    _lap: int = 1
    _pending_wrap_finals: bool = False
    _pending_pre_lap: float | None = None

    def __post_init__(self) -> None:
        self.refs = sorted(self.refs, key=lambda r: r.spline_lo)
        self._pass = {r.index: _PassState() for r in self.refs}
        self.ledger.begin_lap(self._lap)

    def reset(self) -> None:
        """Clear ALL session state — call on pit-exit / producer reconnect / session restart (B4).

        Without this, stale ``_lap``/``_last_spline``/per-corner passes + a RETIRED ledger carry
        across stints, which silently suppresses cues until the sidecar process is restarted.
        """
        self.ledger.clear_session()
        self._pass = {r.index: _PassState() for r in self.refs}
        self._last_spline = None
        self._last_lap = None
        self._lap = 1
        self._pending_wrap_finals = False
        self._pending_pre_lap = None
        self.ledger.begin_lap(self._lap)

    def _advance_lap_after_wrap(self, out: list[Advisory]) -> None:
        """Finalize open passes, then advance the ledger lap (speak-set needs fresh diagnoses)."""
        for r in self.refs:
            if self._pass[r.index].active:
                out.extend(self._finalize_pass(r))
        self._lap += 1
        self.ledger.begin_lap(self._lap)

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        spline, speed, brake, throttle, steer, lap, grip = _normalize(frame)
        if spline is None or speed is None:
            return []
        out: list[Advisory] = []

        # Deferred wrap finalization when lapCount lags the spline drop by a frame (codex #294).
        if self._pending_wrap_finals:
            if (
                lap is not None
                and self._pending_pre_lap is not None
                and lap > self._pending_pre_lap
            ):
                self._advance_lap_after_wrap(out)
                self._pending_wrap_finals = False
                self._pending_pre_lap = None
            elif spline > _WRAP_CUR_MAX:
                self._pass = {r.index: _PassState() for r in self.refs}
                self._pending_wrap_finals = False
                self._pending_pre_lap = None

        # A backward spline jump is either a true start/finish wrap or a same-lap rewind/teleport.
        if self._last_spline is not None and self._last_spline - spline > _LAP_WRAP_DROP:
            lap_known = lap is not None and self._last_lap is not None
            lap_advanced = lap_known and lap > self._last_lap
            wrap_shaped = self._last_spline >= _WRAP_PREV_MIN and spline <= _WRAP_CUR_MAX
            if lap_advanced or (wrap_shaped and not lap_known):
                self._advance_lap_after_wrap(out)
            elif wrap_shaped and lap_known:
                self._pending_wrap_finals = True
                self._pending_pre_lap = self._last_lap
            else:
                self._pass = {r.index: _PassState() for r in self.refs}

        # Ambiguous wrap (lap counter lagging) must not PRIME/accumulate on the drop frame.
        if self._pending_wrap_finals:
            self._last_spline = spline
            if lap is not None:
                self._last_lap = lap
            return out

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

            # 2. Accumulate within the pass window [brake-lead .. exit], then finalize ON EXIT.
            # The exit check MUST come first: once a pass is active the window must be able to
            # CLOSE at spline_hi, else the corner accumulates lap-wide (B1) and every apex/min-speed
            # collapses to the lap minimum.
            if st.active and spline > r.spline_hi:
                out.extend(self._finalize_pass(r))
            elif (anc.brake - 0.04) <= spline <= r.spline_hi:
                self._accumulate(st, r, spline, speed, brake, throttle, steer, out)
                if grip is not None and st.active:
                    st.max_grip_used = max(st.max_grip_used, grip)

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
        if not self.cue_policy.allows(diag.root):
            diag = Diagnosis(RootError.NONE, {"skill_gated": 1.0})
        # time-lost proxy: apex-speed deficit (km/h) stands in until lap-time deltas are wired
        time_lost = max(0.0, ref_sig.min_speed_kmh - st.min_speed_kmh)
        # Validity gate (B3): a pass that never reached a plausible apex (no entry samples, or the
        # min-speed sentinel never beaten) is an out-lap / pit / teleport / partial pass — do NOT
        # let it poison the ledger. The runtime has no richer off-track flag yet; v2 trusts every
        # on-track pass that produced real corner samples (documented in the PR).
        valid = st.entry_count > 0 and st.min_speed_kmh < 1e9
        events = self.ledger.record_pass(r.index, diag, time_lost_s=time_lost, valid=valid)
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
            # Same window-close discipline as observe() (B2): the reference baseline must be built
            # with the IDENTICAL per-corner window, or a clean lap diagnoses non-NONE everywhere.
            if st.active and spline > r.spline_hi:
                sigs[r.index] = _signature_from_pass(st, r)
                st.reset()
            elif (anc.brake - 0.04) <= spline <= r.spline_hi:
                _accumulate_core(st, r, spline, speed, brake, throttle, steer)
    for r in refs:
        if r.index not in sigs and states[r.index].active:
            sigs[r.index] = _signature_from_pass(states[r.index], r)
    return sigs


# --- advisory builders (message carries the exact spoken phrase) ---
def _prime(
    r: CornerReference,
    root: RootError,
    spline: float,
    *,
    register: str = "firm",
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
    """True if the car crossed ``target`` going forward between ``prev`` and ``cur`` — wrap-aware
    (m6): on a track where a corner's anchor wraps below 0 (``brake_point < lead`` → anchor ≈ 0.99),
    the forward arc prev→1→0→cur must still register the crossing, else the PRIME is dropped.
    """
    if prev is None:
        return False
    if prev <= cur:  # normal, no wrap
        return prev < target <= cur
    return target > prev or target <= cur  # wrapped over start/finish


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
        (
            None
            if pick("lap", "lapCount", "lap_count", "completedLaps") is None
            else num(pick("lap", "lapCount", "lap_count", "completedLaps"))
        ),
        None if grip is None else num(grip),
    )


def _profile_for_runtime(
    driver_profile: Mapping[str, Any] | None,
    driver_profile_path: str | Path | None,
) -> Mapping[str, Any] | None:
    if driver_profile is not None:
        return driver_profile
    configured = driver_profile_path or os.environ.get("AC_COPILOT_DRIVER_PROFILE")
    path = Path(configured) if configured else DEFAULT_PROFILE_PATH
    if not path.exists() and configured is None:
        return None
    return load_profile(path)


def build_coach_runtime(
    reference_archive: dict,
    *,
    lead_s: float = _DEFAULT_LEAD_S,
    driver_profile: Mapping[str, Any] | None = None,
    driver_profile_path: str | Path | None = None,
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
        bp = sig.brake_point_spline if sig and sig.brake_point_spline is not None else r.spline_lo
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
    policy = cue_policy_from_profile(_profile_for_runtime(driver_profile, driver_profile_path))
    ledger = CoachingLedger(
        hysteresis=_env_int("AC_COPILOT_COACH_HYSTERESIS", policy.hysteresis, min_value=1),
        assess_laps=_env_int("AC_COPILOT_COACH_ASSESS_LAPS", policy.assess_laps, min_value=0),
        lap_budget=_env_int("AC_COPILOT_COACH_LAP_BUDGET", policy.lap_budget, min_value=1),
    )
    return CoachRuntime(
        refs=refs,
        ref_sigs=ref_sigs,
        anchors=anchors,
        track_length_m=track_m,
        ledger=ledger,
        cue_policy=policy,
    )


def _env_int(name: str, default: int, *, min_value: int = 0) -> int:
    """Env int with a floor (n7): an unvalidated 0/negative budget or hysteresis silently breaks
    pacing, so clamp rather than trust the operator."""
    try:
        return max(min_value, int(os.environ[name]))
    except (KeyError, ValueError):
        return default
