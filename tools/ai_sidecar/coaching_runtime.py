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
geometry); the server wires whichever producer is active. Archive construction resolves provenance
once at the boundary; telemetry ticks do no qualification I/O. Tests feed synthetic injected-mistake
frame streams.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from tools.ac_harness.ggv_profile import (
    G as _G_ACCEL,
)
from tools.ac_harness.ggv_profile import (
    GGVModel,
    ggv_from_telemetry,
)
from tools.ai_sidecar.coaching_diagnosis import (
    ANCHOR,
    APEX_KMH_FLOOR,
    PHRASE,
    THROTTLE_SPLINE_FLOOR,
    Diagnosis,
    RootError,
    classify_root_error,
)
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.conditions_model import analyze_conditions
from tools.ai_sidecar.driver_profile import DEFAULT_PROFILE_PATH, load_profile, sanitize_profile
from tools.ai_sidecar.driver_progression import (
    DriverCuePolicy,
    cue_policy_from_profile,
    default_cue_policy,
)
from tools.ai_sidecar.lap_dynamics import (
    CornerSignature,
    LapTrace,
    corner_signatures,
    lap_trace_from_archive,
)
from tools.ai_sidecar.race_management import _BRAKE_CRITICAL_C, _BRAKE_HOT_C
from tools.ai_sidecar.realtime_observer import (
    _CAL_EMA_ALPHA,
    CAL_MATCH_TOL_M,
    Advisory,
    _signed_spline_delta,
)
from tools.ai_sidecar.track_reference import (
    CornerReference,
    build_references,
    sustained_brake_onsets,
)
from tools.ai_sidecar.tyre_model import analyze_tyres
from tools.lap_qualification import qualify_archive

#: Roots that demand more speed / later braking — suppressed at the grip ceiling (P3) or when
#: thermal / track-condition eligibility gates abstain (#938).
#: LATE_BRAKE maps to "Brake earlier." and is NOT grip-gated (still valid at the grip ceiling).
_GRIP_GATED_ROOTS = frozenset({RootError.SLOW_APEX, RootError.EARLY_BRAKE})

# live thresholds
_BRAKE_ON = 0.05
_THROTTLE_ON = 0.20
_STEER_ON = 0.05
_BASELINE_GRIP_CEILING_G = 1.55  # legacy GT3 scalar kept only for baseline mode comparison (#938)
_GRIP_CEILING_G = _BASELINE_GRIP_CEILING_G
_GRIP_GATE_FRAC = 0.95
_CAPABILITY_GATE_MODES = frozenset({"condition_indexed", "ggv_denominator_only", "baseline"})
_MACHINE_CODE_RE = re.compile(r"^[a-z0-9_]+$")
_WHEELS: tuple[str, ...] = ("fl", "fr", "rl", "rr")
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
    max_lat_grip_used: float = 0.0  # peak speed-indexed lateral utilisation fraction
    max_entry_grip_used: float = 0.0  # peak corner-entry combined braking/turn-in utilisation
    has_grip_evidence: bool = False
    has_thermal_evidence: bool = False
    ineligible_reason: str = ""

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]


@dataclass(frozen=True)
class _FrameCapability:
    """Per-frame capability utilization and thermal/condition eligibility evaluation (#938)."""

    lat_util: float | None = None
    entry_util: float | None = None
    has_grip_evidence: bool = False
    has_thermal_evidence: bool = False
    has_cond_evidence: bool = False
    has_brake_evidence: bool = False
    has_tyre_evidence: bool = False
    cond_reason: str = ""
    brake_reason: str = ""
    tyre_reason: str = ""
    ineligible_reason: str = ""


def _default_ggv_model() -> GGVModel:
    return GGVModel(
        mu_lat_g=_BASELINE_GRIP_CEILING_G,
        k_aero_lat=0.0,
        brake_b0_g=1.60,
        brake_b1=0.0,
        drive_b0_g=0.80,
        drive_b1=0.0,
        drive_min_g=0.25,
        ellipse_n=1.4,
    )


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
    frontier: dict[str, Any] = field(
        default_factory=lambda: {
            "configured": False,
            "active": False,
            "source": "reference",
            "reason": "not_configured",
            "corners": [],
        }
    )
    brake_lead_s: float = _DEFAULT_LEAD_S
    track_id: str | None = None
    track_layout: str | None = None
    reference_lap_ms: float | None = None
    ggv_model: GGVModel = field(default_factory=_default_ggv_model)
    capability_gate_mode: str = "condition_indexed"
    reference_compound: str | None = None
    reference_optimal_temp_c: float | None = None
    last_pass_capability: dict[int, dict[str, Any]] = field(default_factory=dict)
    # A dynamic index remains internal; only a geometry-bound canonical name may leave the engine.
    corner_identity: dict[str, Any] = field(
        default_factory=lambda: {
            "ready": False,
            "reason": "canonical_catalog_unavailable",
            "labels": {},
            "eligible_count": 0,
        }
    )
    corner_identity_generation: int = 0
    #: per-corner driver brake action-point EMA (issue #675 Parts 0/3): (spline, n_laps).
    _driver_brake_points: dict[int, tuple[float, int]] = field(default_factory=dict)
    _rolling_best_lap_ms: float | None = None
    #: Part 4 — when the active reference is slower than the driver's rolling best, reference-
    #: derived brake/turn cues are suppressed (visible via :attr:`cue_suppress_reason`).
    _off_pace_reference: bool = False
    cue_suppress_reason: str = ""
    _active_cond_reason: str = ""
    _active_brake_reason: str = ""
    _active_tyre_reason: str = ""
    _active_ineligible_reason: str = ""
    _pass: dict[int, _PassState] = field(default_factory=dict)
    _last_spline: float | None = None
    _last_lap: float | None = None
    _lap: int = 1
    _pending_wrap_finals: bool = False
    _pending_pre_lap: float | None = None

    def __post_init__(self) -> None:
        if self.capability_gate_mode not in _CAPABILITY_GATE_MODES:
            raise ValueError(
                f"capability_gate_mode must be one of {sorted(_CAPABILITY_GATE_MODES)}, "
                f"got {self.capability_gate_mode!r}"
            )
        self.refs = sorted(self.refs, key=lambda r: r.spline_lo)
        self._pass = {r.index: _PassState() for r in self.refs}
        self.ledger.begin_lap(self._lap)

    def _set_suppress_reason(self, reason: str) -> None:
        """Assign a public `/health`-safe lowercase machine code (`[a-z0-9_]+`) or `""` (#938)."""
        if not reason:
            self.cue_suppress_reason = (
                "reference_slower_than_rolling_best" if self._off_pace_reference else ""
            )
            return
        clean = reason.strip().lower()
        self.cue_suppress_reason = (
            clean if _MACHINE_CODE_RE.fullmatch(clean) else "capability_gate_suppressed"
        )

    def reset(self) -> None:
        """Clear ALL session state — call on pit-exit / producer reconnect / session restart (B4).

        Without this, stale ``_lap``/``_last_spline``/per-corner passes + a RETIRED ledger carry
        across stints, which silently suppresses cues until the sidecar process is restarted.
        Per-driver brake calibration and the rolling-best / off-pace gate persist
        (driver knowledge).
        """
        self.ledger.clear_session()
        self.set_corner_identity(
            {
                "ready": False,
                "reason": "canonical_catalog_unavailable",
                "labels": {},
                "eligible_count": 0,
            }
        )
        self._pass = {r.index: _PassState() for r in self.refs}
        self.last_pass_capability.clear()
        self._active_cond_reason = ""
        self._active_brake_reason = ""
        self._active_tyre_reason = ""
        self._active_ineligible_reason = ""
        self._set_suppress_reason("")
        self._last_spline = None
        self._last_lap = None
        self._lap = 1
        self._pending_wrap_finals = False
        self._pending_pre_lap = None
        self.ledger.begin_lap(self._lap)

    def set_corner_identity(self, binding: dict[str, Any]) -> None:
        if binding != self.corner_identity:
            self.corner_identity = binding
            self.corner_identity_generation += 1

    def named_advisory(self, advisory: Advisory) -> Advisory | None:
        """The single output gate for Coach v2 cues, including voice and rules commands."""
        label = self.corner_identity.get("labels", {}).get(advisory.corner)
        return replace(advisory, corner=int(label[1:]) - 1) if label else None

    def note_completed_lap(self, lap_time_ms: float | None, *, is_valid: bool = True) -> None:
        """Fold a finished lap into the rolling-best / off-pace-reference gate (#675 Part 4)."""
        if not is_valid or lap_time_ms is None:
            return
        try:
            ms = float(lap_time_ms)
        except (TypeError, ValueError):
            return
        if ms <= 0.0 or ms != ms:
            return
        if self._rolling_best_lap_ms is None or ms < self._rolling_best_lap_ms:
            self._rolling_best_lap_ms = ms
        self._refresh_off_pace_gate()

    def _refresh_off_pace_gate(self) -> None:
        ref = self.reference_lap_ms
        best = self._rolling_best_lap_ms
        if ref is None or best is None:
            self._off_pace_reference = False
            self.cue_suppress_reason = ""
            return
        if ref > best:
            self._off_pace_reference = True
            self.cue_suppress_reason = "reference_slower_than_rolling_best"
        else:
            self._off_pace_reference = False
            self.cue_suppress_reason = ""

    def calibrate_from_driver_lap(
        self,
        lap: LapTrace,
        *,
        track_id: str | None = None,
        track_layout: str | None = None,
    ) -> int:
        """Fold one valid driver lap into per-corner brake action-point EMAs (#675 Parts 0/3).

        Mirrors :meth:`RealtimeObserver.calibrate_from_driver_lap` guards (track/layout match,
        metric tolerance, EMA alpha) but updates the v2 cue producer: PRIME brake anchors and the
        SAVE ``brake_point_spline`` on :attr:`ref_sigs`. Returns the number of corners updated.
        """
        if track_id and self.track_id and track_id != self.track_id:
            return 0
        if track_layout and self.track_layout and track_layout != self.track_layout:
            return 0
        tol = CAL_MATCH_TOL_M / max(self.track_length_m, 1.0)
        updated = 0
        for ref in self.refs:
            sig = self.ref_sigs.get(ref.index)
            if sig is None or sig.brake_point_spline is None:
                continue
            cur = self._driver_brake_points.get(ref.index)
            anchor = cur[0] if cur is not None else sig.brake_point_spline
            lo_a, hi_a = anchor - tol, anchor + 2.0 * tol
            if lo_a < 0.0:
                windows = [(lo_a % 1.0, 1.0), (0.0, hi_a)]
            elif hi_a > 1.0:
                windows = [(lo_a, 1.0), (0.0, hi_a % 1.0)]
            else:
                windows = [(lo_a, hi_a)]
            onsets: list[float] = []
            seen: set[float] = set()
            for w_lo, w_hi in windows:
                for onset in sustained_brake_onsets(lap, w_lo, w_hi):
                    if onset not in seen:
                        seen.add(onset)
                        onsets.append(onset)
            if not onsets:
                continue
            best = min(onsets, key=lambda o: abs(_signed_spline_delta(o, anchor)))
            if abs(_signed_spline_delta(best, anchor)) > tol:
                continue
            if cur is None:
                candidate = best % 1.0
                n = 1
            else:
                ema, n_prev = cur
                candidate = (ema + _CAL_EMA_ALPHA * _signed_spline_delta(best, ema)) % 1.0
                n = n_prev + 1
            self._driver_brake_points[ref.index] = (candidate, n)
            self._apply_brake_calibration(ref.index, candidate)
            updated += 1
        return updated

    def _apply_brake_calibration(self, corner_idx: int, brake_point: float) -> None:
        """Move the PRIME fire point and SAVE action point to a calibrated brake mark."""
        sig = self.ref_sigs.get(corner_idx)
        v_ref = sig.entry_speed_kmh if sig is not None else 150.0
        lead = _lead_spline(v_ref, self.track_length_m, self.brake_lead_s)
        anc = self.anchors.get(corner_idx)
        if anc is not None:
            anc.brake = (brake_point - lead) % 1.0
        if sig is not None:
            self.ref_sigs[corner_idx] = replace(sig, brake_point_spline=brake_point % 1.0)

    def _advance_lap_after_wrap(self, out: list[Advisory]) -> None:
        """Finalize open passes, then advance the ledger lap (speak-set needs fresh diagnoses)."""
        for r in self.refs:
            if self._pass[r.index].active:
                out.extend(self._finalize_pass(r))
        self._lap += 1
        self.ledger.begin_lap(self._lap)

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        spline, speed, brake, throttle, steer, lap, grip = _normalize(
            frame,
            ggv_model=self.ggv_model,
            mode=self.capability_gate_mode,
        )
        if spline is None or speed is None:
            return []
        cap = _evaluate_frame_capability(
            frame,
            speed_kmh=speed,
            ggv_model=self.ggv_model,
            mode=self.capability_gate_mode,
            default_compound=self.reference_compound,
            default_optimal_temp_c=self.reference_optimal_temp_c,
        )
        if cap.has_cond_evidence:
            self._active_cond_reason = cap.cond_reason
        if cap.has_brake_evidence:
            self._active_brake_reason = cap.brake_reason
        if cap.has_tyre_evidence:
            self._active_tyre_reason = cap.tyre_reason
        if cap.has_thermal_evidence:
            self._active_ineligible_reason = (
                self._active_cond_reason or self._active_brake_reason or self._active_tyre_reason
            )
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
            # Part 4 off-pace and #938 thermal/condition abstention: advance ledger state
            # (due_prime spends budget) but abstain from demand-increasing PRIME cues when the
            # reference is slower or tyres/brakes/conditions are out of window.
            root = self.ledger.armed_root(r.index)
            if root is not None and _crossed(self._last_spline, spline, anc.for_root(root)):
                ineligible_reason = cap.ineligible_reason or self._active_ineligible_reason
                if (
                    not ineligible_reason
                    and self.capability_gate_mode == "condition_indexed"
                    and root in _GRIP_GATED_ROOTS
                ):
                    frame_util = cap.entry_util if root is RootError.EARLY_BRAKE else cap.lat_util
                    prev_cap = self.last_pass_capability.get(r.index) or {}
                    prev_key = (
                        "max_entry_grip_used"
                        if root is RootError.EARLY_BRAKE
                        else "max_lat_grip_used"
                    )
                    prev_util = _finite_float(prev_cap.get(prev_key)) or 0.0
                    if (
                        frame_util is not None and frame_util >= _GRIP_GATE_FRAC
                    ) or prev_util >= _GRIP_GATE_FRAC:
                        ineligible_reason = "grip_envelope_saturated"
                prime_gated = (
                    self.capability_gate_mode == "condition_indexed"
                    and root in _GRIP_GATED_ROOTS
                    and bool(ineligible_reason)
                )
                if prime_gated:
                    self._set_suppress_reason(ineligible_reason)
                else:
                    spoken = self.ledger.due_prime(r.index)
                    if spoken is not None and not self._off_pace_reference:
                        if spoken in _GRIP_GATED_ROOTS:
                            self._set_suppress_reason("")
                        gst = self.ledger.state(r.index)
                        reg = gst.register if gst else "urgent"
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
                if st.active:
                    if cap.lat_util is not None:
                        st.has_grip_evidence = True
                        st.max_lat_grip_used = max(st.max_lat_grip_used, cap.lat_util)
                        st.max_grip_used = max(st.max_grip_used, cap.lat_util)
                    if cap.entry_util is not None and spline <= r.apex_spline:
                        st.has_grip_evidence = True
                        st.max_entry_grip_used = max(st.max_entry_grip_used, cap.entry_util)
                    elif cap.lat_util is None and grip is not None:
                        st.has_grip_evidence = True
                        st.max_grip_used = max(st.max_grip_used, grip)
                    if cap.has_thermal_evidence:
                        st.has_thermal_evidence = True
                    if cap.has_cond_evidence or cap.has_brake_evidence or cap.has_tyre_evidence:
                        st.ineligible_reason = self._active_ineligible_reason

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
        # Suppressed under Part 4 off-pace (would coach toward a slower reference).
        ref_sig = self.ref_sigs.get(r.index)
        ref_bp = ref_sig.brake_point_spline if ref_sig else None
        if (
            not self._off_pace_reference
            and not st.save_fired
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
        diag = _classify_for_policy(sig, ref_sig, self.cue_policy)
        if st.has_grip_evidence and st.has_thermal_evidence:
            evidence_quality = "full"
        elif st.has_grip_evidence:
            evidence_quality = "kinematic_only"
        elif st.has_thermal_evidence:
            evidence_quality = "thermal_only"
        else:
            evidence_quality = "missing"
        self.last_pass_capability[r.index] = {
            "evidence_quality": evidence_quality,
            "max_grip_used": round(st.max_grip_used, 3),
            "max_lat_grip_used": round(st.max_lat_grip_used, 3),
            "max_entry_grip_used": round(st.max_entry_grip_used, 3),
            "ineligible_reason": st.ineligible_reason,
        }
        # CONDITION-INDEXED CAPABILITY & THERMAL GATE (#938 / P3):
        # 1. Thermal/condition eligibility: when tyres/brakes are out of window or regime is wet,
        #    demand-increasing roots (EARLY_BRAKE, SLOW_APEX) abstain.
        # 2. Envelope saturation: EARLY_BRAKE checks corner-entry combined braking/turn-in
        #    utilization against the combo GGVModel friction ellipse; SLOW_APEX checks speed-
        #    indexed lateral utilization against GGVModel.ay_max(v). Missing telemetry channels
        #    stay fail-open without fabricating saturation.
        gated_abstain = False
        if diag.root in _GRIP_GATED_ROOTS:
            pass_ineligible = st.ineligible_reason or self._active_ineligible_reason
            if self.capability_gate_mode == "condition_indexed" and pass_ineligible:
                self._set_suppress_reason(pass_ineligible)
                gated_abstain = True
                diag = Diagnosis(
                    RootError.NONE,
                    {
                        "capability_gated": 1.0,
                        "reason": pass_ineligible,
                        "evidence_quality": evidence_quality,
                    },
                )
            else:
                if (
                    self.capability_gate_mode == "condition_indexed"
                    and diag.root is RootError.EARLY_BRAKE
                ):
                    used = st.max_entry_grip_used if st.has_grip_evidence else st.max_grip_used
                else:
                    used = st.max_lat_grip_used if st.has_grip_evidence else st.max_grip_used
                if used >= _GRIP_GATE_FRAC:
                    if self.capability_gate_mode == "condition_indexed":
                        self._set_suppress_reason("grip_envelope_saturated")
                    gated_abstain = True
                    diag = Diagnosis(
                        RootError.NONE,
                        {
                            "grip_gated": round(used, 3),
                            "evidence_quality": evidence_quality,
                        },
                    )
                elif not self._off_pace_reference:
                    self._set_suppress_reason("")
        # time-lost proxy: apex-speed deficit (km/h) stands in until lap-time deltas are wired
        time_lost = max(0.0, ref_sig.min_speed_kmh - st.min_speed_kmh)
        # Validity gate (B3): a pass that never reached a plausible apex (no entry samples, or the
        # min-speed sentinel never beaten) is an out-lap / pit / teleport / partial pass — do NOT
        # let it poison the ledger. Likewise, capability/thermal abstention holds existing ledger
        # state unchanged (valid=False) rather than recording a false clean pass ('Good.').
        valid = st.entry_count > 0 and st.min_speed_kmh < 1e9 and not gated_abstain
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


def _classify_for_policy(
    sig: CornerSignature,
    ref_sig: CornerSignature,
    cue_policy: DriverCuePolicy,
) -> Diagnosis:
    diag = classify_root_error(sig, ref_sig)
    if cue_policy.allows(diag.root):
        return diag
    if diag.root is RootError.NO_TRAIL:
        apex_deficit = ref_sig.min_speed_kmh - sig.min_speed_kmh
        if cue_policy.allows(RootError.SLOW_APEX) and apex_deficit >= APEX_KMH_FLOOR:
            return Diagnosis(RootError.SLOW_APEX, {"apex_deficit_kmh": round(apex_deficit, 1)})
        if sig.throttle_on_spline is not None and ref_sig.throttle_on_spline is not None:
            throttle_delta = sig.throttle_on_spline - ref_sig.throttle_on_spline
            if (
                cue_policy.allows(RootError.LATE_THROTTLE)
                and throttle_delta > THROTTLE_SPLINE_FLOOR
            ):
                return Diagnosis(
                    RootError.LATE_THROTTLE, {"throttle_delta": round(throttle_delta, 4)}
                )
    return Diagnosis(RootError.NONE, {"skill_gated": 1.0})


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
    register: str = "urgent",
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


def _finite_float(value: Any) -> float | None:
    """Return a finite float for ``value``, rejecting ``bool``, ``None``, ``NaN``, and ``±inf``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _sanitize_corner_map(raw: Any) -> dict[str, float] | None:
    """Return a sanitized ``{fl, fr, rl, rr}`` float dict, rejecting bool/NaN/±inf."""
    if isinstance(raw, Mapping):
        out: dict[str, float] = {}
        for wheel in _WHEELS:
            f = _finite_float(raw.get(wheel))
            if f is not None:
                out[wheel] = f
        return out or None
    return None


def _extract_frame_conditions(
    frame: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None, float | None]:
    """Extract sanitized conditions dict, tyre compound, and optimal temp from a frame."""
    nested = payload.get("conditions")
    if not isinstance(nested, Mapping):
        nested = frame.get("conditions") if isinstance(frame.get("conditions"), Mapping) else {}

    def pick_cond(*keys: str) -> Any:
        for src in (nested, payload, frame):
            if isinstance(src, Mapping):
                for k in keys:
                    if k in src:
                        return src[k]
        return None

    cond: dict[str, Any] = {}
    grip = _finite_float(pick_cond("trackGripLevel", "track_grip_level"))
    if grip is not None:
        cond["trackGripLevel"] = grip
    track_temp = _finite_float(pick_cond("trackTempC", "track_temp_c"))
    if track_temp is not None:
        cond["trackTempC"] = track_temp
    ambient_temp = _finite_float(pick_cond("ambientTempC", "ambient_temp_c"))
    if ambient_temp is not None:
        cond["ambientTempC"] = ambient_temp
    weather = pick_cond("weatherType", "weather_type")
    if isinstance(weather, str) and weather.strip():
        cond["weatherType"] = weather.strip()

    compound_raw = pick_cond("tyreCompound", "tyre_compound", "tire_compound")
    compound = (
        compound_raw.strip() if isinstance(compound_raw, str) and compound_raw.strip() else None
    )
    opt_temp = _finite_float(pick_cond("optimalTempC", "tyre_optimal_temp_c", "optimal_temp_c"))
    if opt_temp is not None and opt_temp <= 0.0:
        opt_temp = None

    return (cond if cond else None), compound, opt_temp


def _evaluate_frame_capability(
    frame: dict[str, Any],
    *,
    speed_kmh: float | None,
    ggv_model: GGVModel,
    mode: str = "condition_indexed",
    default_compound: str | None = None,
    default_optimal_temp_c: float | None = None,
) -> _FrameCapability:
    """Evaluate per-frame capability envelope utilization and thermal/condition eligibility (#938).

    Thermal and condition states act strictly as eligibility/abstention gates (never uncalibrated
    friction multipliers). Missing channels remain fail-open and record their absence via
    ``has_grip_evidence`` / ``has_thermal_evidence``.
    """
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}

    def pick(*keys: str) -> Any:
        for src in (frame, payload):
            for k in keys:
                if k in src:
                    return src[k]
        return None

    v_ms = max(0.0, (speed_kmh or 0.0) / 3.6)
    direct_grip = _finite_float(pick("grip", "grip_used"))
    lat_g = _finite_float(pick("lat_g", "latg", "accG_lat", "accg_lat", "accG"))
    long_g = _finite_float(
        pick("long_g", "longg", "accG_long", "accg_long", "accG_lon", "accg_lon")
    )

    lat_util: float | None = None
    entry_util: float | None = None
    has_grip_evidence = False

    if direct_grip is not None and direct_grip >= 0.0:
        lat_util = direct_grip
        entry_util = direct_grip
        has_grip_evidence = True
    elif lat_g is not None:
        has_grip_evidence = True
        if mode == "baseline":
            lat_util = abs(lat_g) / _BASELINE_GRIP_CEILING_G
            entry_util = lat_util
        else:
            ay_cap_g = max(0.3, ggv_model.ay_max(v_ms) / _G_ACCEL)
            lat_util = abs(lat_g) / ay_cap_g
            if mode == "condition_indexed" and long_g is not None and long_g < 0.0:
                ax_brake_cap_g = max(0.3, ggv_model.ax_brake_max(v_ms) / _G_ACCEL)
                brake_util = max(0.0, -long_g) / ax_brake_cap_g
                n = max(1.0, min(2.5, _finite_float(ggv_model.ellipse_n) or 1.5))
                combined = ((lat_util**n) + (brake_util**n)) ** (1.0 / n)
                entry_util = max(lat_util, combined)
            else:
                entry_util = lat_util
    elif mode == "condition_indexed" and long_g is not None and long_g < 0.0:
        has_grip_evidence = True
        ax_brake_cap_g = max(0.3, ggv_model.ax_brake_max(v_ms) / _G_ACCEL)
        entry_util = max(0.0, -long_g) / ax_brake_cap_g

    if mode != "condition_indexed":
        return _FrameCapability(
            lat_util=lat_util,
            entry_util=entry_util,
            has_grip_evidence=has_grip_evidence,
            has_thermal_evidence=False,
            ineligible_reason="",
        )

    tyre_temps = _sanitize_corner_map(pick("tyre_temps_c", "tire_temps_c"))
    brake_temps = _sanitize_corner_map(pick("brake_temps_c", "brake_temp_c"))
    cond_dict, frame_compound, frame_opt_temp = _extract_frame_conditions(frame, payload)
    has_cond_evidence = False
    has_brake_evidence = bool(brake_temps)
    has_tyre_evidence = bool(tyre_temps)
    has_thermal_evidence = bool(cond_dict is not None or has_brake_evidence or has_tyre_evidence)
    cond_reason = ""
    brake_reason = ""
    tyre_reason = ""

    if cond_dict is not None:
        cond_report = analyze_conditions(cond_dict)
        if cond_report.regime in {"wet", "dry"}:
            has_cond_evidence = True
        if cond_report.regime == "wet":
            cond_reason = "wet_regime"

    if brake_temps:
        max_brake_c = max(brake_temps.values())
        if max_brake_c >= _BRAKE_CRITICAL_C:
            brake_reason = "brake_temp_critical"
        elif max_brake_c >= _BRAKE_HOT_C:
            brake_reason = "brake_temp_overheat"

    if tyre_temps:
        tyre_report = analyze_tyres(
            tyre_temps,
            compound=frame_compound or default_compound,
            optimal_temp_c=frame_opt_temp or default_optimal_temp_c,
        )
        statuses = set(tyre_report.status.values())
        if "critical" in statuses:
            tyre_reason = "tyre_temp_critical"
        elif "overheat" in statuses:
            tyre_reason = "tyre_temp_overheat"
        elif "cold" in statuses or "warming" in statuses:
            tyre_reason = "tyre_temp_cold"

    ineligible_reason = cond_reason or brake_reason or tyre_reason

    return _FrameCapability(
        lat_util=lat_util,
        entry_util=entry_util,
        has_grip_evidence=has_grip_evidence,
        has_thermal_evidence=has_thermal_evidence,
        has_cond_evidence=has_cond_evidence,
        has_brake_evidence=has_brake_evidence,
        has_tyre_evidence=has_tyre_evidence,
        cond_reason=cond_reason,
        brake_reason=brake_reason,
        tyre_reason=tyre_reason,
        ineligible_reason=ineligible_reason,
    )


def _normalize(
    frame: dict[str, Any],
    *,
    ggv_model: GGVModel | None = None,
    mode: str = "condition_indexed",
) -> tuple[float | None, float | None, float, float, float, float | None, float | None]:
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}

    def pick(*keys: str) -> Any:
        for src in (frame, payload):
            for k in keys:
                if k in src:
                    return src[k]
        return None

    def num(v: Any, default: float = 0.0) -> float:
        f = _finite_float(v)
        return default if f is None else f

    raw_spline = pick("spline", "normalizedSplinePosition")
    raw_speed = pick("speed", "speed_kmh")
    spline = _finite_float(raw_spline)
    speed = _finite_float(raw_speed)
    raw_lap = pick("lap", "lapCount", "lap_count", "completedLaps")
    lap = _finite_float(raw_lap)

    # grip utilisation: a direct fraction if supplied, else derived against the combo GGVModel
    # (or legacy _BASELINE_GRIP_CEILING_G in baseline mode). None when the frame carries neither.
    grip = _finite_float(pick("grip", "grip_used"))
    if grip is None:
        latg = _finite_float(pick("lat_g", "latg", "accG_lat", "accg_lat", "accG"))
        if latg is not None:
            if mode == "baseline" or ggv_model is None:
                denom_g = _BASELINE_GRIP_CEILING_G
            else:
                v_ms = max(0.0, (speed or 0.0) / 3.6)
                denom_g = max(0.3, ggv_model.ay_max(v_ms) / _G_ACCEL)
            grip = abs(latg) / denom_g
    return (
        spline,
        speed,
        num(pick("brake")),
        num(pick("throttle", "gas")),
        num(pick("steer")),
        lap,
        grip,
    )


def _derive_combo_ggv(
    reference_archive: Mapping[str, Any],
    ref_lap: LapTrace,
) -> GGVModel:
    """Derive a combo-specific :class:`GGVModel` from the reference archive or trace (#938)."""
    raw_ggv = reference_archive.get("ggv")
    if not isinstance(raw_ggv, Mapping):
        car_obj = reference_archive.get("car")
        if isinstance(car_obj, Mapping) and isinstance(car_obj.get("ggv"), Mapping):
            raw_ggv = car_obj.get("ggv")
    if isinstance(raw_ggv, Mapping):
        try:
            return GGVModel.from_dict(dict(raw_ggv))
        except (TypeError, ValueError):
            pass

    accg_lat_series = getattr(ref_lap, "accg_lat", None)
    if not isinstance(accg_lat_series, list | tuple) or len(accg_lat_series) != len(ref_lap):
        return _default_ggv_model()
    accg_long_series = getattr(ref_lap, "accg_long", None)
    lon_source = (
        accg_long_series
        if isinstance(accg_long_series, list | tuple) and len(accg_long_series) == len(ref_lap)
        else ref_lap.long_g
    )

    samples: list[dict[str, float]] = []
    n_samples = len(ref_lap)
    for i in range(n_samples):
        v_kmh = _finite_float(ref_lap.v_kmh[i]) or 0.0
        lat_g = _finite_float(accg_lat_series[i]) or 0.0
        long_g = _finite_float(lon_source[i]) or 0.0
        samples.append(
            {
                "speed_kmh": max(0.0, v_kmh),
                "accg_lat": lat_g,
                "accg_lon": long_g,
            }
        )

    model = ggv_from_telemetry(
        samples,
        min_corner_lat_g=0.55,
        min_samples=10,
    )
    prov = model.provenance if isinstance(model.provenance, dict) else {}
    mu_lat_g = model.mu_lat_g
    brake_b0_g = model.brake_b0_g
    brake_b1 = model.brake_b1
    updated = False
    if int(prov.get("lat_corner_bins") or 0) == 0:
        corner_lat = sorted(
            abs(_finite_float(g) or 0.0)
            for g in accg_lat_series
            if abs(_finite_float(g) or 0.0) >= 0.45
        )
        if corner_lat:
            idx_lat = min(len(corner_lat) - 1, int(0.95 * (len(corner_lat) - 1)))
            mu_lat_g = round(max(0.60, corner_lat[idx_lat]), 4)
            updated = True
    if not prov.get("brake_fit_valid"):
        brake_lon = sorted(
            max(0.0, -(_finite_float(g) or 0.0))
            for g, b in zip(lon_source, ref_lap.brake, strict=False)
            if (_finite_float(b) or 0.0) >= 0.2 and -(_finite_float(g) or 0.0) >= 0.35
        )
        if brake_lon:
            idx_brk = min(len(brake_lon) - 1, int(0.95 * (len(brake_lon) - 1)))
            brake_b0_g = round(max(0.60, brake_lon[idx_brk]), 4)
            brake_b1 = 0.0
            updated = True
        else:
            brake_b0_g = round(max(0.60, mu_lat_g * 1.05), 4)
            brake_b1 = 0.0
            updated = True
    if updated:
        model = replace(model, mu_lat_g=mu_lat_g, brake_b0_g=brake_b0_g, brake_b1=brake_b1)
    return model


def _profile_for_runtime(
    driver_profile: Mapping[str, Any] | None,
    driver_profile_path: str | Path | None,
) -> Mapping[str, Any] | None:
    if driver_profile is not None:
        return sanitize_profile(driver_profile)
    configured = driver_profile_path or os.environ.get("AC_COPILOT_DRIVER_PROFILE")
    path = Path(configured) if configured else DEFAULT_PROFILE_PATH
    if not path.exists() and configured is None:
        return None
    return load_profile(path)


def _combo_text(value: Any) -> str:
    return str(value or "")


def _archive_combo(reference_archive: Mapping[str, Any]) -> tuple[str, str, str] | None:
    car = reference_archive.get("car") if isinstance(reference_archive.get("car"), Mapping) else {}
    track = (
        reference_archive.get("track")
        if isinstance(reference_archive.get("track"), Mapping)
        else {}
    )
    car_id = car.get("id") or car.get("car_id")
    track_id = track.get("id") or track.get("track_id")
    if not car_id or not track_id:
        return None
    return (_combo_text(car_id), _combo_text(track_id), _combo_text(track.get("layout")))


def _row_matches_combo(row: Mapping[str, Any], combo: tuple[str, str, str]) -> bool:
    car_id, track_id, track_layout = combo
    return (
        _combo_text(row.get("car_id")) == car_id
        and _combo_text(row.get("track_id")) == track_id
        and _combo_text(row.get("track_layout")) == track_layout
    )


def _profile_for_reference_combo(
    profile: Mapping[str, Any] | None, reference_archive: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    if not isinstance(profile, Mapping):
        return profile
    combo = _archive_combo(reference_archive)
    if combo is None:
        return None
    filtered = dict(profile)
    for key in ("corner_history", "consistency", "session_rollups", "personal_bests"):
        rows = profile.get(key)
        if not isinstance(rows, Mapping):
            filtered[key] = {}
            continue
        filtered[key] = {
            row_key: row
            for row_key, row in rows.items()
            if isinstance(row, Mapping) and _row_matches_combo(row, combo)
        }
    return filtered


def build_coach_runtime(
    reference_archive: dict,
    *,
    lead_s: float = _DEFAULT_LEAD_S,
    driver_profile: Mapping[str, Any] | None = None,
    driver_profile_path: str | Path | None = None,
    alien_line_path: str | Path | None = None,
    alien_line_artifact: Mapping[str, Any] | None = None,
    alien_expected_plant_sha12: str | None = None,
    alien_expected_fast_lane_sha12: str | None = None,
    expected_combo: tuple[str, str, str | None] | None = None,
    diagnostics: dict[str, Any] | None = None,
    use_environment: bool = True,
    ggv_model: GGVModel | None = None,
    capability_gate_mode: str = "condition_indexed",
) -> CoachRuntime | None:
    """Build a :class:`CoachRuntime` from a reference archive (same input as the observer).

    ``use_environment=False`` is the offline seam: no ambient profile, alien source
    or pacing overrides. Explicit arguments and canonical attribution still apply.
    """
    qualification = qualify_archive(
        reference_archive, use="live_reference", expected_combo=expected_combo
    )
    if diagnostics is not None:
        diagnostics.update(allowed=qualification.allowed, reason=qualification.reason)
    if not qualification.allowed:
        return None
    if diagnostics is not None:
        diagnostics.update(allowed=False, reason="reference_trace_unavailable")
    generator = reference_archive.get("generator") or {}
    tt_reference = generator.get("tt_reference") if isinstance(generator, dict) else None
    if isinstance(tt_reference, dict) and tt_reference.get("partial") is True:
        if diagnostics is not None:
            diagnostics.update(allowed=False, reason="partial_tt_reference")
        return None
    try:
        ref_lap = lap_trace_from_archive(reference_archive)
    except ValueError:
        return None
    refs = build_references(ref_lap)
    if not refs:
        if diagnostics is not None:
            diagnostics["reason"] = "reference_corners_unavailable"
        return None
    geom = {s.index: s for s in corner_signatures(ref_lap)}  # for anchor timing only
    track_obj = reference_archive.get("track")
    track_m = _DEFAULT_TRACK_M
    track_id: str | None = None
    track_layout: str | None = None
    if isinstance(track_obj, dict):
        try:
            track_m = float(track_obj.get("lengthM") or _DEFAULT_TRACK_M)
        except (TypeError, ValueError):
            track_m = _DEFAULT_TRACK_M
        tid = track_obj.get("id")
        track_id = tid if isinstance(tid, str) and tid.strip() else None
        tlayout = track_obj.get("layout")
        track_layout = tlayout if isinstance(tlayout, str) and tlayout.strip() else None
    reference_lap_ms = _archive_lap_ms(reference_archive)
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
    profile = _profile_for_reference_combo(
        _profile_for_runtime(
            {}
            if not use_environment and driver_profile is None and driver_profile_path is None
            else driver_profile,
            driver_profile_path,
        ),
        reference_archive,
    )
    profile_source = profile.get("source") if isinstance(profile, Mapping) else None
    if (
        diagnostics is not None
        and isinstance(profile_source, Mapping)
        and profile_source.get("rebuild_required") is True
    ):
        diagnostics["driver_profile"] = {
            "rebuild_required": True,
            "reasons": profile_source.get("skipped", []),
        }
    policy = cue_policy_from_profile(profile)
    frontier: dict[str, Any] = {
        "configured": False,
        "active": False,
        "source": "reference",
        "reason": "not_configured",
        "corners": [],
    }
    configured_alien = alien_line_path or (
        os.environ.get("AC_COPILOT_ALIEN_LINE") if use_environment else None
    )
    combo = _archive_combo(reference_archive)
    artifact = alien_line_artifact
    if artifact is None and configured_alien:
        from tools.ai_sidecar.coachable_frontier import (
            FrontierError,
            frontier_fallback,
            load_verified_alien_evidence,
        )

        if combo is None:
            frontier = frontier_fallback("reference_combo_missing")
        else:
            try:
                artifact, alien_expected_plant_sha12, alien_expected_fast_lane_sha12 = (
                    load_verified_alien_evidence(
                        configured_alien,
                        combo=combo,
                        plant_path=(
                            os.environ.get("AC_COPILOT_ALIEN_PLANT") if use_environment else None
                        ),
                        fast_lane_path=(
                            os.environ.get("AC_COPILOT_ALIEN_FAST_LANE")
                            if use_environment
                            else None
                        ),
                        ac_root=(os.environ.get("AC_COPILOT_AC_ROOT") if use_environment else None),
                    )
                )
            except FrontierError as exc:
                frontier = frontier_fallback(str(exc))
    elif artifact is not None and (
        not isinstance(artifact, Mapping)
        or not alien_expected_plant_sha12
        or not alien_expected_fast_lane_sha12
    ):
        from tools.ai_sidecar.coachable_frontier import frontier_fallback

        frontier = frontier_fallback("alien_injected_evidence_unverified")
        artifact = None
    if artifact is not None:
        from tools.ai_sidecar.coachable_frontier import (
            FrontierError,
            derive_coachable_frontier,
            frontier_fallback,
        )

        if combo is None:
            frontier = frontier_fallback("reference_combo_missing")
        else:
            try:
                frontier = derive_coachable_frontier(
                    refs,
                    artifact,
                    combo=combo,
                    profile=profile,
                    driver_level=policy.level,
                    reference_brake_points={
                        index: signature.brake_point_spline for index, signature in ref_sigs.items()
                    },
                    expected_plant_sha12=alien_expected_plant_sha12 or "",
                    expected_fast_lane_sha12=alien_expected_fast_lane_sha12 or "",
                )
            except FrontierError as exc:
                frontier = frontier_fallback(str(exc))

    # Only minimum speed is borrowed from the derived frontier. All other signature fields remain
    # the human reference technique, which is the central safety/coachability invariant for P5.
    for ref in refs:
        if ref.coachable_apex_kmh is not None and ref.index in ref_sigs:
            ref_sigs[ref.index] = replace(ref_sigs[ref.index], min_speed_kmh=ref.coachable_apex_kmh)
    ledger = CoachingLedger(
        hysteresis=(
            _env_int("AC_COPILOT_COACH_HYSTERESIS", policy.hysteresis, min_value=1)
            if use_environment
            else policy.hysteresis
        ),
        assess_laps=(
            _env_int("AC_COPILOT_COACH_ASSESS_LAPS", policy.assess_laps, min_value=0)
            if use_environment
            else policy.assess_laps
        ),
        lap_budget=(
            _env_int("AC_COPILOT_COACH_LAP_BUDGET", policy.lap_budget, min_value=1)
            if use_environment
            else policy.lap_budget
        ),
    )
    resolved_ggv = ggv_model or _derive_combo_ggv(reference_archive, ref_lap)
    car_meta = (
        reference_archive.get("car") if isinstance(reference_archive.get("car"), Mapping) else {}
    )
    cond_meta = (
        reference_archive.get("conditions")
        if isinstance(reference_archive.get("conditions"), Mapping)
        else {}
    )
    _, ref_compound, ref_opt_temp = _extract_frame_conditions(
        {"conditions": cond_meta},
        dict(car_meta),
    )
    if diagnostics is not None:
        diagnostics.update(allowed=True, reason=qualification.reason)
    return CoachRuntime(
        refs=refs,
        ref_sigs=ref_sigs,
        anchors=anchors,
        track_length_m=track_m,
        ledger=ledger,
        cue_policy=policy,
        frontier=frontier,
        brake_lead_s=lead_s,
        track_id=track_id,
        track_layout=track_layout,
        reference_lap_ms=reference_lap_ms,
        ggv_model=resolved_ggv,
        capability_gate_mode=capability_gate_mode,
        reference_compound=ref_compound,
        reference_optimal_temp_c=ref_opt_temp,
    )


def _archive_lap_ms(archive: Mapping[str, Any]) -> float | None:
    """Best-effort lap time (ms) from a reference/driver archive ``lap`` block."""
    lap = archive.get("lap")
    if not isinstance(lap, Mapping):
        return None
    for key in ("lap_ms", "lapTimeMs", "time_ms", "lap_time_ms"):
        raw = lap.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            ms = float(raw)
        except (TypeError, ValueError):
            continue
        if ms > 0.0 and ms == ms:
            return ms
    return None


def _env_int(name: str, default: int, *, min_value: int = 0) -> int:
    """Env int with a floor (n7): an unvalidated 0/negative budget or hysteresis silently breaks
    pacing, so clamp rather than trust the operator."""
    try:
        return max(min_value, int(os.environ[name]))
    except (KeyError, ValueError):
        return default
