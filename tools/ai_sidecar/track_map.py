"""Track-map payload for the tablet MAP page (#531 Part F).

Built once from the loaded reference archive — the same artifact that arms the realtime
observer — because its trace carries real world coordinates (``px``/``pz``, in the archive
since the Tier-B channel work) ordered by spline. No track-install parsing, no invented
geometry: **no reference archive → no map** (the page renders its explicit unknown).

Payload shape (the ``track.map`` topic):

``{track_id?, car_id?, source: "reference_archive", lap_ms?,
   outline: [[x, z], ...],       # downsampled to <= MAX_OUTLINE_POINTS, spline-ordered
   spline:  [s, ...],            # per outline point — the client maps live spline -> dot
   corners: [{label, spline, entry_spline, min_speed_kmh, gear?}, ...]}``

Corner identities come only from the persisted or live Lua canonical catalogue. Dynamics
measures reference phase boundaries within those windows; it never numbers corners independently.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from dataclasses import fields, replace
from typing import Any

from tools.ai_sidecar.lap_dynamics import (
    LapTrace,
    corner_phase_boundaries,
    corner_signatures,
    lap_trace_from_archive,
    segment_corners,
)
from tools.ai_sidecar.track_reference import CornerReference
from tools.lap_qualification import archive_combo, qualify_archive
from tools.lap_trace_validity import completed_trace_reason, finish_wrap_cut

#: Outline resolution cap — ~2 m spacing on a 5 km lap, well under the A133's SVG budget.
MAX_OUTLINE_POINTS = 256
#: A real circuit spans hundreds of metres; anything under this is a zero-filled/degenerate
#: position column, not geometry (Codex on PR #618).
MIN_OUTLINE_SPAN_M = 50.0


def _round_gear(value: float) -> int | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):  # Infinity would raise OverflowError at int() (#618 R11)
        return None
    g = int(round(f))
    return g if g >= 1 else None


def build_track_map(
    archive: dict[str, Any],
    corner_catalog: dict[str, Any] | None = None,
    *,
    expected_combo: tuple[str, str, str | None] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The ``track.map`` payload for ``archive``, or ``None`` when it cannot be built honestly.

    Never raises: a malformed archive (no trace, no position channels, too few samples)
    returns ``None`` — the caller logs and the MAP page keeps its explicit unknown.
    """
    qualification = qualify_archive(archive, use="map", expected_combo=expected_combo)
    if diagnostics is not None:
        diagnostics.update(allowed=qualification.allowed, reason=qualification.reason)
    if not qualification.allowed:
        return None
    if diagnostics is not None:
        diagnostics.update(allowed=False, reason="reference_geometry_unavailable")
    try:
        lap = lap_trace_from_archive(archive)
    except (ValueError, TypeError, AttributeError, IndexError, OverflowError):
        return None
    lap = _normalise_finish_wrap(lap)
    if lap is None:
        return None
    # Non-finite coordinates would serialize as bare `NaN` tokens that the tablet's
    # JSON.parse rejects, dropping the only replayed map frame (Codex on PR #618 R6) —
    # keep only fully finite samples, then re-check viability.
    finite_idx = [
        i
        for i in range(len(lap.spline))
        if math.isfinite(lap.x[i]) and math.isfinite(lap.z[i]) and math.isfinite(lap.spline[i])
    ]
    n = len(finite_idx)
    if n < 8:
        return None
    xs = [lap.x[i] for i in finite_idx]
    zs = [lap.z[i] for i in finite_idx]
    # Degenerate-geometry gate (Codex on PR #618): a trace whose px/pz columns were present
    # but unreadable defaults to 0.0 rows — the "outline" would be a collapsed point that
    # HIDES the honest no-reference state. Require a real spatial span on both axes' union.
    span_x = max(xs) - min(xs)
    span_z = max(zs) - min(zs)
    if max(span_x, span_z) < MIN_OUTLINE_SPAN_M:
        return None

    step = max(1, -(-n // MAX_OUTLINE_POINTS))  # ceil-div: the cap is a cap, not a target
    idx = [finite_idx[i] for i in range(0, n, step)]
    if idx[-1] != finite_idx[-1]:
        # Always keep the final sample: dropping up to step-1 points at S/F would make the
        # client's closing segment a false chord tens of metres off (daemon on PR #618).
        idx.append(finite_idx[-1])
    if len(idx) > MAX_OUTLINE_POINTS:
        # The forced tail can overshoot the cap by one (daemon R11) — drop the point before
        # it, keeping the first and last samples exact.
        del idx[-2]
    outline = [[round(lap.x[i], 1), round(lap.z[i], 1)] for i in idx]
    spline = [round(lap.spline[i], 4) for i in idx]

    corners: list[dict[str, Any]] = []
    catalogue = _canonical_catalog(archive, corner_catalog)
    measured_reference = _reference_provenance_valid(
        archive, expected_combo=expected_combo
    ) and all(_channel_valid(archive, key) for key in ("speed", "px", "pz"))
    for identity, measured, window in _catalog_windows(lap, catalogue, measure=measured_reference):
        if window is None:
            corners.append(
                {
                    "id": identity["corner_id"],
                    "label": identity["corner_id"],
                    "spline": identity["brake_spline"],
                    "anchor_phase": "catalog_brake_anchor",
                    "phases": {"braking": None, "entry": None, "apex": None, "exit": None},
                    "boundary_reason": "reference phase boundaries unresolved in canonical region",
                }
            )
            continue
        entry_i, apex_i, exit_i = window
        # Same finiteness contract as the outline (daemon on PR #618 R8): one non-finite
        # corner metric would serialize as a bare NaN/Infinity token and kill the whole
        # frame at the tablet's JSON.parse. Skip the corner, keep the map.
        spline_apex = measured.spline[apex_i]
        spline_entry = measured.spline[entry_i]
        v_apex = measured.v_ms[apex_i]
        if not (
            math.isfinite(spline_apex) and math.isfinite(spline_entry) and math.isfinite(v_apex)
        ):
            continue
        corner: dict[str, Any] = {
            "id": identity["corner_id"],
            "label": identity["corner_id"],
            "anchor_phase": "measured_apex",
            "spline": round(spline_apex, 4),
            "entry_spline": round(spline_entry, 4),
            "min_speed_kmh": round(v_apex * 3.6),
            "exit_spline": round(measured.spline[exit_i], 6),
            "phases": corner_phase_boundaries(
                measured,
                (0, apex_i, exit_i),
                brake_available=_channel_valid(archive, "brake"),
                steer_available=_channel_valid(archive, "steer"),
            ),
        }
        onset = _brake_point(lap, measured, apex_i) if _channel_valid(archive, "brake") else None
        if corner["phases"]["braking"] is not None:
            corner["phases"]["braking"] = (
                [round(onset, 6), corner["phases"]["braking"][1]] if onset is not None else None
            )
        gear = _round_gear(measured.gear[apex_i])
        if gear is not None:
            corner["gear"] = gear
        corners.append(corner)

    payload: dict[str, Any] = {
        "source": "reference_archive",
        "outline": outline,
        "spline": spline,
        "corners": corners,
        "reference_id": reference_identity(archive),
        "reference_source": archive.get("source") or "unknown",
        "lap_uuid": archive.get("lap_uuid"),
        "track_layout": _combo(archive)[2],
        "corner_catalog_source": catalogue.get("source"),
        "corner_catalog_id": catalogue.get("id"),
        "corner_catalog_reference_source": catalogue.get("reference_source"),
        "corner_catalog_reference_lap_ms": catalogue.get("reference_lap_ms"),
        "corner_availability": (
            "measured"
            if corners and all(c["phases"].get("apex") is not None for c in corners)
            else "canonical identities; some/all measured boundaries unavailable"
            if corners
            else "canonical catalogue/boundaries unavailable"
        ),
    }
    if lap.track_id:
        payload["track_id"] = lap.track_id
    if lap.car_id:
        payload["car_id"] = lap.car_id
    if lap.lap_ms is not None and lap.lap_ms > 0:
        payload["lap_ms"] = lap.lap_ms
    if diagnostics is not None:
        diagnostics.update(allowed=True, reason=qualification.reason)
    return payload


def _canonical_catalog(archive: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    combo = _combo(archive)
    if not combo[0] or not combo[1]:
        return {}  # unknown identities can retain geometry, never a matching corner catalogue
    if live is not None:
        if live.get("available") is not True or tuple(live.get("combo") or ()) != combo:
            return {}
        rows = live.get("corners")
        source = "lua_active_reference"
    else:
        rows = archive.get("corners")
        source = "archive_lua_corners"
    if not isinstance(rows, list) or not rows or len(rows) > 32:
        return {}
    out = []
    labels = set()
    for row in rows:
        if not isinstance(row, dict):
            return {}
        label = row.get("corner_id") or row.get("label")
        if not isinstance(label, str) or not label.startswith("T") or not label[1:].isdigit():
            return {}
        if label in labels or not 1 <= int(label[1:]) <= 32:
            return {}
        labels.add(label)
        start, end = row.get("s0"), row.get("s1")
        anchor = row.get("brake_spline", row.get("brakePointSpline"))
        if (
            any(
                not isinstance(v, (float, int))
                or isinstance(v, bool)
                or not math.isfinite(v)
                or not 0 <= v <= 1
                for v in (start, end, anchor)
            )
            or start == end
        ):
            return {}
        out.append({"corner_id": label, "s0": start, "s1": end, "brake_spline": anchor})
    digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return {
        "corners": out,
        "source": source,
        "id": digest,
        "reference_source": (live or {}).get("reference_source"),
        "reference_lap_ms": (live or {}).get("reference_lap_ms"),
    }


def bind_reference_corners(
    archive: dict[str, Any],
    references: list[CornerReference],
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind measured regions to canonical names without renumbering their diagnostic facts.

    A speed-minimum window is not a turn identity. Merged regions, multiple measured
    regions sharing one canonical turn, and unknown geometry cannot supply named advice.
    Uses the same combo/catalogue authority as MAP; no trace parsing or telemetry I/O.
    """
    catalog = _canonical_catalog(archive, live)
    labels: dict[int, str] = {}
    rejected: dict[int, str] = {}
    owners: dict[str, set[int]] = {}
    result: dict[str, Any] = {
        "ready": False,
        "reason": "canonical_catalog_unavailable",
        "labels": labels,
        "rejected": rejected,
        "reference_count": len(references),
        "eligible_count": 0,
        "catalog_id": catalog.get("id"),
        "source": catalog.get("source"),
    }
    if not catalog:
        return result

    def parts(lo: float, hi: float) -> list[tuple[float, float]]:
        return [(lo, hi)] if lo < hi else [(lo, 1.0), (0.0, hi)]

    def overlap(a: float, b: float, c: float, d: float) -> bool:
        return any(min(y, v) - max(x, u) > 1e-9 for x, y in parts(a, b) for u, v in parts(c, d))

    for ref in references:
        values = (ref.spline_lo, ref.apex_spline, ref.spline_hi)
        if any(
            not isinstance(v, (int, float))
            or isinstance(v, bool)
            or not math.isfinite(v)
            or not 0 <= v <= 1
            for v in values
        ):
            rejected[ref.index] = "invalid_reference_geometry"
            continue
        if ref.spline_lo >= ref.spline_hi or not ref.spline_lo <= ref.apex_spline <= ref.spline_hi:
            rejected[ref.index] = "invalid_reference_geometry"
            continue
        touched = [
            row
            for row in catalog["corners"]
            if overlap(ref.spline_lo, ref.spline_hi, row["s0"], row["s1"])
        ]
        for row in touched:
            owners.setdefault(row["corner_id"], set()).add(ref.index)
        if len(touched) != 1:
            rejected[ref.index] = "merged_or_unresolved_reference_region"
            continue
        row = touched[0]
        if not any(lo <= ref.apex_spline <= hi for lo, hi in parts(row["s0"], row["s1"])):
            rejected[ref.index] = "apex_outside_canonical_region"
            continue
        labels[ref.index] = row["corner_id"]
    for label in set(labels.values()):
        indexes = [index for index, value in labels.items() if value == label]
        # A merged/rejected neighbour still makes canonical ownership ambiguous.
        if len(owners[label]) > 1:
            for index in indexes:
                del labels[index]
                rejected[index] = "split_reference_region"
    result.update(
        ready=bool(labels),
        eligible_count=len(labels),
        reason=(
            "unique_corner_geometry"
            if not rejected and labels
            else "partial_unique_corner_geometry"
            if labels
            else "no_unique_corner_geometry"
        ),
    )
    return result


def _slice_circular(lap: LapTrace, start: float, end: float) -> LapTrace:
    if start <= end:
        # Equal physical S/F positions are distinct observations at t=0 and t=lap_ms.
        # A non-wrapping window ending at 1 must retain the actual finish telemetry.
        indices = [i for i, s in enumerate(lap.spline) if start <= s <= end]
    else:
        suffix = [i for i, s in enumerate(lap.spline) if s >= start]
        prefix = [i for i, s in enumerate(lap.spline) if s <= end]
        # At a circular seam prefer the measured finish over repeating t=0 shifted
        # by one lap. Other prefix samples supply the circular continuation.
        if suffix and prefix and lap.spline[suffix[-1]] == 1 and lap.spline[prefix[0]] == 0:
            prefix = prefix[1:]
        indices = suffix + prefix
    channels = {
        name: [getattr(lap, name)[i] for i in indices]
        for name in ("spline", "v_ms", "brake", "throttle", "steer", "gear", "x", "z")
    }
    times = [lap.t_s[i] + (lap.lap_ms or 0) / 1000 * (lap.spline[i] < start) for i in indices]
    return LapTrace(
        **channels, t_s=times, lap_ms=lap.lap_ms, car_id=lap.car_id, track_id=lap.track_id
    )


def _catalog_windows(lap: LapTrace, catalogue: dict[str, Any], *, measure: bool = True) -> list:
    result = []
    for identity in catalogue.get("corners") or []:
        measured = _slice_circular(lap, identity["brake_spline"], identity["s1"])
        if not measure:
            result.append((identity, measured, None))
            continue
        windows = segment_corners(measured)
        # A canonical region must resolve one measured corner. A split/merged reference is
        # ambiguous: don't guess which minimum receives this label.
        if len(windows) != 1:
            result.append((identity, measured, None))
            continue
        window = windows[0]
        apex = measured.spline[window[1]]
        if (apex - identity["s0"]) % 1 > (identity["s1"] - identity["s0"]) % 1:
            result.append((identity, measured, None))
            continue
        result.append((identity, measured, window))
    return result


def _brake_point(lap: LapTrace, measured: LapTrace, apex: int) -> float | None:
    point = corner_signatures(measured, [(0, apex, len(measured) - 1)])[0].brake_point_spline
    if point is None or point != measured.spline[0]:
        return point
    # A driver/reference can start braking before the catalogue anchor. Continue an observed
    # contiguous application backwards in the full trace, including across S/F; don't clip it
    # at the comparison window and falsely report the same brake point for every lap.
    i = min(range(len(lap)), key=lambda k: abs(lap.spline[k] - point))
    for _ in range(len(lap)):
        previous = (i - 1) % len(lap)
        if lap.brake[previous] <= 0.05:
            return lap.spline[i]
        i = previous
    return None  # no observable onset when the brake is held for the whole lap


def reference_identity(archive: dict[str, Any]) -> str:
    """Content identity shared by geometry and comparisons; no local paths escape."""
    content = {key: archive.get(key) for key in ("car", "track", "lap", "trace")}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _channel_valid(archive: dict[str, Any], name: str) -> bool:
    trace = _metadata(archive, "trace")
    fields, samples = trace.get("fields") or [], trace.get("samples") or []
    if name not in fields or not samples:
        return False
    i = fields.index(name)
    try:
        return all(not isinstance(row[i], bool) and math.isfinite(float(row[i])) for row in samples)
    except (IndexError, TypeError, ValueError):
        return False


def _combo(archive: dict[str, Any]) -> tuple[Any, Any, Any]:
    combo = archive_combo(archive)
    return (combo[0], combo[1], combo[2] or "") if combo else (None, None, None)


def _metadata(archive: dict[str, Any], key: str) -> dict[str, Any]:
    value = archive.get(key)
    return value if isinstance(value, dict) else {}


def _reference_provenance_valid(
    archive: dict[str, Any], *, expected_combo: tuple[str, str, str | None] | None = None
) -> bool:
    if not qualify_archive(
        archive, use="reference_comparison", expected_combo=expected_combo
    ).allowed:
        return False
    generator = _metadata(archive, "generator")
    name = str(generator.get("name") or "")
    if "reference_lap" in name or name.startswith("trace_replay:"):
        return False
    if archive.get("import_format") == "generated_reference_v1":
        return False
    if archive.get("source") == "in_game":
        return True
    if archive.get("source") != "imported" or archive.get("import_format") not in {
        "motec_csv",
        "track_titan_reference_v1",
    }:
        return False
    tt = generator.get("tt_reference")
    return not isinstance(tt, dict) or tt.get("partial") is not True


def _normalise_finish_wrap(lap: LapTrace) -> LapTrace | None:
    """Trim only the measured post-S/F tail of a completed native trace, in memory.

    The archive's final sample can be the first packet just over S/F while eMs still belongs
    to the completed lap. Sorting it into the beginning corrupts elapsed-time alignment.
    Retain the pre-finish coverage and lap duration; never invent a sample at spline zero.
    """
    cut = finish_wrap_cut(lap.spline, lap.t_s)
    if cut is None:
        return None
    if cut == len(lap):
        return lap
    changes = {
        field.name: getattr(lap, field.name)[:cut]
        for field in fields(lap)
        if isinstance(getattr(lap, field.name), list) and len(getattr(lap, field.name)) == len(lap)
    }
    changes.update(_kappa=None, _lat_g=None, _long_g=None)
    return replace(lap, **changes)


def _valid_trace(archive: dict[str, Any]) -> LapTrace | None:
    # The general dynamics decoder's best-effort defaults are useful for other callers, but
    # cannot become a zero performance verdict here. Verify the raw comparison channels first.
    lap = _metadata(archive, "lap")
    if lap.get("is_valid") is not True:
        return None
    if not all(_channel_valid(archive, key) for key in ("spline", "speed", "eMs")):
        return None
    try:
        out = lap_trace_from_archive(archive)
        out = _normalise_finish_wrap(out)
        if out is None:
            return None
        if completed_trace_reason(out.spline, [t * 1000 for t in out.t_s], out.v_ms, out.lap_ms):
            return None
        return out
    except (TypeError, ValueError):
        return None


def _at(lap: LapTrace, values: list[float], spline: float) -> float | None:
    if spline < lap.spline[0] or spline > lap.spline[-1]:
        return None
    i = bisect_left(lap.spline, spline)
    if i == 0:
        return values[0]
    a, b = lap.spline[i - 1], lap.spline[i]
    return values[i - 1] + (values[i] - values[i - 1]) * (spline - a) / (b - a)


def build_corner_comparison(
    archive: dict[str, Any],
    reference: dict[str, Any] | None,
    corner_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bounded latest-completed-lap MAP metrics on the reference's canonical windows.

    Positive time is lost; positive brake-onset metres means later braking. Exact car, track
    and layout identities plus explicit valid timed traces are required before any verdict.
    """
    result: dict[str, Any] = {
        "available": False,
        "reason": "reference unavailable",
        "corners": [],
        "lap_uuid": archive.get("lap_uuid"),
        "session_uuid": archive.get("session_uuid"),
        "lap_n": _metadata(archive, "lap").get("lap_n"),
        "car_id": _combo(archive)[0],
        "track_id": _combo(archive)[1],
        "track_layout": _combo(archive)[2],
    }
    if reference is None:
        return result
    subject_qualification = qualify_archive(archive, use="analysis")
    if not subject_qualification.allowed:
        result["reason"] = f"lap qualification: {subject_qualification.reason}"
        return result
    combo = _combo(archive)
    reference_qualification = qualify_archive(
        reference,
        use="reference_comparison",
        expected_combo=combo if combo[0] and combo[1] else None,
    )
    if not reference_qualification.allowed:
        result["reason"] = f"reference qualification: {reference_qualification.reason}"
        return result
    result["reference_id"] = reference_identity(reference)
    result["reference_lap_uuid"] = reference.get("lap_uuid")
    result["reference_source"] = reference.get("source") or "unknown"
    result["reference_import_format"] = reference.get("import_format")
    result["lap_source"] = archive.get("source") or "unknown"
    if not _reference_provenance_valid(reference, expected_combo=combo):
        result["reason"] = "measured reference provenance unavailable/unsupported"
        return result
    if not combo[0] or not combo[1] or combo != _combo(reference):
        result["reason"] = "car/track/layout mismatch or unknown identity"
        return result
    lap, ref = _valid_trace(archive), _valid_trace(reference)
    if lap is None or ref is None:
        result["reason"] = "valid completed lap/reference trace unavailable"
        return result
    # Geometry is needed for the canonical corner segmentation and for signed physical metres.
    if not all(_channel_valid(reference, key) for key in ("px", "pz")):
        result["reason"] = "reference geometry unavailable"
        return result
    catalogue = _canonical_catalog(reference, corner_catalog)
    windows = _catalog_windows(ref, catalogue)
    if not windows:
        result["reason"] = "canonical reference corners unavailable"
        return result
    distances = [0.0]
    for i in range(1, len(ref)):
        distances.append(
            distances[-1] + math.hypot(ref.x[i] - ref.x[i - 1], ref.z[i] - ref.z[i - 1])
        )
    rows = []
    for identity, measured, window in windows:
        if window is None:
            rows.append(
                {
                    "id": identity["corner_id"],
                    "label": identity["corner_id"],
                    "phase": "unavailable",
                    "time_loss_s": None,
                    "brake_onset_delta_m": None,
                    "min_speed_kmh": None,
                    "reference_min_speed_kmh": None,
                    "apex_speed_kmh": None,
                    "reference_apex_speed_kmh": None,
                    "reason": "reference phase boundaries unresolved in canonical region",
                }
            )
            continue
        entry, apex, exit_i = window
        signature = corner_signatures(measured, [(0, apex, exit_i)])[0]
        start, end = measured.spline[entry], measured.spline[exit_i]
        driver_window = _slice_circular(lap, start, end)
        speed = min((v * 3.6 for v in driver_window.v_ms), default=None)
        apex_speed = _at(lap, lap.v_ms, measured.spline[apex])
        ts, te = _at(lap, lap.t_s, start), _at(lap, lap.t_s, end)
        loss = (
            None
            if ts is None or te is None
            else (
                te
                - ts
                + (lap.lap_ms / 1000 if end < start else 0)
                - (measured.t_s[exit_i] - measured.t_s[entry])
            )
        )
        brake_delta = None
        if (
            signature.brake_point_spline is not None
            and _channel_valid(reference, "brake")
            and _channel_valid(archive, "brake")
        ):
            # Same window and detector as the reference signature; do not independently match
            # driver corner numbers (different driving can split/merge speed minima).
            driver_brake_window = _slice_circular(lap, identity["brake_spline"], end)
            if len(driver_brake_window) >= 3:
                driver_apex = min(
                    range(len(driver_brake_window)), key=lambda i: driver_brake_window.v_ms[i]
                )
                driver_point = _brake_point(lap, driver_brake_window, driver_apex)
                ref_point = _brake_point(ref, measured, apex)
                if driver_point is not None and ref_point is not None:
                    rd = _at(ref, distances, ref_point)
                    dd = _at(ref, distances, driver_point)
                    if rd is not None and dd is not None:
                        brake_delta = dd - rd
                        length = distances[-1]
                        if length > 0:
                            brake_delta = (brake_delta + length / 2) % length - length / 2
        rows.append(
            {
                "id": identity["corner_id"],
                "label": identity["corner_id"],
                "phase": "measured_decel_to_recovery",
                "entry_spline": start,
                "exit_spline": end,
                "min_speed_kmh": None if speed is None else round(speed, 1),
                "reference_min_speed_kmh": round(signature.min_speed_kmh, 1),
                "apex_speed_kmh": None if apex_speed is None else round(apex_speed * 3.6, 1),
                "reference_apex_speed_kmh": round(measured.v_ms[apex] * 3.6, 1),
                "brake_onset_delta_m": None if brake_delta is None else round(brake_delta, 1),
                "time_loss_s": None if loss is None else round(loss, 3),
                "source": "completed_archive/reference_trace/shared_corner_window",
            }
        )
    opportunities = [r for r in rows if r["time_loss_s"] is not None and r["time_loss_s"] > 0]
    result.update(
        available=True,
        reason="verified same-combo completed lap/reference",
        corners=rows,
        corner_catalog_id=catalogue.get("id"),
        corner_catalog_source=catalogue.get("source"),
        largest_opportunity_id=max(opportunities, key=lambda r: r["time_loss_s"])["id"]
        if opportunities
        else None,
    )
    return result


__all__ = ["MAX_OUTLINE_POINTS", "build_track_map", "LapTrace"]
