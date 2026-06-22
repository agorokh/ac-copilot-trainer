"""Track/weather conditions → grip model for cross-session-comparable coaching. Pure stdlib.

Consumes a lap archive's ``conditions`` block (``trackGripLevel``, ``ambientTempC``, ``trackTempC``,
``weatherType``) and produces a regime + a coarse grip normalizer + honest coaching about how
conditions, not the driver, explain part of a lap delta.

Grounded in adversarially-verified research (the red-team's corrections are LOAD-BEARING — do not
re-introduce the precision they removed):

* **``trackGripLevel`` is the ONLY authoritative, persisted, cross-session-comparable scalar.**
  Normalize on it ALONE; the scalar→laptime mapping is nonlinear/car-specific, so any cross-band
  comparison is **approximate** — prefer comparing laps in the *same* grip band.
* **AC exposes NO reliable track-temp→grip percentage.** Grip-vs-temp is per-compound,
  mod-dependent, defined on *tyre* temp (not track temp), and not in the API. So temperature here
  is **qualitative** ("colder → slower warm-up, grip-limited early"), NEVER a grip multiplier.
* **Wet/snow ⇒ the slick model is INVALID** — gate it off; coach compound + water management, never
  "build heat aggressively".
* ``trackTempC`` / ``weatherType`` are **nullable** — guard; null weather = "unknown", not "dry".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# weatherType is NOT standardized across base AC / CSP / Sol — match defensively (lowercase substr).
_WET_TOKENS = ("damp", "rain", "wet", "snow", "storm", "shower")
_DRY_TOKENS = ("dry", "clear", "sun", "cloud", "overcast", "fair", "mist")

# trackGripLevel bands (AC native scalar; fresh stock session ~0.95-0.96, rubbers UP toward ~1.0).
GREEN_BELOW = 0.93  # green/dusty/low-rubber — grip is the dominant limit, will build
RUBBERED_AT = 0.985  # at/above ~ rubbered-in plateau
SANE_GRIP = (0.70, 1.05)  # outside → "investigate config/data", not a physics claim

# qualitative track-temp bands for a DRY slick (directional only; NO grip-% attached)
TRACK_TEMP_COLD_C = 20.0
TRACK_TEMP_HOT_C = 45.0
TEMP_DELTA_NOTABLE_C = 6.0  # reference-vs-current track-temp gap worth a coaching note


@dataclass(frozen=True)
class ConditionsFinding:
    key: str
    summary: str
    coaching: str
    confidence: str  # high | medium | low
    approximate: bool = False  # True when the statement is a coarse/qualitative inference


@dataclass
class ConditionsReport:
    regime: str  # "dry" | "wet" | "unknown"
    grip_level: float | None
    grip_band: str  # green | building | rubbered | boosted | unknown
    track_temp_c: float | None
    ambient_temp_c: float | None
    weather: str | None
    grip_level_delta: float | None  # vs reference (approximate normalizer signal)
    findings: list[ConditionsFinding] = field(default_factory=list)

    @property
    def slick_model_valid(self) -> bool:
        """Slick temp/grip heuristics only apply in a dry (or unknown-but-not-wet) regime."""
        return self.regime != "wet"

    def normalizer(self) -> float:
        """Coarse, APPROXIMATE grip normalizer (= trackGripLevel, clamped). 1.0 when unknown.

        Use only to scale deltas between laps of the SAME regime, and always label the result
        approximate — the scalar→laptime mapping is nonlinear and car/track-specific.
        """
        if self.grip_level is None:
            return 1.0
        return max(SANE_GRIP[0], min(SANE_GRIP[1], self.grip_level))

    def headline(self) -> str:
        if self.regime == "wet":
            return f"WET/{(self.weather or 'rain')} — slick model off; coach compound + water."
        g = (
            f"track grip {self.grip_level:.3f} ({self.grip_band})"
            if self.grip_level is not None
            else "track grip unknown"
        )
        return f"Conditions: {self.regime}, {g}."


def _regime(weather: Any) -> str:
    if not isinstance(weather, str) or not weather.strip():
        return "unknown"
    w = weather.strip().lower()
    if any(t in w for t in _WET_TOKENS):
        return "wet"
    if any(t in w for t in _DRY_TOKENS):
        return "dry"
    return "unknown"


def _grip_band(grip: float | None) -> str:
    if grip is None:
        return "unknown"
    if grip > 1.02:
        return "boosted"
    if grip >= RUBBERED_AT:
        return "rubbered"
    if grip < GREEN_BELOW:
        return "green"
    return "building"


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _sane_grip(grip: float | None) -> bool:
    """True when a trackGripLevel is present and within the sane band (else not comparable)."""
    return grip is not None and SANE_GRIP[0] <= grip <= SANE_GRIP[1]


def analyze_conditions(
    conditions: dict[str, Any] | None,
    *,
    reference_conditions: dict[str, Any] | None = None,
) -> ConditionsReport:
    """Build a :class:`ConditionsReport` from a ``conditions`` block (+ optional reference)."""
    conditions = conditions or {}
    grip = _num(conditions.get("trackGripLevel"))
    track_t = _num(conditions.get("trackTempC"))
    ambient_t = _num(conditions.get("ambientTempC"))
    weather = conditions.get("weatherType")
    regime = _regime(weather)
    band = _grip_band(grip)

    ref = reference_conditions or {}
    ref_grip = _num(ref.get("trackGripLevel"))
    ref_track_t = _num(ref.get("trackTempC"))
    ref_regime = _regime(ref.get("weatherType"))
    # A reference comparison is only meaningful when current + reference are the SAME, DRY regime
    # (wet trackGripLevel/temp don't transfer) and both grip scalars are in the sane band. Otherwise
    # both the grip delta AND the reference-temperature note are apples-to-oranges (codex #283).
    comparable_ref = (
        regime != "wet" and ref_regime == regime and _sane_grip(grip) and _sane_grip(ref_grip)
    )
    grip_delta = round(grip - ref_grip, 4) if comparable_ref else None
    ref_track_for_note = ref_track_t if comparable_ref else None

    findings = _build_findings(
        regime, grip, band, track_t, ambient_t, weather, grip_delta, ref_grip, ref_track_for_note
    )
    return ConditionsReport(
        regime=regime,
        grip_level=grip,
        grip_band=band,
        track_temp_c=track_t,
        ambient_temp_c=ambient_t,
        weather=weather if isinstance(weather, str) else None,
        grip_level_delta=grip_delta,
        findings=findings,
    )


def _build_findings(
    regime, grip, band, track_t, ambient_t, weather, grip_delta, ref_grip, ref_track_t
) -> list[ConditionsFinding]:
    out: list[ConditionsFinding] = []
    if regime == "wet":
        out.append(
            ConditionsFinding(
                "wet_regime",
                f"wet/snow regime ({weather})",
                "Slick temp/grip model is OFF — pace is limited by the surface + compound, not "
                "your technique or 'cold tyres'. Run an inter/wet, brake earlier, no "
                "trail-braking, smooth throttle. Do NOT build heat aggressively (wets run cooler).",
                "high",
            )
        )
        return out  # in the wet, the slick-temp findings below do not apply

    if grip is None:
        out.append(
            ConditionsFinding(
                "no_grip_data",
                "trackGripLevel missing",
                "No track-grip data this lap — cannot normalize across sessions; compare only "
                "within the same session.",
                "low",
                approximate=True,
            )
        )
    else:
        if not (SANE_GRIP[0] <= grip <= SANE_GRIP[1]):
            out.append(
                ConditionsFinding(
                    "grip_out_of_range",
                    f"trackGripLevel {grip:.3f} outside {SANE_GRIP}",
                    "Unusual grip scalar — investigate session config / data, not a physics claim.",
                    "low",
                    approximate=True,
                )
            )
        elif band == "green":
            out.append(
                ConditionsFinding(
                    "green_track",
                    f"low-rubber track (grip {grip:.3f})",
                    "Track is green/low-rubber — that's the dominant limit now; grip builds over "
                    "the session as rubber goes down. Don't over-correct setup on a green track.",
                    "medium",
                )
            )
        elif band == "rubbered":
            out.append(
                ConditionsFinding(
                    "rubbered_track",
                    f"rubbered-in (grip {grip:.3f})",
                    "Track is rubbered-in and stable — a good reference session; deltas here "
                    "reflect you + setup, not track state.",
                    "medium",
                )
            )

    # cross-session grip normalization — APPROXIMATE, trackGripLevel only
    if grip_delta is not None and abs(grip_delta) >= 0.005:
        hotter = "higher" if grip_delta > 0 else "lower"
        out.append(
            ConditionsFinding(
                "grip_vs_reference",
                f"track grip {hotter} than reference by {abs(grip_delta):.3f}",
                f"Part of the laptime gap is track grip ({ref_grip:.3f} → {grip:.3f}), not you — "
                "this normalization is APPROXIMATE; ideally compare laps in the same grip band.",
                "medium",
                approximate=True,
            )
        )

    # qualitative track-temp coaching (NO grip-% — AC exposes none)
    if track_t is None:
        out.append(
            ConditionsFinding(
                "no_track_temp",
                "trackTempC missing",
                "No track-temp data — using the grip meter only; not inferring a temp effect.",
                "low",
                approximate=True,
            )
        )
    else:
        if track_t < TRACK_TEMP_COLD_C:
            out.append(
                ConditionsFinding(
                    "cold_track",
                    f"track {track_t:.0f}°C (cold for slicks)",
                    "Cold track — tyres take extra laps to switch on; laps 1-2 feel grip-limited. "
                    "Qualitative (AC exposes no track-temp→grip number); warm up before pushing.",
                    "low",
                    approximate=True,
                )
            )
        elif track_t > TRACK_TEMP_HOT_C:
            out.append(
                ConditionsFinding(
                    "hot_track",
                    f"track {track_t:.0f}°C (hot)",
                    "Hot track — tyres switch on fast but overheat sooner; manage thermal load "
                    "with smoother inputs. Qualitative direction only.",
                    "low",
                    approximate=True,
                )
            )
        if ref_track_t is not None and abs(track_t - ref_track_t) >= TEMP_DELTA_NOTABLE_C:
            cooler = "colder" if track_t < ref_track_t else "hotter"
            out.append(
                ConditionsFinding(
                    "track_temp_vs_reference",
                    f"track {abs(track_t - ref_track_t):.0f}°C {cooler} than reference",
                    f"Track is {cooler} than your reference lap — expect a different tyre warm-up/"
                    "thermal balance; treat early-lap grip differences as conditions, not you. "
                    "Direction only, not a quantified grip change.",
                    "low",
                    approximate=True,
                )
            )
    return out


def conditions_from_lap_archive(
    archive: dict, *, reference_archive: dict | None = None
) -> ConditionsReport:
    """Build a :class:`ConditionsReport` from a lap archive's conditions (+ optional reference)."""
    cond = archive.get("conditions") if isinstance(archive, dict) else None
    ref = reference_archive.get("conditions") if isinstance(reference_archive, dict) else None
    return analyze_conditions(
        cond if isinstance(cond, dict) else None,
        reference_conditions=ref if isinstance(ref, dict) else None,
    )
