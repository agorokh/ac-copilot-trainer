"""Offline replay of retained lap archives through ``CoachRuntime`` with the cue-exposure
journal on (issue #989, stage 0).

Reads lap archives, never writes to them. Starts no simulator, sidecar, worker or audio. Each
session's laps are fed in lap order through a fresh runtime built from a reference lap of the
same car and track taken from a *different* session, mirroring the hooks the live server runs
after each completed lap (rolling-best fold; brake calibration only when the lap qualifies for
``human_progression``).

    python -m tools.ai_sidecar.coaching_trial_replay --laps-dir <journal/laps> --out <new dir>

The lap-archive to frame conversion is :func:`shadow_replay._frames`, the existing validated
replay boundary. ``tools/ac_harness/trace_replay.py`` drives the Lua modules under ``lupa`` and
has no ``CoachRuntime`` path, so it is not reused here.

Every session is replayed twice: once with the stock ledger and once with the recording ledger.
The two advisory streams are serialized and compared byte for byte; a difference is an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.ai_sidecar.coaching_runtime import CoachRuntime, build_coach_runtime
from tools.ai_sidecar.coaching_trial import ExposureJournal, TrialRecorder
from tools.ai_sidecar.lap_dynamics import lap_trace_from_archive
from tools.ai_sidecar.voice.shadow_replay import _frames
from tools.lap_qualification import (
    archive_combo,
    archive_identity,
    duplicate_identity_reasons,
    qualify_archive,
)

MANIFEST_SCHEMA = "coaching_trial_replay_v1"
DEFAULT_MIN_LAPS = 5


class ReplayError(RuntimeError):
    """The replay cannot produce trustworthy evidence."""


@dataclass
class LapSource:
    path: str
    sha256: str
    record: dict[str, Any]
    lap_n: int
    lap_uuid: str
    lap_ms: float


@dataclass
class SessionPlan:
    session_uuid: str
    combo: tuple[str, str, str | None]
    laps: list[LapSource] = field(default_factory=list)


def load_archive(path: Path) -> tuple[dict[str, Any], str]:
    """Read one archive once; hash exactly the bytes that were parsed."""
    data = path.read_bytes()
    record = json.loads(data)
    if not isinstance(record, dict):
        raise ValueError("archive_root_invalid")
    return record, hashlib.sha256(data).hexdigest()


def discover_sessions(
    paths: Sequence[Path], *, min_laps: int = DEFAULT_MIN_LAPS
) -> tuple[list[SessionPlan], list[LapSource], list[dict[str, str]]]:
    """Group analysis-eligible archives into sessions.

    Returns ``(sessions, eligible_laps, rejected)``. ``rejected`` names every archive that was
    not used and why; nothing is dropped silently.
    """
    files = sorted(
        {
            file
            for path in paths
            for file in ([path] if path.is_file() else sorted(path.glob("lap_*.json")))
        }
    )
    loaded: list[tuple[Path, dict[str, Any], str]] = []
    rejected: list[dict[str, str]] = []
    for file in files:
        try:
            record, digest = load_archive(file)
        except (OSError, ValueError) as exc:
            rejected.append({"path": str(file), "reason": f"unreadable: {exc}"})
            continue
        loaded.append((file, record, digest))
    duplicates = duplicate_identity_reasons([record for _, record, _ in loaded])
    eligible: list[LapSource] = []
    for index, (file, record, digest) in enumerate(loaded):
        if index in duplicates:
            rejected.append({"path": str(file), "reason": duplicates[index]})
            continue
        qualification = qualify_archive(record, use="analysis")
        if not qualification.allowed:
            rejected.append({"path": str(file), "reason": f"analysis: {qualification.reason}"})
            continue
        identity = archive_identity(record)
        lap_n, lap_ms = identity["lap_n"], identity["lap_ms"]
        session, lap_uuid = identity["session_uuid"], identity["lap_uuid"]
        if (
            not isinstance(session, str)
            or not session
            or not isinstance(lap_uuid, str)
            or not lap_uuid
            or type(lap_n) is not int
            or isinstance(lap_ms, bool)
            or not isinstance(lap_ms, (int, float))
            or archive_combo(record) is None
        ):
            rejected.append({"path": str(file), "reason": "session_or_lap_identity_unavailable"})
            continue
        eligible.append(LapSource(str(file), digest, record, lap_n, lap_uuid, float(lap_ms)))
    grouped: dict[tuple[str, tuple[str, str, str | None]], SessionPlan] = {}
    for lap in eligible:
        combo = archive_combo(lap.record)
        session = str(lap.record["session_uuid"])
        grouped.setdefault((session, combo), SessionPlan(session, combo)).laps.append(lap)
    sessions = []
    for plan in grouped.values():
        plan.laps.sort(key=lambda lap: lap.lap_n)
        if len(plan.laps) >= min_laps:
            sessions.append(plan)
        else:
            rejected.extend(
                {"path": lap.path, "reason": f"session_shorter_than_{min_laps}_eligible_laps"}
                for lap in plan.laps
            )
    sessions.sort(key=lambda plan: (plan.combo, plan.session_uuid))
    return sessions, eligible, rejected


def _build_runtime(reference: LapSource, combo: tuple[str, str, str | None]) -> CoachRuntime | None:
    return build_coach_runtime(
        reference.record,
        expected_combo=combo,
        use_environment=False,
        practice_drills=False,
    )


def choose_reference(session: SessionPlan, eligible: Sequence[LapSource]) -> LapSource | None:
    """Fastest lap of the same combo from another session that the runtime accepts as a live
    reference. The replayed session never supplies its own technique target.
    """
    candidates = sorted(
        (
            lap
            for lap in eligible
            if lap.record.get("session_uuid") != session.session_uuid
            and archive_combo(lap.record) == session.combo
        ),
        key=lambda lap: lap.lap_ms,
    )
    for lap in candidates:
        if _build_runtime(lap, session.combo) is not None:
            return lap
    return None


def _drive(
    session: SessionPlan, runtime: CoachRuntime, recorder: TrialRecorder | None
) -> tuple[bytes, list[dict[str, Any]]]:
    """Feed a session through ``runtime``. Returns the serialized advisory stream and lap notes.

    Used for both arms of the identity check, so the only difference between them is the ledger.
    """
    stream: list[dict[str, Any]] = []
    laps: list[dict[str, Any]] = []
    clock_ms = 0.0
    for ordinal, lap in enumerate(session.laps, start=1):
        frames, reason, _ = _frames(lap.record)
        note = {
            "lap": ordinal,
            "lap_n": lap.lap_n,
            "lap_uuid": lap.lap_uuid,
            "lap_ms": lap.lap_ms,
            "sha256": lap.sha256,
            "replayed": reason is None,
            "skip_reason": reason,
        }
        laps.append(note)
        if reason is not None:
            if recorder is not None:
                recorder.note_lap(**note)
            continue
        for frame in frames:
            frame["lap"] = ordinal
            t_ms = clock_ms + frame["eMs"]
            out = (
                recorder.observe(frame, t_ms=t_ms)
                if recorder is not None
                else runtime.observe(frame)
            )
            stream.extend({"lap": ordinal, "t_ms": t_ms, **asdict(adv)} for adv in out)
        clock_ms += lap.lap_ms
        if recorder is not None:
            recorder.note_lap(**note)
        # Mirror the live server's completed-lap hooks.
        runtime.note_completed_lap(lap.lap_ms, is_valid=True)
        if qualify_archive(lap.record, use="human_progression").allowed:
            track = lap.record.get("track") if isinstance(lap.record.get("track"), dict) else {}
            runtime.calibrate_from_driver_lap(
                lap_trace_from_archive(lap.record),
                track_id=track.get("id") if isinstance(track.get("id"), str) else None,
                track_layout=track.get("layout") if isinstance(track.get("layout"), str) else None,
            )
    if recorder is not None:
        recorder.finish()
    data = json.dumps(stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return data.encode("utf-8"), laps


def replay_session(
    session: SessionPlan, reference: LapSource, *, journal_path: Path | None
) -> dict[str, Any]:
    """Replay one session with the journal on and prove the coaching output did not change."""
    plain = _build_runtime(reference, session.combo)
    recorded = _build_runtime(reference, session.combo)
    if plain is None or recorded is None:
        raise ReplayError(f"reference_rejected_for_session:{session.session_uuid}")
    baseline, _ = _drive(session, plain, None)
    journal = ExposureJournal(journal_path)
    try:
        recorder = TrialRecorder(
            recorded,
            journal=journal,
            session_id=session.session_uuid,
            context={
                "combo": list(session.combo),
                "reference_lap_uuid": reference.lap_uuid,
                "reference_sha256": reference.sha256,
                "source": "offline_replay",
            },
        )
        journaled, laps = _drive(session, recorded, recorder)
    finally:
        journal.close()
    if journaled != baseline:
        raise ReplayError(f"coaching_output_changed_by_journal:{session.session_uuid}")
    return {
        "session_uuid": session.session_uuid,
        "combo": list(session.combo),
        "journal": journal_path.name if journal_path is not None else None,
        "events": len(journal.events),
        "advisory_stream_sha256": hashlib.sha256(journaled).hexdigest(),
        "default_output_identical": True,
        "reference": {
            "lap_uuid": reference.lap_uuid,
            "session_uuid": reference.record.get("session_uuid"),
            "lap_ms": reference.lap_ms,
            "sha256": reference.sha256,
        },
        "laps": laps,
        "journal_events": journal.events if journal_path is None else None,
    }


def _inside(path: Path, parents: Sequence[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved == p.resolve() or p.resolve() in resolved.parents for p in parents)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--laps-dir", action="append", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new directory for journals")
    parser.add_argument("--min-laps", type=int, default=DEFAULT_MIN_LAPS)
    parser.add_argument("--max-sessions", type=int, default=0, help="0 = all")
    args = parser.parse_args(argv)
    if any(not path.exists() for path in args.laps_dir):
        parser.error("every --laps-dir must exist")
    if _inside(args.out, [p if p.is_dir() else p.parent for p in args.laps_dir]):
        parser.error("--out must not be inside a lap archive directory (archives are immutable)")
    try:
        args.out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("--out already exists; journals are never overwritten")
    sessions, eligible, rejected = discover_sessions(args.laps_dir, min_laps=args.min_laps)
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "eligible_laps": len(eligible),
        "rejected": rejected,
        "sessions": [],
        "sessions_without_reference": [],
    }
    for session in sessions:
        if args.max_sessions and len(manifest["sessions"]) >= args.max_sessions:
            break
        reference = choose_reference(session, eligible)
        if reference is None:
            manifest["sessions_without_reference"].append(session.session_uuid)
            continue
        # A session id comes from archive content: never let it choose a path.
        digest = hashlib.sha256(session.session_uuid.encode("utf-8")).hexdigest()[:16]
        summary = replay_session(
            session, reference, journal_path=args.out / f"session-{digest}.trial.jsonl"
        )
        summary.pop("journal_events")
        manifest["sessions"].append(summary)
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"replayed {len(manifest['sessions'])} session(s); "
        f"{len(manifest['sessions_without_reference'])} without a reference; "
        f"{len(rejected)} archive(s) rejected"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
