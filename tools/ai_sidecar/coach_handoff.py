"""Structured coach-handoff protocol: a versioned, machine-readable per-corner verdict.

Turns the brain's debrief (``coach_report.build_structured_debrief``) into a compact, versioned
message a downstream consumer — an RL/agentic coach, the rig screen, or a logger — can act on
without re-parsing prose. Per corner: ``{corner, time_loss_s, cause_class, confidence, advisory,
coaching, suggested_setup_delta}``; per lap: total time lost, the top-focus corner, and the
aero/mechanical balance verdict.

The ``suggested_setup_delta`` is grounded in the verified setup knowledge + the attribution's own
cause: a technique-class corner suggests NO setup change (it's a driver fix); a setup/grip-class
corner names the lever + direction (e.g. front-biased braking → ``FRONT_BIAS`` rearward), always
carrying the honest "needs live per-wheel slip to confirm the axle" caveat where the archive can
only suspect.

``cause_class`` is forwarded verbatim from the brain's attribution and is one of
:data:`CAUSE_CLASSES`. Note the **mixed** ``"setup+technique"`` value: several common rules
(braking, exit-traction) legitimately have both setup and technique causes, so a v1 consumer MUST
handle it (do not assume the bare ``setup|technique|grip`` trio).

The braking-bias direction is **car-** and **confidence-gated** (codex/copilot #290): the
rear-engine-911 "bias rearward toward ~50-56%" recommendation fires only for that car AND only while
the diagnosis is still *suspected* (``advisory``). Once per-wheel slip confirms the locking axle
the brain already knows the direction (rear-lock wants bias forward, the opposite), so the handoff
defers to the brain's coaching instead of guessing from the bias number. Pure stdlib.
"""

from __future__ import annotations

from typing import Any

from tools.ai_sidecar.setup_model import CarSetup

COACH_HANDOFF_VERSION = 1

#: The complete set of ``cause_class`` values a v1 consumer may receive (forwarded verbatim from
#: ``coach_report._cause_class``). ``"setup+technique"`` is a real, common value — handle it.
CAUSE_CLASSES = ("setup", "technique", "setup+technique", "grip", "none", "unknown")

#: 911 GT3 R (rear-engine) wants lower front brake bias than a typical GT3 — flag above this.
_FRONT_BIAS_HIGH_PCT = 58.0
_TIME_LOSS_EPS_S = 0.03  # a corner counts as "losing time" above this


def _is_rear_engine_911(car_id: str | None) -> bool:
    """True for the rear-engine Porsche 911 GT3 family (the car the bias-rearward rule fits)."""
    if not car_id:
        return False
    cid = car_id.lower()
    return "911" in cid and "gt3" in cid


def _setup_delta(
    attr: dict[str, Any], setup: CarSetup | None, car_id: str | None = None
) -> dict[str, Any] | None:
    """Derive a structured, grounded setup-change suggestion from one attribution, or None.

    Technique-class causes return None (the fix is the driver, not the car). Setup/grip causes name
    the AC section + direction, with the verified caveats (per-wheel slip to confirm an axle, etc.).
    The braking-bias direction is gated by car (rear-engine 911 only) and by confidence (suspected
    only) so the machine-readable advice never contradicts a confirmed per-wheel diagnosis.
    """
    key = attr.get("key")
    if key in ("entry_speed_left", "turn_in_lag"):
        return None  # technique-first — no setup delta
    if key == "braking_phase_loss":
        bias = setup.brake_bias_pct if setup else None
        car = car_id or (setup.car_id if setup else None)
        suspected = bool(attr.get("advisory"))  # confirmed (per-wheel) → defer to the brain
        if (
            suspected
            and _is_rear_engine_911(car)
            and bias is not None
            and bias > _FRONT_BIAS_HIGH_PCT
        ):
            return {
                "section": "FRONT_BIAS",
                "direction": "decrease",
                "from": bias,
                "rationale": "suspected front-biased braking on a rear-engine 911 GT3 R (usually "
                "wants ~50-56%) — confirm which axle locks with live per-wheel slip before "
                "committing.",
            }
        if not suspected:
            return {
                "section": "FRONT_BIAS",
                "direction": "investigate",
                "from": bias,
                "rationale": "the brain confirmed the locking axle from live per-wheel slip; "
                "follow its corner coaching (rear lock wants bias FORWARD, front lock rearward) "
                "and do not move bias off the bias number alone.",
            }
        return {
            "section": "FRONT_BIAS",
            "direction": "investigate",
            "from": bias,
            "rationale": "investigate brake bias + modulation; the right target is car-specific, "
            "and live per-wheel slip confirms which axle locks.",
        }
    if key == "exit_traction":
        if not bool(attr.get("advisory")):
            # confirmed by per-wheel slip: the brain knows whether it was wheelspin (diff/TC
            # relevant) or simply late to power (technique) — defer, don't push a setup lever blind.
            return {
                "section": "DIFF_POWER",
                "direction": "investigate",
                "from": setup.diff_power if setup else None,
                "rationale": "the brain confirmed exit traction from live per-wheel slip — follow "
                "its corner coaching; only touch DIFF_POWER/TC if it was actually wheelspin, not "
                "if the loss was getting to power late (technique).",
            }
        return {
            "section": "DIFF_POWER",
            "direction": "context",
            "from": setup.diff_power if setup else None,
            "rationale": "suspected exit traction — lead with throttle technique + DIFF_POWER "
            "(on-throttle lock); lower TC if it is cutting power — needs live RPM/slip to tell a "
            "cut from over-throttle.",
        }
    if key == "grip_limited":
        return {
            "section": "TYRES/PRESSURE/WING",
            "direction": "increase_grip",
            "from": setup.compound_index if setup else None,
            "rationale": "at the grip limit — pressures toward the hot window, a softer compound, "
            "or more wing; confirm with live hot-pressure + core-temp.",
        }
    return None


def build_coach_handoff(
    structured: dict[str, Any] | None, *, setup: CarSetup | None = None, lap: Any = None
) -> dict[str, Any]:
    """Build the versioned coach-handoff message from a ``build_structured_debrief`` result.

    Returns the envelope even when ``structured`` is None/empty (an empty corner list), so a
    consumer always gets a well-formed, versioned message.
    """
    structured = structured or {}
    car_id = structured.get("car_id")
    corners_in = structured.get("corners") or []
    corners_out: list[dict[str, Any]] = []
    for c in corners_in:
        attrs = c.get("attributions") or []
        top = attrs[0] if attrs else None
        corners_out.append(
            {
                "corner": c.get("index"),
                "apex_spline": c.get("apex_spline"),
                "time_loss_s": c.get("time_loss_s"),
                "cause_class": top.get("cause_class") if top else "none",
                "confidence": top.get("confidence", 0.0) if top else 0.0,
                "advisory": bool(top.get("advisory")) if top else False,
                "symptom": top.get("symptom") if top else "on pace",
                "coaching": top.get("coaching") if top else c.get("headline", ""),
                "suggested_setup_delta": _setup_delta(top, setup, car_id) if top else None,
            }
        )
    losers = [
        c
        for c in corners_out
        if isinstance(c["time_loss_s"], (int, float)) and c["time_loss_s"] > _TIME_LOSS_EPS_S
    ]
    top_focus = max(losers, key=lambda c: c["time_loss_s"]) if losers else None
    return {
        "v": COACH_HANDOFF_VERSION,
        "lap": lap,
        "car_id": structured.get("car_id"),
        "track_id": structured.get("track_id"),
        "total_time_lost_s": round(sum(c["time_loss_s"] for c in losers), 3) if losers else None,
        "top_focus_corner": top_focus["corner"] if top_focus else None,
        "balance": structured.get("balance"),
        "corners": corners_out,
    }
