"""Stint-level race-management cues from live telemetry.

This module is deliberately independent of the corner coach engines. The sidecar can run the
legacy ``RealtimeObserver`` or Coach v2; fuel, tyre, brake, and condition management should ride
along either way. The model is pure stdlib and conservative: it emits only when the live frame
carries the required channel, and every advisory detail records the measured/estimated basis.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from tools.ai_sidecar.conditions_model import ConditionsFinding, analyze_conditions
from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.tyre_model import TyreFinding, analyze_tyres

_WHEELS = ("fl", "fr", "rl", "rr")

_MIN_FUEL_LAP_USE_L = 0.05
_FUEL_SHORT_MARGIN_LAPS = 0.25
_FUEL_CRITICAL_DEFICIT_LAPS = 1.0
_FUEL_SAMPLE_WINDOW = 5

_WEAR_CAUTION_PCT = 70.0
_BRAKE_HOT_C = 650.0
_BRAKE_CRITICAL_C = 850.0


def _payload(frame: dict[str, Any]) -> dict[str, Any]:
    return frame.get("payload") if isinstance(frame.get("payload"), dict) else {}


def _pick(frame: dict[str, Any], *keys: str) -> Any:
    payload = _payload(frame)
    for src in (frame, payload):
        for key in keys:
            if key in src:
                return src[key]
    return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _lap(frame: dict[str, Any]) -> int | None:
    raw = _pick(frame, "lap", "lap_count", "lapCount", "completed_laps", "completedLaps")
    value = _num(raw)
    if value is None or value < 0:
        return None
    return int(value)


def _corner_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for wheel in _WHEELS:
        v = _num(value.get(wheel))
        if v is not None:
            out[wheel] = v
    return out


def _frame_corner_map(frame: dict[str, Any], *keys: str) -> dict[str, float]:
    for key in keys:
        value = _pick(frame, key)
        out = _corner_map(value)
        if out:
            return out
    return {}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _dominant_axle(values: dict[str, float]) -> str:
    front = [values[w] for w in ("fl", "fr") if w in values]
    rear = [values[w] for w in ("rl", "rr") if w in values]
    if not front and not rear:
        return "unknown"
    if not rear:
        return "front"
    if not front:
        return "rear"
    return "front" if _mean(front) >= _mean(rear) else "rear"


def _serial_findings(findings: list[TyreFinding | ConditionsFinding]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for finding in findings:
        row = {
            "key": finding.key,
            "summary": finding.summary,
            "coaching": finding.coaching,
            "confidence": finding.confidence,
        }
        severity = getattr(finding, "severity", None)
        if severity is not None:
            row["severity"] = severity
        approximate = getattr(finding, "approximate", None)
        if approximate is not None:
            row["approximate"] = approximate
        out.append(row)
    return out


@dataclass
class RaceManagementObserver:
    """Stateful live race-management observer.

    Feed it the same ``telemetry_tick`` frames used by the realtime coach. It returns ``Advisory``
    objects so server/voice/haptic fan-out does not need a second event path.
    """

    fuel_samples: deque[float] = field(default_factory=lambda: deque(maxlen=_FUEL_SAMPLE_WINDOW))
    _last_lap: int | None = None
    _lap_start_fuel_l: float | None = None
    _last_fuel_cue: tuple[int | None, str] | None = None
    _last_tyre_cue: tuple[int | None, str] | None = None
    _last_brake_cue: tuple[int | None, str] | None = None
    _conditions_seen: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self._reset_fuel()
        self._last_tyre_cue = None
        self._last_brake_cue = None
        self._conditions_seen.clear()

    def _reset_fuel(self) -> None:
        self.fuel_samples.clear()
        self._last_lap = None
        self._lap_start_fuel_l = None
        self._last_fuel_cue = None

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        lap = _lap(frame)
        lap_advanced = self._update_fuel_lap(frame, lap)
        out: list[Advisory] = []
        fuel = self._fuel_advisory(frame, lap, lap_advanced=lap_advanced)
        if fuel is not None:
            out.append(fuel)
        tyre = self._tyre_advisory(frame, lap)
        if tyre is not None:
            out.append(tyre)
        brake = self._brake_advisory(frame, lap)
        if brake is not None:
            out.append(brake)
        conditions = self._conditions_advisory(frame)
        if conditions is not None:
            out.append(conditions)
        return out

    def _update_fuel_lap(self, frame: dict[str, Any], lap: int | None) -> bool:
        fuel_l = _num(_pick(frame, "fuel_l", "fuelLevel", "fuel"))
        if fuel_l is None:
            return False
        if lap is None:
            if self._lap_start_fuel_l is None:
                self._lap_start_fuel_l = fuel_l
            return False
        if self._last_lap is None:
            self._last_lap = lap
            self._lap_start_fuel_l = fuel_l
            return False
        if lap < self._last_lap:
            self._reset_fuel()
            self._last_lap = lap
            self._lap_start_fuel_l = fuel_l
            return False
        if lap == self._last_lap:
            return False
        lap_delta = lap - self._last_lap
        if self._lap_start_fuel_l is not None:
            used = (self._lap_start_fuel_l - fuel_l) / lap_delta
            if used >= _MIN_FUEL_LAP_USE_L:
                self.fuel_samples.append(used)
        self._last_lap = lap
        self._lap_start_fuel_l = fuel_l
        return True

    def _fuel_numbers(
        self, frame: dict[str, Any], lap: int | None
    ) -> tuple[float, float, float, float | None] | None:
        """Raw ``(fuel_l, per_lap, laps_remaining, target)`` for the current frame, or ``None``
        when fuel is unmeasurable. Unrounded — cue thresholds compare against these so a value
        rounded for the wire can never flip a near-threshold decision (Codex on PR #615)."""
        fuel_l = _num(_pick(frame, "fuel_l", "fuelLevel", "fuel"))
        direct_per_lap = _num(_pick(frame, "fuel_per_lap_l", "fuelPerLapL"))
        if fuel_l is None or (not self.fuel_samples and direct_per_lap is None):
            return None
        per_lap = _mean(list(self.fuel_samples)) if self.fuel_samples else direct_per_lap
        if per_lap is None or per_lap <= 0:
            return None
        return fuel_l, per_lap, fuel_l / per_lap, _target_laps_remaining(frame, lap)

    def fuel_status(self, frame: dict[str, Any], lap: int | None = None) -> dict[str, Any] | None:
        """Clean fuel fields for the current frame, or ``None`` when fuel is unmeasurable.

        #531 Part D remainder: the same numbers ``_fuel_advisory`` buries inside a cue ``detail``,
        surfaced as first-class fields so the ``race.status`` topic (and any other consumer) can
        read fuel-as-a-decision without parsing cues. Ungated — no dedup, no register ladder;
        callers rate-limit. ``lap`` defaults to the frame's own lap counter.
        """
        if lap is None:
            lap = _lap(frame)
        numbers = self._fuel_numbers(frame, lap)
        if numbers is None:
            return None
        fuel_l, per_lap, laps_remaining, target = numbers
        status = {
            "fuel_l": round(fuel_l, 2),
            "fuel_per_lap_l": round(per_lap, 3),
            "laps_remaining": round(laps_remaining, 2),
            "samples": len(self.fuel_samples),
            "fuel_per_lap_source": "observed_laps" if self.fuel_samples else "frame",
        }
        if target is not None:
            status["target_laps_remaining"] = round(target, 2)
        return status

    def _fuel_advisory(
        self, frame: dict[str, Any], lap: int | None, *, lap_advanced: bool
    ) -> Advisory | None:
        numbers = self._fuel_numbers(frame, lap)
        if numbers is None:
            return None
        _fuel_l, per_lap, laps_remaining, target = numbers
        detail = self.fuel_status(frame, lap)
        if target is not None:
            deficit = target - laps_remaining
            if deficit > _FUEL_SHORT_MARGIN_LAPS:
                register = "critical" if deficit >= _FUEL_CRITICAL_DEFICIT_LAPS else "urgent"
                key = (lap, register)
                if self._last_fuel_cue == key:
                    return None
                self._last_fuel_cue = key
                detail["deficit_laps"] = round(deficit, 2)
                return Advisory(
                    kind="fuel_save",
                    corner=-1,
                    spline=float(_num(_pick(frame, "spline")) or 0.0),
                    urgency="act",
                    message=(f"Fuel short by {deficit:.1f} laps; lift and coast on the straights."),
                    detail=detail,
                    intensity=min(1.0, deficit / 2.0),
                    register=register,
                )
        if not lap_advanced:
            return None
        key = (lap, "status")
        if self._last_fuel_cue == key:
            return None
        self._last_fuel_cue = key
        return Advisory(
            kind="fuel_status",
            corner=-1,
            spline=float(_num(_pick(frame, "spline")) or 0.0),
            urgency="info",
            message=f"Fuel {laps_remaining:.1f} laps remaining at {per_lap:.2f} L/lap.",
            detail=detail,
            intensity=0.0,
            register="calm",
        )

    def _tyre_advisory(self, frame: dict[str, Any], lap: int | None) -> Advisory | None:
        temps = _frame_corner_map(frame, "tyre_temps_c", "tire_temps_c")
        wear = _frame_corner_map(frame, "tyre_wear_pct", "tire_wear_pct")
        if not temps and not wear:
            return None
        if temps:
            compound = _pick(frame, "tyre_compound", "tire_compound")
            report = analyze_tyres(
                temps,
                compound=compound if isinstance(compound, str) else None,
                laps_since_start=lap,
            )
            keys = {f.key for f in report.findings}
            status_values = set(report.status.values())
            if "critical" in status_values:
                return self._tyre_cue(
                    lap,
                    "critical",
                    "critical",
                    "Tyres critical; back off now and protect the hottest axle.",
                    temps,
                    wear,
                    report.findings,
                    "act",
                )
            if "overheat" in keys:
                axle = _dominant_axle(temps)
                return self._tyre_cue(
                    lap,
                    "overheat",
                    "urgent",
                    f"{axle.title()} tyres overheating; smooth inputs and protect the axle.",
                    temps,
                    wear,
                    report.findings,
                    "act",
                )
            if "degradation_onset" in keys:
                return self._tyre_cue(
                    lap,
                    "thermal_rolloff",
                    "alert",
                    "Tyres are near thermal roll-off; smooth the stint and stop sliding them.",
                    temps,
                    wear,
                    report.findings,
                    "prepare",
                )
        high_wear = {wheel: value for wheel, value in wear.items() if value >= _WEAR_CAUTION_PCT}
        if high_wear:
            axle = _dominant_axle(high_wear)
            return self._tyre_cue(
                lap,
                "wear",
                "alert",
                f"{axle.title()} tyre wear is high without an overheat signal; "
                "protect it from slides.",
                temps,
                wear,
                [],
                "prepare",
            )
        return None

    def _tyre_cue(
        self,
        lap: int | None,
        classification: str,
        register: str,
        message: str,
        temps: dict[str, float],
        wear: dict[str, float],
        findings: list[TyreFinding],
        urgency: str,
    ) -> Advisory | None:
        key = (lap, classification)
        if self._last_tyre_cue == key:
            return None
        self._last_tyre_cue = key
        return Advisory(
            kind="tyre_manage",
            corner=-1,
            spline=0.0,
            urgency=urgency,
            message=message,
            detail={
                "classification": classification,
                "tyre_temps_c": {k: round(v, 1) for k, v in temps.items()},
                "tyre_wear_pct": {k: round(v, 1) for k, v in wear.items()},
                "wear_signal": bool(wear),
                "findings": _serial_findings(findings[:3]),
            },
            intensity=1.0 if register == "critical" else 0.65 if register == "urgent" else 0.35,
            register=register,
        )

    def _brake_advisory(self, frame: dict[str, Any], lap: int | None) -> Advisory | None:
        temps = _frame_corner_map(frame, "brake_temps_c", "brake_temp_c")
        wear = _frame_corner_map(frame, "brake_wear_pct")
        if not temps and not wear:
            return None
        hot = {wheel: temp for wheel, temp in temps.items() if temp >= _BRAKE_HOT_C}
        critical = {wheel: temp for wheel, temp in temps.items() if temp >= _BRAKE_CRITICAL_C}
        high_wear = {wheel: value for wheel, value in wear.items() if value >= _WEAR_CAUTION_PCT}
        if critical:
            classification = "critical_temp"
            register = "critical"
            urgency = "act"
            message = "Brakes are in the critical heat band; cool them with earlier lifts."
        elif hot:
            classification = "hot"
            register = "alert"
            urgency = "prepare"
            message = "Brake temps are hot; stop dragging brake and add cooling laps."
        elif high_wear:
            classification = "wear"
            register = "alert"
            urgency = "prepare"
            message = "Brake wear is building; reduce peak brake time over the stint."
        else:
            return None
        key = (lap, classification)
        if self._last_brake_cue == key:
            return None
        self._last_brake_cue = key
        return Advisory(
            kind="brake_manage",
            corner=-1,
            spline=float(_num(_pick(frame, "spline")) or 0.0),
            urgency=urgency,
            message=message,
            detail={
                "classification": classification,
                "brake_temps_c": {k: round(v, 1) for k, v in temps.items()},
                "brake_wear_pct": {k: round(v, 1) for k, v in wear.items()},
            },
            intensity=1.0 if register == "critical" else 0.35,
            register=register,
        )

    def _conditions_advisory(self, frame: dict[str, Any]) -> Advisory | None:
        conditions = _conditions_from_frame(frame)
        if conditions is None:
            return None
        report = analyze_conditions(conditions)
        finding = next(
            (
                f
                for f in report.findings
                if f.key in {"wet_regime", "cold_track", "hot_track", "green_track"}
            ),
            None,
        )
        if finding is None:
            return None
        if finding.key in self._conditions_seen:
            return None
        self._conditions_seen.add(finding.key)
        if finding.key == "wet_regime":
            urgency = "act"
            register = "urgent"
            message = "Wet track strategy: brake earlier, use smoother throttle, and avoid puddles."
        elif finding.key == "cold_track":
            urgency = "prepare"
            register = "alert"
            message = "Cold track strategy: build tyre heat before pushing."
        elif finding.key == "hot_track":
            urgency = "prepare"
            register = "alert"
            message = "Hot track strategy: manage tyre temperature over the stint."
        else:
            urgency = "prepare"
            register = "calm"
            message = "Green track strategy: let grip build before judging setup."
        return Advisory(
            kind="conditions_strategy",
            corner=-1,
            spline=float(_num(_pick(frame, "spline")) or 0.0),
            urgency=urgency,
            message=message,
            detail={
                "classification": finding.key,
                "conditions": conditions,
                "finding": _serial_findings([finding])[0],
            },
            intensity=0.65 if register == "urgent" else 0.35 if register == "alert" else 0.25,
            register=register,
        )


def _target_laps_remaining(frame: dict[str, Any], lap: int | None) -> float | None:
    for key in ("target_laps_remaining", "laps_to_finish", "race_laps_remaining"):
        value = _num(_pick(frame, key))
        if value is not None and value >= 0:
            return value
    total = _num(_pick(frame, "race_laps", "session_laps_total"))
    if total is not None and total >= 0 and lap is not None:
        return max(0.0, total - lap)
    return None


def _conditions_from_frame(frame: dict[str, Any]) -> dict[str, Any] | None:
    keys = {
        "trackGripLevel": _pick(frame, "track_grip_level", "trackGripLevel"),
        "trackTempC": _pick(frame, "track_temp_c", "trackTempC"),
        "ambientTempC": _pick(frame, "ambient_temp_c", "ambientTempC"),
        "weatherType": _pick(frame, "weather_type", "weatherType"),
    }
    if all(v is None for v in keys.values()):
        return None
    return keys
