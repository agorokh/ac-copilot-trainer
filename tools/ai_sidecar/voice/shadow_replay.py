"""Silent, measured-lap replay through the existing coaching and voice pipeline (#815).

The selected lap is driving stimulus, never a technique reference. A separate
reference must pass the existing live-reference guards. Legacy unknown-control
references are engineering baselines only and cannot qualify human evaluation.
Each production producer runs in
its own fresh lane, against the same immutable recording; their cues are not
combined. This module neither opens files nor starts workers, audio, or services.
Qualification may read the canonical attribution store, as at every archive
boundary. The caller owns stable source-byte loading and report publication.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from tools.ai_sidecar.coaching_runtime import CoachRuntime, build_coach_runtime
from tools.ai_sidecar.lap_dynamics import lap_trace_from_archive
from tools.ai_sidecar.realtime_observer import (
    CAL_MATCH_TOL_M,
    Advisory,
    RealtimeObserver,
    build_observer_from_reference,
)
from tools.ai_sidecar.track_reference import (
    CornerReference,
    build_references,
    sustained_brake_onsets,
)
from tools.ai_sidecar.voice import vocabulary
from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.manifest import MANIFEST_VERSION, ClipEntry, Manifest
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler, SchedulingDecision
from tools.lap_archive_export import _MOTEC_CHANNELS
from tools.lap_qualification import (
    AttributionError,
    archive_combo,
    archive_identity,
    payload_sha256,
    qualify_archive,
    resolve_archive_provenance,
)
from tools.lap_trace_validity import completed_trace_reason, finish_wrap_cut

_REQUIRED = ("spline", "speed", "eMs", "brake", "throttle", "steer", "gear", "px", "py", "pz")
_MODELED_CLIP_MS = 400.0
# The native exporter/reader contract names measured lateral acceleration in G.
# This optional channel does not inherit the ten canonical channels' qualification.
_LATERAL_G_UNIT = next(unit for _, unit, field in _MOTEC_CHANNELS if field == "accG_lat")
_GRIP_ALIASES = ("accG_lat", "lat_g", "latg", "accG", "grip", "grip_used")


def _finite(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _manifest() -> Manifest:
    """Vocabulary-only manifest, as in timing_report; no bank or PCM is loaded."""
    return Manifest(
        version=MANIFEST_VERSION,
        samplerate=22050,
        voice_signature="vocabulary-only-shadow",
        vocabulary_hash=vocabulary.vocabulary_hash(),
        clips={
            phrase.clip_id: ClipEntry(
                clip_id=phrase.clip_id,
                file=f"{phrase.clip_id}.wav",
                kind=phrase.kind,
                urgency=phrase.urgency,
                register=phrase.register,
                corner=phrase.corner,
                text=phrase.text,
                sha256="0" * 64,
            )
            for phrase in vocabulary.iter_vocabulary()
        },
    )


def _frames(archive: dict[str, Any]) -> tuple[list[dict[str, float]], str | None, int]:
    """Validate even legacy archives; never replace bad times with an invented cadence."""
    trace = archive.get("trace")
    if not isinstance(trace, dict):
        return [], "trace_unavailable", 0
    fields, samples = trace.get("fields"), trace.get("samples")
    if not isinstance(fields, list) or not all(isinstance(v, str) for v in fields):
        return [], "trace_fields_invalid", 0
    if len(fields) != len(set(fields)):
        return [], "duplicate_trace_channel", 0
    missing = [name for name in _REQUIRED if name not in fields]
    if missing:
        return [], "missing_measured_channels:" + ",".join(missing), 0
    if not isinstance(samples, list) or len(samples) < 2:
        return [], "insufficient_trace_samples", 0
    if any(
        not isinstance(row, list) or len(row) != len(fields) or not all(map(_finite, row))
        for row in samples
    ):
        return [], "nonfinite_or_missing_trace_value", 0
    frames = [dict(zip(fields, row, strict=True)) for row in samples]
    times, splines = ([frame[key] for frame in frames] for key in ("eMs", "spline"))
    if any(t < 0 for t in times):
        return [], "negative_elapsed_time", 0
    if any(a >= b for a, b in zip(times, times[1:], strict=False)):
        return [], "nonmonotonic_elapsed_time", 0
    cut = finish_wrap_cut(splines, times)
    if cut is None:
        return [], "nonmonotonic_trace", 0
    trimmed = len(frames) - cut
    frames = frames[:cut]
    lap = archive.get("lap")
    lap_ms = lap.get("lap_ms") if isinstance(lap, dict) else None
    if not _finite(lap_ms):
        return [], "invalid_lap_duration", 0
    if lap.get("is_valid") is not True or lap.get("complete") is False or lap.get("partial"):
        return [], "lap_validity_or_completion_unproved", 0
    reason = completed_trace_reason(
        splines[:cut], times[:cut], [f["speed"] for f in frames], lap_ms
    )
    if reason:
        return [], reason, 0
    if any(b - a > 1000 for a, b in zip(times, times[1:], strict=False)):
        return [], "trace_time_gap", 0
    if any(not 0 <= f[k] <= 1 for f in frames for k in ("brake", "throttle")):
        return [], "control_value_out_of_range", 0
    # No wrap/extra lap is synthesized. Optional grip requires its own boundary proof;
    # never let a raw runtime alias bypass that proof by riding through this dictionary.
    for frame in frames:
        frame["lap"] = 1
        for alias in _GRIP_ALIASES:
            frame.pop(alias, None)
    return frames, None, trimmed


def _lateral_grip(archive: dict[str, Any], frames: list[dict[str, float]]) -> dict[str, Any]:
    """Apply only a qualified native G channel; field names and magnitude are not proof."""
    resolved = resolve_archive_provenance(archive)
    envelope = resolved.get("qualification")
    envelope = envelope if isinstance(envelope, Mapping) else {}
    channels = envelope.get("channels")
    channels = channels if isinstance(channels, Mapping) else {}
    metadata = channels.get("accG_lat")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    result = {
        "available": False,
        "source_field": "accG_lat",
        "runtime_field": "lat_g",
        "expected_unit": _LATERAL_G_UNIT,
        "unit": metadata.get("unit"),
        "basis": metadata.get("basis"),
        "reason": "channel_semantics_unverified",
    }
    fields = archive["trace"]["fields"]
    if envelope.get("resolution_error"):
        result["reason"] = "attribution_resolution_failed"
    elif "accG_lat" not in fields:
        result["reason"] = "missing_channel"
    elif metadata.get("basis") == "measured" and metadata.get("unit") == _LATERAL_G_UNIT:
        index = fields.index("accG_lat")
        values = [row[index] for row in archive["trace"]["samples"][: len(frames)]]
        # Match the native lap reader's all-zero unavailable-channel convention.
        if not any(values):
            result["reason"] = "all_zero_channel_unavailable"
        else:
            for frame, value in zip(frames, values, strict=True):
                frame["lat_g"] = value
            result.update(available=True, reason="qualified_measured_native_channel")
    return result


def _source(archive: dict[str, Any], *, use: str, combo=None) -> dict[str, Any]:
    result = asdict(qualify_archive(archive, use=use, expected_combo=combo))
    result["identity"] = {
        key: value if value is None or isinstance(value, str) or _finite(value) else None
        for key, value in archive_identity(archive).items()
    }
    try:
        result["payload_sha256"] = payload_sha256(archive)
    except AttributionError:
        result["payload_sha256"] = None
    return result


def _measured_lap(archive: dict[str, Any], frames: list[dict[str, float]]):
    """A derived prefix view for geometry; never edit or requalify the original evidence."""
    trace = archive["trace"]
    return lap_trace_from_archive(
        {**archive, "trace": {**trace, "samples": trace["samples"][: len(frames)]}}
    )


def _brake_events(
    archive: dict[str, Any], frames: list[dict[str, float]], refs: list[CornerReference]
) -> list[dict[str, Any]]:
    lap = _measured_lap(archive, frames)
    onsets = sustained_brake_onsets(lap, 0.0, frames[-1]["spline"])
    by_spline = {f["spline"]: (i, f) for i, f in enumerate(frames)}
    events = []
    for onset in onsets:
        if onset not in by_spline:
            continue
        index, frame = by_spline[onset]
        end_index = index
        while end_index + 1 < len(frames) and frames[end_index + 1]["brake"] > 0.05:
            end_index += 1
        # A true pedal onset usually precedes the speed-drop-based segment entry.
        # Match by run/window overlap; never relabel a clipped in-window sample as onset.
        corners = [
            r.index
            for r in refs
            if onset <= r.spline_hi and frames[end_index]["spline"] >= r.spline_lo
        ]
        events.append(
            {
                "event_id": len(events),
                "sample_index": index,
                "t_event_ms": frame["eMs"],
                "spline": onset,
                "end_spline": frames[end_index]["spline"],
                "corner": corners[0] if len(corners) == 1 else None,
                "corner_reason": "matched_window" if len(corners) == 1 else "outside_unique_window",
            }
        )
    return events


def _match_brake_event(
    advisory: Advisory, events: list[dict[str, Any]], refs: list[CornerReference], track_m: float
) -> dict[str, Any] | None:
    # Only brake-targeted cues have a brake lead. A release/exit verdict is not a late brake cue.
    if advisory.kind not in {"late_brake", "early_brake", "save"}:
        return None
    ref = next((r for r in refs if r.index == advisory.corner), None)
    if ref is None:
        return None
    mark = advisory.detail.get("brake_point_spline", ref.best_brake_point_spline)
    if not _finite(mark):
        return None
    matched = [
        e
        for e in events
        if e["corner"] == advisory.corner and abs(e["spline"] - mark) * track_m <= CAL_MATCH_TOL_M
    ]
    # A corner can contain several zones. Never silently choose a different measured brake event.
    return min(matched, key=lambda e: abs(e["spline"] - mark)) if matched else None


def _lane(
    producer: RealtimeObserver | CoachRuntime,
    frames: list[dict[str, float]],
    events: list[dict[str, Any]],
    refs: list[CornerReference],
    *,
    track_m: float,
    manifest: Manifest,
    durations: Mapping[str, float],
    config: VoiceConfig,
) -> dict[str, Any]:
    playback = RecordingPlayback()  # Never inject a caller's playback: this path is always inert.
    now = [frames[0]["eMs"] / 1000.0]
    cues: list[dict[str, Any]] = []
    by_advisory: dict[int, dict[str, Any]] = {}
    by_utterance: dict[int, dict[str, Any]] = {}
    # Keep advisory/utterance objects alive throughout the replay so identity keys cannot be reused.
    retained: list[object] = []

    def decision(event: SchedulingDecision) -> None:
        row = by_advisory.get(id(event.advisory)) if event.advisory is not None else None
        if row is not None and event.utterance is not None:
            retained.append(event.utterance)
            by_utterance[id(event.utterance)] = row
            row.update(
                clip_id=event.utterance.clip_id,
                phrase=event.utterance.text,
                resolved_register=event.utterance.register,
                dedup_key=event.utterance.dedup_key,
            )
        if row is None and event.utterance is not None:
            row = by_utterance.get(id(event.utterance))
        if row is None:
            raise RuntimeError("shadow_scheduler_event_without_advisory")
        row["decisions"].append(
            {
                "reason": event.reason,
                "t_ms": event.now_s * 1000,
                "age_ms": (event.now_s - event.enqueued_at_s) * 1000,
            }
        )
        if event.reason == "dispatched":
            row["status"] = "dispatched"
            row["t_dispatch_ms"] = event.now_s * 1000
            row["advisory_to_dispatch_ms"] = (event.now_s - event.enqueued_at_s) * 1000
        elif event.reason not in {"resolved", "barge_in"}:
            row["status"] = event.reason

    scheduler = Scheduler(
        Resolver(manifest), playback, config, clock=lambda: now[0], on_decision=decision
    )
    playing_until_ms = -1.0
    for frame in frames:
        now[0] = frame["eMs"] / 1000.0
        if playback.current is not None and frame["eMs"] >= playing_until_ms:
            playback.finish()
        for advisory in producer.observe(frame):
            retained.append(advisory)
            brake = _match_brake_event(advisory, events, refs, track_m)
            row = {
                "cue_id": len(cues),
                "corner": advisory.corner,
                "kind": advisory.kind,
                "urgency": advisory.urgency,
                "requested_register": advisory.register,
                "detail": dict(advisory.detail),
                "t_telemetry_event_ms": frame["eMs"],
                "t_advisory_ms": frame["eMs"],
                "t_dispatch_ms": None,
                "advisory_to_dispatch_ms": None,
                "measured_brake_event_id": brake["event_id"] if brake else None,
                "t_measured_brake_ms": brake["t_event_ms"] if brake else None,
                "producer_lead_budget_ms": (
                    (
                        producer.brake_lead_s
                        if isinstance(producer, CoachRuntime)
                        else getattr(producer, "_brake_prepare_lead_s", 0.0)
                    )
                    * 1000.0
                    if brake is not None and advisory.urgency == "prepare"
                    else None
                ),
                "status": "pending",
                "clip_id": None,
                "phrase": None,
                "dedup_key": None,
                "decisions": [],
            }
            cues.append(row)
            by_advisory[id(advisory)] = row
            scheduler.submit(advisory)
        winner = scheduler.process_pending(now[0])
        if winner is not None:
            playing_until_ms = frame["eMs"] + durations.get(winner.clip_id, _MODELED_CLIP_MS)

    for cue in cues:
        dispatch, mark = cue["t_dispatch_ms"], cue["t_measured_brake_ms"]
        cue["lead_to_measured_brake_ms"] = (
            mark - dispatch if dispatch is not None and mark is not None else None
        )
        cue["onset_before_measured_brake"] = (
            dispatch <= mark if dispatch is not None and mark is not None else None
        )
        cue["timing_reason"] = (
            "dispatched_against_measured_brake"
            if dispatch is not None and mark is not None
            else "not_dispatched"
            if dispatch is None
            else "no_matched_measured_brake"
        )
        cue["modeled_clip_duration_ms"] = (
            durations.get(cue["clip_id"], _MODELED_CLIP_MS) if cue["clip_id"] else None
        )
        lead, budget = cue["lead_to_measured_brake_ms"], cue["producer_lead_budget_ms"]
        cue["lead_meets_producer_budget"] = lead >= budget if lead is not None and budget else None
        duration = cue["modeled_clip_duration_ms"]
        cue["modeled_clip_finish_lead_ms"] = (
            lead - duration if lead is not None and duration else None
        )
        cue["modeled_clip_finishes_before_measured_brake"] = (
            cue["modeled_clip_finish_lead_ms"] >= 0
            if cue["modeled_clip_finish_lead_ms"] is not None
            else None
        )
        if cue["status"] in {"pending", "deferred"}:
            cue["status"] = "unprocessed_at_recording_end"
    dispatched = [c for c in cues if c["status"] == "dispatched"]
    comparisons = []
    for event in events:
        matching = [c for c in cues if c["measured_brake_event_id"] == event["event_id"]]
        sent = [c for c in matching if c["status"] == "dispatched"]
        comparisons.append(
            {
                "event_id": event["event_id"],
                "corner": event["corner"],
                "t_measured_brake_ms": event["t_event_ms"],
                "emitted_cue_ids": [c["cue_id"] for c in matching],
                "dispatched_cue_ids": [c["cue_id"] for c in sent],
                "reason": "compared"
                if sent
                else "suppressed"
                if matching
                else "no_matching_brake_cue_emitted",
            }
        )
    return {
        "available": True,
        "reason": "replayed" if cues else "no_advisories_emitted_on_this_recording",
        "frames_replayed": len(frames),
        "cues": cues,
        "emitted_count": len(cues),
        "dispatched_count": len(dispatched),
        "suppressed_count": len(cues) - len(dispatched),
        "late_brake_onset_count": sum(
            c["onset_before_measured_brake"] is False for c in dispatched
        ),
        "brake_event_results": comparisons,
        "checks": {
            "scheduler_diagnostics_complete": scheduler.decision_error_count == 0
            and len(dispatched) == len(playback.played),
            "non_vacuous_dispatch": bool(dispatched),
            "measured_brake_timing_available": any(
                c["lead_to_measured_brake_ms"] is not None for c in dispatched
            ),
            "all_dispatched_brake_cues_before_measured_onset": (
                all(
                    c["onset_before_measured_brake"]
                    for c in dispatched
                    if c["onset_before_measured_brake"] is not None
                )
                if any(c["onset_before_measured_brake"] is not None for c in dispatched)
                else None
            ),
            "stale_suppressed_count": sum(c["status"] in {"stale", "stale_deferred"} for c in cues),
            "dedup_suppressed_count": sum(c["status"] == "dedup" for c in cues),
            "all_brake_prepare_leads_meet_producer_budget": (
                all(
                    c["lead_meets_producer_budget"]
                    for c in dispatched
                    if c["lead_meets_producer_budget"] is not None
                )
                if any(c["lead_meets_producer_budget"] is not None for c in dispatched)
                else None
            ),
        },
        "diagnostic_error_count": scheduler.decision_error_count,
        "recording_playback_dispatch_count": len(playback.played),
        "cadence_ms": max(b["eMs"] - a["eMs"] for a, b in zip(frames, frames[1:], strict=False)),
    }


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    report["available"] = report["status"] == "replayed"
    report["reason"] = (
        "silent_replay_completed" if report["available"] else report["no_go_reasons"][-1]
    )
    report["engineering_validation"] = "replayed" if report["available"] else "unavailable"
    if any(
        lane.get("checks", {}).get("scheduler_diagnostics_complete") is False
        for lane in report["lanes"].values()
    ):
        report["engineering_validation"] = "invalid_diagnostics"
        report["no_go_reasons"].append("scheduler_diagnostics_incomplete")
    report["decision"] = {
        "human_evaluation": "no_go",
        "live_activation": "no_go",
        "reasons": report["no_go_reasons"],
    }
    for name in ("observer", "coach_v2"):
        report["lanes"].setdefault(
            name,
            {
                "available": False,
                "reason": report["reason"],
                "frames_replayed": 0,
                "emitted_count": 0,
                "dispatched_count": 0,
                "suppressed_count": 0,
                "late_brake_onset_count": 0,
                "cues": [],
                "checks": {},
                "brake_event_results": [],
            },
        )
    return report


def _conditions(stimulus: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare retained context without inferring equality from two absent fields."""
    rows = []
    for path in (
        ("car", "extendedPhysics"),
        ("conditions", "weatherType"),
        ("conditions", "ambientTempC"),
        ("assists",),
    ):
        values = []
        for archive in (stimulus, reference):
            value: Any = archive
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            values.append(value)
        left, right = values
        rows.append(
            {
                "field": ".".join(path),
                "stimulus": left,
                "reference": right,
                "status": "unknown"
                if left is None or right is None
                else "match"
                if left == right
                else "mismatch",
            }
        )
    return rows


def build_shadow_replay(
    stimulus: dict[str, Any],
    reference: dict[str, Any] | None = None,
    *,
    config: VoiceConfig | None = None,
    evidence_kind: str = "recorded_telemetry",
    manifest: Manifest | None = None,
    clip_durations_ms: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return JSON-compatible silent evidence; an analyzed lap never authorizes activation.

    ``synthetic_contract_test`` labels fixture/mistake-injection evidence explicitly.
    A provided manifest/duration map is metadata only: no WAV path is opened or
    decoded, and its availability, hashes and acoustic timing are not verified.
    """
    if evidence_kind not in {"recorded_telemetry", "synthetic_contract_test"}:
        raise ValueError("unsupported_shadow_evidence_kind")
    durations = dict(clip_durations_ms or {})
    if any(not isinstance(k, str) or not _finite(v) or v <= 0 for k, v in durations.items()):
        raise ValueError("invalid_clip_duration_metadata")
    config = config or VoiceConfig()
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "voice_shadow_replay",
        "evidence_kind": evidence_kind,
        "status": "no_go",
        "activation_allowed": False,
        "no_go_reasons": ["silent_replay_cannot_authorize_live_activation", "audio_not_verified"],
        "assumptions": {
            "clock": "unaltered_recorded_eMs; arbitration_at_recorded_samples",
            "playback": "RecordingPlayback_without_bank_or_worker",
            "clip_duration": "caller_metadata_or_400ms_model; not_measured_audio",
            "manifest": "caller_metadata_only" if manifest else "current_vocabulary_only",
            "lanes": "alternative_production_modes; counts_must_not_be_combined",
            "history": "one_recorded_lap; fresh_in_memory_state; no_synthetic_repetition",
            "profile_and_alien_environment": "ignored; canonical_attribution_policy_still_applies",
            "brake_event": "sustained_brake_onsets; observed_sample_time; 50m_reference_match",
        },
        "voice_config": {**asdict(config), "verbosity": config.verbosity.name.lower()},
        "measured_brake_events": [],
        "optional_channels": {},
        "lanes": {},
    }
    if not isinstance(stimulus, dict):
        report["no_go_reasons"].append("stimulus:archive_root_invalid")
        return _finish(report)
    report["stimulus"] = _source(stimulus, use="analysis")
    if not report["stimulus"]["allowed"]:
        report["no_go_reasons"].extend("stimulus:" + r for r in report["stimulus"]["reasons"])
        return _finish(report)
    if type(stimulus.get("schema_version")) is not int or stimulus["schema_version"] != 1:
        report["no_go_reasons"].append("stimulus:unsupported_archive_schema")
        return _finish(report)
    if stimulus.get("source") != "in_game" or stimulus.get("import_format") is not None:
        report["no_go_reasons"].append("stimulus:selected_native_source_required")
        return _finish(report)
    frames, reason, trimmed = _frames(stimulus)
    if reason:
        report["no_go_reasons"].append("stimulus:" + reason)
        return _finish(report)
    if report["stimulus"]["payload_sha256"] is None:
        report["no_go_reasons"].append("stimulus:nonfinite_or_unserializable_payload")
        return _finish(report)
    report["stimulus"].update(sample_count=len(frames), trimmed_finish_tail_samples=trimmed)
    report["optional_channels"]["lateral_grip"] = _lateral_grip(stimulus, frames)
    stimulus_refs = build_references(_measured_lap(stimulus, frames))
    report["measured_brake_events"] = _brake_events(stimulus, frames, stimulus_refs)
    report["brake_corner_basis"] = "stimulus_geometry"
    combo = archive_combo(stimulus)
    if combo is None:
        report["no_go_reasons"].append("stimulus:combo_identity_unavailable")
        return _finish(report)
    if reference is None:
        report["no_go_reasons"].append("independent_reference_unavailable")
        return _finish(report)
    if not isinstance(reference, dict):
        report["no_go_reasons"].append("reference:archive_root_invalid")
        return _finish(report)
    report["reference"] = _source(reference, use="live_reference", combo=combo)
    if not report["reference"]["allowed"]:
        report["no_go_reasons"].extend("reference:" + r for r in report["reference"]["reasons"])
        return _finish(report)
    if archive_combo(reference) != combo:
        report["no_go_reasons"].append("reference:combo_mismatch")
        return _finish(report)
    if report["reference"]["authority"] != "human":
        report["no_go_reasons"].append("reference:human_control_unproved")
    if (
        report["reference"]["payload_sha256"] == report["stimulus"]["payload_sha256"]
        or (reference.get("lap_uuid") and reference.get("lap_uuid") == stimulus.get("lap_uuid"))
        or (
            reference.get("session_uuid")
            and reference.get("session_uuid") == stimulus.get("session_uuid")
            and report["reference"]["identity"]["lap_n"] is not None
            and report["reference"]["identity"]["lap_n"] == report["stimulus"]["identity"]["lap_n"]
        )
    ):
        report["no_go_reasons"].append("reference:not_independent_of_stimulus")
        return _finish(report)
    _, reason, _ = _frames(reference)
    if reason:
        report["no_go_reasons"].append("reference:" + reason)
        return _finish(report)
    if report["reference"]["payload_sha256"] is None:
        report["no_go_reasons"].append("reference:nonfinite_or_unserializable_payload")
        return _finish(report)
    report["condition_comparison"] = _conditions(stimulus, reference)
    for comparison in report["condition_comparison"]:
        if comparison["status"] != "match":
            report["no_go_reasons"].append(
                "reference_condition_" + comparison["status"] + ":" + comparison["field"]
            )
    observer_diagnostics: dict[str, Any] = {}
    coach_diagnostics: dict[str, Any] = {}
    observer = build_observer_from_reference(
        reference, expected_combo=combo, diagnostics=observer_diagnostics
    )
    coach = build_coach_runtime(
        reference, expected_combo=combo, diagnostics=coach_diagnostics, use_environment=False
    )
    if observer is None or coach is None:
        report["no_go_reasons"].append("reference:usable_coaching_geometry_unavailable")
        report["builder_diagnostics"] = {
            "observer": observer_diagnostics,
            "coach_v2": coach_diagnostics,
        }
        return _finish(report)
    report["brake_corner_basis"] = "independent_reference_geometry"
    refs = observer._refs
    events = _brake_events(stimulus, frames, refs)
    report["measured_brake_events"] = events
    voice_manifest = manifest or _manifest()
    for name, producer in (("observer", observer), ("coach_v2", coach)):
        report["lanes"][name] = _lane(
            producer,
            frames,
            events,
            refs,
            track_m=observer._track_length_m,
            manifest=voice_manifest,
            durations=durations,
            config=config,
        )
    report["status"] = "replayed"
    report["coach_policy"] = {
        "assess_laps": coach.ledger.assess_laps,
        "hysteresis": coach.ledger.hysteresis,
        "lap_budget": coach.ledger.lap_budget,
    }
    if not report["optional_channels"]["lateral_grip"]["available"]:
        report["no_go_reasons"].append(
            "measured_lateral_grip_unavailable;coach_grip_gate_not_verified"
        )
    if not any(lane["dispatched_count"] for lane in report["lanes"].values()):
        report["no_go_reasons"].append("no_dispatched_cues;timing_not_proved")
    for name, lane in report["lanes"].items():
        if lane["late_brake_onset_count"]:
            report["no_go_reasons"].append(name + ":cue_onset_after_measured_brake")
        if lane["checks"]["all_brake_prepare_leads_meet_producer_budget"] is False:
            report["no_go_reasons"].append(name + ":measured_brake_lead_below_producer_budget")
    if reference["lap"]["lap_ms"] > stimulus["lap"]["lap_ms"]:
        report["no_go_reasons"].append("reference:slower_than_stimulus;teaching_value_unproved")
    return _finish(report)
