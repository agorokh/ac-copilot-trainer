"""CLI + orchestration for ``python -m tools.tt_ingest`` (issue #353, M-TT0).

The local retention pipeline (:func:`retain_sessions`) is pure-of-network and fully
unit-tested against ``tmp_path``: given already-fetched raw sessions it normalizes,
immutably retains, and indexes them. The network entrypoints (token mint + page
fetch) are thin and ``# pragma: no cover`` — they are proven live, not in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.tt_ingest.tt_auth import (
    TTAuthError,
    TTConfig,
    is_token_expired,
    mint_tokens,
    resolve_refresh_token,
    token_expiry,
    uid_from_token,
)
from tools.tt_ingest.tt_export import (
    COACHING_ENDPOINT_PREFIX,
    CURRICULUM_ENDPOINT_PREFIX,
    INDEX_FILENAME,
    LAST_SESSION_ENDPOINT_PREFIX,
    LAST_SESSION_WINDOW_MARKER,
    RetainedFile,
    TTExportError,
    build_index,
    endpoint_file,
    lake_root,
    relative_to_lake,
    sanitize_segment,
    session_lake_dir,
    sha256_hex,
    stable_fingerprint,
    write_immutable_json,
)
from tools.tt_ingest.tt_normalize import (
    DEFAULT_CURRICULUM_MIN_TIME_LOSS_S,
    DEFAULT_REFERENCE_COVERAGE_THRESHOLD,
    DEFAULT_REFERENCE_MAX_SPLINE_GAP,
    TTNormalizeError,
    build_harness_curriculum,
    build_reference_archive,
    build_sessions_index,
    normalize_session,
    split_session_id,
)
from tools.tt_ingest.tt_services import (
    TTServicesError,
    fetch_last_session_raw,
    fetch_session_coaching,
    parse_last_session,
)
from tools.tt_ingest.tt_vulcan import iter_all_sessions, session_summary

SESSIONS_INDEX_FILENAME = "sessions_index.json"
RAW_SESSION_ENDPOINT = "session"
# Both the raw /last-session payload AND the coaching bundle are retained one file PER LAP
# (``last_session_lap{N}.json`` / ``coaching_lap{N}.json``). The /last-session telemetry is
# lap-specific, so lap-keying it keeps each lap's raw evidence COHERENT with its coaching even
# when the same session later gains another lap (a single write-once ``last_session.json``
# would otherwise go stale against a newer lap's bundle).
LAST_SESSION_ENDPOINT_GLOB = f"{LAST_SESSION_ENDPOINT_PREFIX}*.json"
COACHING_ENDPOINT_GLOB = f"{COACHING_ENDPOINT_PREFIX}*.json"
REFERENCE_INPUT_GLOB = LAST_SESSION_ENDPOINT_GLOB
CURRICULUM_ENDPOINT_GLOB = f"{CURRICULUM_ENDPOINT_PREFIX}*.json"


def last_session_endpoint(lap: Any) -> str:
    """Endpoint (file stem) for a lap's raw /last-session payload: ``last_session_lap{lap}``."""
    return f"{LAST_SESSION_ENDPOINT_PREFIX}{lap}"


def last_session_window_endpoint(lap: Any, payload: Mapping[str, Any]) -> str:
    """Endpoint for an additional distinct /last-session segment window for one lap."""
    return (
        f"{last_session_endpoint(lap)}"
        f"{LAST_SESSION_WINDOW_MARKER}"
        f"{stable_fingerprint(dict(payload))}"
    )


def _last_session_endpoint_matches_lap(stem: str, lap: Any) -> bool:
    base = last_session_endpoint(lap)
    return stem == base or stem.startswith(f"{base}{LAST_SESSION_WINDOW_MARKER}")


def coaching_endpoint(lap: Any) -> str:
    """Endpoint (file stem) for a lap's coaching bundle: ``coaching_lap{lap}``."""
    return f"{COACHING_ENDPOINT_PREFIX}{lap}"


def curriculum_endpoint(lap: Any) -> str:
    """Endpoint (file stem) for a derived M-TT3 curriculum: ``curriculum_lap{lap}``."""
    return f"{CURRICULUM_ENDPOINT_PREFIX}{lap}"


@dataclass(frozen=True)
class ExportSummary:
    """Outcome of a retention run."""

    total: int
    retained_new: int
    skipped_existing: int
    lake_root: Path
    failed: int = 0
    indexed: int = 0

    def render(self) -> str:
        base = (
            f"retained {self.total} session(s) to {self.lake_root} "
            f"({self.retained_new} new, {self.skipped_existing} already present; "
            f"{self.indexed} total in lake)"
        )
        if self.failed:
            base += f"; {self.failed} session(s) skipped due to errors"
        return base


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# File-index globs (sessions_index is built from RAW_SESSION_ENDPOINT only — it normalizes
# vulcan sessions; the M-TT1 services endpoints are indexed for discovery/integrity but not
# normalized). Coaching is per-lap, so it is matched by glob, not a fixed name.
INDEXED_ENDPOINT_GLOBS = (
    f"{RAW_SESSION_ENDPOINT}.json",
    LAST_SESSION_ENDPOINT_GLOB,
    COACHING_ENDPOINT_GLOB,
)


def reindex_lake(root: Path, *, generated_at: str) -> int:
    """Rebuild both derived indexes from EVERY retained endpoint file in the lake.

    The indexes are a *derived view* of the immutable raw files — so they are rebuilt by
    scanning the whole lake on disk, never from one batch's records. A partial export can
    therefore never shrink the discovery index, and ``sessions_index.json`` always agrees
    with the raw files actually present (no batch-vs-disk divergence). The content-addressed
    file index covers vulcan ``session.json`` **and** the M-TT1 services endpoints
    (``last_session.json`` / ``coaching_lap{N}.json``); ``sessions_index.json`` is built from
    ``session.json`` only (it normalizes vulcan sessions). Returns the count of indexed files.
    """
    records: list[RetainedFile] = []
    normalized: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for pattern in INDEXED_ENDPOINT_GLOBS:
        for path in sorted(root.rglob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            try:
                data = path.read_bytes()
                raw = json.loads(data)
            except (OSError, ValueError):  # pragma: no cover - corrupt file skipped defensively
                continue
            endpoint = path.stem  # e.g. "session", "last_session", "coaching_lap5"
            records.append(
                RetainedFile(
                    session_key=path.parent.name,
                    endpoint=endpoint,
                    relative_path=relative_to_lake(path, root),
                    sha256=sha256_hex(data),
                    bytes=len(data),
                    written=False,
                )
            )
            if endpoint == RAW_SESSION_ENDPOINT and isinstance(raw, Mapping):
                normalized.append(normalize_session(raw))
    root.mkdir(parents=True, exist_ok=True)
    # sessions_index carries normalized telemetry conditions → allow_nan for lossless
    # round-trip; the file index (hashes/sizes/paths only) stays strict, portable JSON.
    write_immutable_json(
        root / SESSIONS_INDEX_FILENAME,
        build_sessions_index(normalized, generated_at=generated_at),
        overwrite=True,
        allow_nan=True,
    )
    write_immutable_json(
        root / INDEX_FILENAME, build_index(records, generated_at=generated_at), overwrite=True
    )
    return len(records)


def retain_sessions(
    sessions: Sequence[Mapping[str, Any]],
    *,
    lake_base: Path | None = None,
    generated_at: str | None = None,
) -> ExportSummary:
    """Normalize, immutably retain, and (re)index a batch of raw vulcan sessions.

    Each raw session is written **write-once** under
    ``journal/tt/{game}/{car}/{track}/{sessionKey}/session.json`` — raw evidence is never
    clobbered (data-immutability invariant). After the batch, both derived indexes are
    rebuilt from the *entire* lake on disk (see :func:`reindex_lake`), so a partial export
    never shrinks the index and the index always matches the immutable raw files.
    """
    root = lake_root(lake_base)
    stamp = generated_at or _iso_now()
    retained_new = 0
    processed = 0
    failed = 0

    for raw in sessions:
        try:
            row = normalize_session(raw)
            # Distinct sessions must never collapse onto one lake path. A real vulcan id
            # is unique per session; for a degraded session lacking one, key on a content
            # fingerprint so two different id-less payloads stay distinct (a true duplicate
            # still de-dupes) — never the single literal bucket that silently drops data.
            session_key = (
                row.get("session_key")
                or row.get("session_id")
                or f"nokey-{stable_fingerprint(raw)}"
            )
            target_dir = session_lake_dir(
                root,
                game=row.get("game_id"),
                car=row.get("car_id"),
                track=row.get("track_id"),
                session_key=session_key,
            )
            path = endpoint_file(target_dir, RAW_SESSION_ENDPOINT)
            # Raw retention is write-once (never overwrite) + lossless (allow_nan keeps
            # non-finite telemetry floats).
            result = write_immutable_json(path, dict(raw), allow_nan=True)
        except (OSError, ValueError, TypeError, TTExportError):
            # One malformed session must never abort the whole batch or the indexes.
            failed += 1
            continue
        processed += 1
        if result.written:
            retained_new += 1

    indexed = reindex_lake(root, generated_at=stamp)
    return ExportSummary(
        total=processed,
        retained_new=retained_new,
        skipped_existing=processed - retained_new,
        failed=failed,
        lake_root=root,
        indexed=indexed,
    )


@dataclass(frozen=True)
class CoachingSummary:
    """Outcome of retaining one session's coaching bundle (M-TT1)."""

    session_key: str
    segments: int
    actionable: int
    written: list[str]
    lake_root: Path
    indexed: int = 0

    def render(self) -> str:
        return (
            f"retained coaching for session {self.session_key} "
            f"({self.segments} segment(s), {self.actionable} actionable) to {self.lake_root} "
            f"[{', '.join(self.written) or 'nothing new'}; {self.indexed} file(s) indexed]"
        )


@dataclass(frozen=True)
class ReferenceArchiveSummary:
    """Outcome of building one M-TT2 Track Titan reference archive."""

    output: Path
    samples: int
    coverage: float
    partial: bool
    payload_count: int

    def render(self) -> str:
        state = "PARTIAL debug" if self.partial else "full"
        return (
            f"wrote {state} TT reference archive to {self.output} "
            f"({self.samples} samples, coverage={self.coverage:.3f}, "
            f"{self.payload_count} payload(s))"
        )


@dataclass(frozen=True)
class CurriculumSummary:
    """Outcome of building one M-TT3 Track Titan harness curriculum."""

    output: Path
    objectives: int
    total_time_loss_s: float
    source: Path

    def render(self) -> str:
        return (
            f"wrote TT harness curriculum to {self.output} "
            f"({self.objectives} objective(s), "
            f"total_loss={self.total_time_loss_s:.3f}s, source={self.source.name})"
        )


def _car_segment(session: Mapping[str, Any]) -> Any:
    """Resolve a STRING car id for the lake path.

    The last-session ``session`` stores ``car`` as a string id; other surfaces may carry a
    string ``car_id`` or a ``car`` object. Prefer a string id and unwrap an object so the
    lake path is ``…/{car_id}/…``, never a dict-repr (#353 review).
    """
    for value in (session.get("car_id"), session.get("car")):
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Mapping):
            inner = value.get("car_id") or value.get("id")
            if isinstance(inner, str) and inner:
                return inner
    return None


def _session_lake_key(session: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the (game, car, track, session_key) lake key for a services session.

    The session key is the second half of the ``{uid}#{sessionKey}`` id (services has no
    standalone field). The car id is resolved to a string via :func:`_car_segment`.
    """
    raw_id = session.get("session_id") or session.get("id") or ""
    _, session_key = split_session_id(raw_id)
    return {
        "game": session.get("game_id"),
        "car": _car_segment(session),
        "track": session.get("track_id"),
        "session_key": session_key or f"nokey-{stable_fingerprint(dict(session))}",
    }


def _count_actionable(bundle: Mapping[str, Any]) -> int:
    """Count corner stories carrying a real (>0) time loss across the bundle."""
    total = 0
    for seg in bundle.get("segments", []) or []:
        for story in seg.get("stories", []) or []:
            loss = story.get("time_loss")
            if isinstance(loss, (int, float)) and loss > 0:
                total += 1
    return total


def retain_coaching(
    session: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    lap: Any,
    last_session_payload: Mapping[str, Any] | None = None,
    lake_base: Path | None = None,
    generated_at: str | None = None,
) -> CoachingSummary:
    """Immutably retain a session's last-session payload + per-lap coaching bundle, then reindex.

    Pure of network: given already-fetched payloads, writes ``last_session_lap{lap}.json`` and
    ``coaching_lap{lap}.json`` **write-once** under ``journal/tt/{game}/{car}/{track}/{sk}/``
    keyed by the given ``session``. BOTH files are **per-lap**: the /last-session telemetry is
    lap-specific, so lap-keying it keeps each lap's raw evidence coherent with its coaching even
    when the same session later gains another lap (#353 review). Distinct later captures for the
    same lap are retained as ``last_session_lap{lap}_window_{fingerprint}.json`` so M-TT2 lake
    discovery can stitch multiple segment windows without overwriting the first capture.
    ``last_session_payload`` is the FULL raw services response (session + referenceLap + telemetry)
    — preserved so the lake reconstructs exactly what the endpoint returned (the M-TT2
    reference-lap input); it defaults to ``session`` when not supplied.
    After writing, the lake indexes are rebuilt from disk (:func:`reindex_lake`) so the new
    services endpoints are discoverable and integrity-checkable. ``allow_nan`` keeps
    non-finite telemetry floats lossless, matching raw session retention.
    """
    root = lake_root(lake_base)
    stamp = generated_at or _iso_now()
    key = _session_lake_key(session)
    target_dir = session_lake_dir(
        root, game=key["game"], car=key["car"], track=key["track"], session_key=key["session_key"]
    )
    last_payload = dict(last_session_payload) if last_session_payload is not None else dict(session)
    written: list[str] = []
    base_last_endpoint = last_session_endpoint(lap)
    last_result = write_immutable_json(
        endpoint_file(target_dir, base_last_endpoint), last_payload, allow_nan=True
    )
    if last_result.written:
        written.append(base_last_endpoint)
    elif last_result.sha256[:12] != stable_fingerprint(last_payload):
        window_endpoint = last_session_window_endpoint(lap, last_payload)
        window_result = write_immutable_json(
            endpoint_file(target_dir, window_endpoint), last_payload, allow_nan=True
        )
        if window_result.written:
            written.append(window_endpoint)

    coaching_name = coaching_endpoint(lap)
    coaching_result = write_immutable_json(
        endpoint_file(target_dir, coaching_name), dict(bundle), allow_nan=True
    )
    if coaching_result.written:
        written.append(coaching_name)
    indexed = reindex_lake(root, generated_at=stamp)
    return CoachingSummary(
        session_key=key["session_key"],
        segments=len(bundle.get("segments", []) or []),
        actionable=_count_actionable(bundle),
        written=written,
        lake_root=root,
        indexed=indexed,
    )


def _load_json_file(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise TTNormalizeError(f"could not read {path}: {exc}") from exc
    except ValueError as exc:
        raise TTNormalizeError(f"{path} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TTNormalizeError(f"{path} did not contain a JSON object")
    return payload


def _lap_from_coaching_path(path: Path) -> str | None:
    stem = path.stem
    if not stem.startswith(COACHING_ENDPOINT_PREFIX):
        return None
    lap = stem[len(COACHING_ENDPOINT_PREFIX) :]
    return lap or None


def _paired_last_session_path(coaching_path: Path) -> Path | None:
    lap = _lap_from_coaching_path(coaching_path)
    if not lap:
        return None
    candidates: list[Path] = []
    base = coaching_path.with_name(f"{last_session_endpoint(lap)}.json")
    if base.exists() and base.is_file() and not base.is_symlink():
        candidates.append(base)
    candidates.extend(
        path
        for path in coaching_path.parent.glob(
            f"{last_session_endpoint(lap)}{LAST_SESSION_WINDOW_MARKER}*.json"
        )
        if path.is_file() and not path.is_symlink()
    )
    if not candidates:
        return None
    if len(candidates) > 1:
        rel = ", ".join(path.name for path in sorted(candidates))
        raise TTNormalizeError(
            f"multiple paired last-session payloads found for {coaching_path}: {rel}; "
            "pass --session explicitly"
        )
    return candidates[0]


def discover_reference_payloads(
    *,
    lake_base: Path | None = None,
    session_key: str | None = None,
    lap: str | int | None = None,
) -> list[Path]:
    """Discover retained ``last_session_lap*.json`` payloads in the TT lake."""
    if not session_key or lap is None:
        raise TTNormalizeError("--discover-lake requires both --session-key and --lap")
    root = lake_root(lake_base)
    if not root.exists():
        raise TTNormalizeError(f"Track Titan lake not found: {root}")
    paths: list[Path] = []
    for path in sorted(root.rglob(REFERENCE_INPUT_GLOB)):
        if path.is_symlink() or not path.is_file():
            continue
        if path.parent.name != str(session_key):
            continue
        if not _last_session_endpoint_matches_lap(path.stem, lap):
            continue
        paths.append(path)
    if not paths:
        details = []
        if session_key:
            details.append(f"session_key={session_key}")
        if lap is not None:
            details.append(f"lap={lap}")
        suffix = f" ({', '.join(details)})" if details else ""
        raise TTNormalizeError(f"no retained last-session payloads found under {root}{suffix}")
    return paths


def _discover_curriculum_coaching_path(
    *,
    lake_base: Path | None = None,
    session_key: str | None = None,
    lap: str | int | None = None,
) -> Path:
    """Discover the retained coaching bundle for one lake session/lap."""
    if not session_key or lap is None:
        raise TTNormalizeError("--discover-lake requires both --session-key and --lap")
    root = lake_root(lake_base)
    if not root.exists():
        raise TTNormalizeError(f"Track Titan lake not found: {root}")
    target_name = f"{coaching_endpoint(lap)}.json"
    session_leaf = sanitize_segment(session_key, fallback="unknown_session")
    matches: list[Path] = []
    for path in sorted(root.glob(f"*/*/*/{session_leaf}/{target_name}")):
        if path.is_symlink() or not path.is_file():
            continue
        matches.append(path)
    if not matches:
        raise TTNormalizeError(
            f"no retained coaching payload found under {root} "
            f"(session_key={session_key}, lap={lap})"
        )
    if len(matches) > 1:
        rel = ", ".join(str(p.relative_to(root)) for p in matches[:5])
        raise TTNormalizeError(
            f"multiple retained coaching payloads matched session_key={session_key}, "
            f"lap={lap}: {rel}"
        )
    return matches[0]


def discover_curriculum_payloads(
    *,
    lake_base: Path | None = None,
    session_key: str | None = None,
    lap: str | int | None = None,
) -> tuple[Path, Path]:
    """Discover the retained coaching bundle and paired last-session payload for M-TT3."""
    coaching_path = _discover_curriculum_coaching_path(
        lake_base=lake_base, session_key=session_key, lap=lap
    )
    session_path = _paired_last_session_path(coaching_path)
    if session_path is None:
        raise TTNormalizeError(
            f"no paired last-session payload found for {coaching_path} (pass --session)"
        )
    return coaching_path, session_path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _tt_lake_roots_for_output(*, coaching_path: Path) -> tuple[Path, ...]:
    roots = {Path.cwd().resolve() / "journal" / "tt"}
    resolved_coaching = coaching_path.resolve()
    for parent in resolved_coaching.parents:
        if parent.name == "tt" and parent.parent.name == "journal":
            roots.add(parent)
    return tuple(sorted(roots, key=str))


def _resolve_curriculum_output_path(
    output: Path, *, coaching_path: Path, output_base: Path | None = None
) -> Path:
    raw = output
    base_dir = Path.cwd().resolve()
    resolved = output.resolve() if output.is_absolute() else (base_dir / output).resolve()
    coaching_dir = coaching_path.resolve().parent
    tt_lake_roots = set(_tt_lake_roots_for_output(coaching_path=coaching_path))
    if output_base is not None:
        tt_lake_roots.add(Path(output_base).resolve() / "journal" / "tt")
    tt_lake_roots = tuple(sorted(tt_lake_roots, key=str))
    approved_roots = [
        base_dir / ".scratch",
        coaching_dir,
        *tt_lake_roots,
    ]
    if not any(_is_relative_to(resolved, root.resolve()) for root in approved_roots):
        roots = ".scratch/, journal/tt/, or the retained input directory"
        raise TTNormalizeError(f"{raw}: curriculum output must stay under {roots}")
    resolved_coaching = coaching_path.resolve()
    expected_lap = _lap_from_coaching_path(coaching_path)
    for tt_root in tt_lake_roots:
        resolved_tt_root = tt_root.resolve()
        output_in_tt_root = _is_relative_to(resolved, resolved_tt_root)
        if output_in_tt_root and not resolved.match(CURRICULUM_ENDPOINT_GLOB):
            raise TTNormalizeError(
                f"{raw}: curriculum outputs inside {tt_root} must be named "
                f"{CURRICULUM_ENDPOINT_GLOB}"
            )
        if (
            expected_lap is not None
            and output_in_tt_root
            and resolved.name != f"{curriculum_endpoint(expected_lap)}.json"
        ):
            raise TTNormalizeError(f"{raw}: curriculum output lap must match {coaching_path.name}")
        if (
            output_in_tt_root
            and _is_relative_to(resolved_coaching, resolved_tt_root)
            and resolved.parent != resolved_coaching.parent
        ):
            raise TTNormalizeError(
                f"{raw}: curriculum output inside {tt_root} must stay next to {coaching_path.name}"
            )
    return resolved


def _services_session_for_validation(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data") if "success" in payload else payload
    if not isinstance(data, Mapping):
        return {}
    session = data.get("session")
    return session if isinstance(session, Mapping) else data


def _lake_session_key_for_path(path: Path) -> str | None:
    for parent in path.resolve().parents:
        if parent.name == "tt" and parent.parent.name == "journal":
            try:
                return path.parent.relative_to(parent).parts[-1]
            except (IndexError, ValueError):
                return None
    return None


def _validate_curriculum_session_pair(
    coaching_path: Path, *, session_payload: Mapping[str, Any]
) -> None:
    expected_lap = _lap_from_coaching_path(coaching_path)
    session = _services_session_for_validation(session_payload)
    if expected_lap is not None:
        actual_lap = session.get("lap_number")
        if actual_lap is None:
            raise TTNormalizeError(
                f"{coaching_path.name}: paired last-session payload missing lap_number"
            )
        if str(actual_lap) != str(expected_lap):
            raise TTNormalizeError(
                f"paired last-session lap {actual_lap} does not match {coaching_path.name}"
            )

    expected_session_key = _lake_session_key_for_path(coaching_path)
    if expected_session_key:
        raw_id = session.get("id") or session.get("session_id") or ""
        _, actual_session_key = split_session_id(str(raw_id))
        actual_session_key = actual_session_key or session.get("session_key")
        if not actual_session_key:
            raise TTNormalizeError(
                f"{coaching_path.name}: paired last-session payload missing session key"
            )
        if str(actual_session_key) != expected_session_key:
            raise TTNormalizeError(
                "paired last-session session key "
                f"{actual_session_key} does not match retained coaching session "
                f"{expected_session_key}"
            )


def build_reference_archive_from_files(
    paths: Sequence[Path],
    *,
    output: Path,
    channel: str = "reference",
    allow_partial: bool = False,
    coverage_threshold: float = DEFAULT_REFERENCE_COVERAGE_THRESHOLD,
    max_spline_gap: float = DEFAULT_REFERENCE_MAX_SPLINE_GAP,
    track_length_m: float,
    overwrite: bool = False,
    pretty: bool = False,
) -> ReferenceArchiveSummary:
    """Build and write a TT reference archive from retained payload files."""
    resolved_output = output.resolve()
    for path in paths:
        if resolved_output == path.resolve():
            raise TTNormalizeError(f"output must not overwrite retained input: {output}")
    if output.exists() and not overwrite:
        raise TTNormalizeError(f"output already exists (pass --overwrite): {output}")
    payloads = [_load_json_file(path) for path in paths]
    archive = build_reference_archive(
        list(payloads),
        channel=channel,
        coverage_threshold=coverage_threshold,
        max_spline_gap=max_spline_gap,
        allow_partial=allow_partial,
        track_length_m=track_length_m,
    )
    if pretty:
        text = json.dumps(archive, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(archive, separators=(",", ":"), sort_keys=True) + "\n"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise TTNormalizeError(f"could not write {output}: {exc}") from exc
    meta = archive["generator"]["tt_reference"]
    return ReferenceArchiveSummary(
        output=output,
        samples=int(meta["samples"]),
        coverage=float(meta["coverage"]),
        partial=bool(meta["partial"]),
        payload_count=int(meta["payload_count"]),
    )


def build_curriculum_from_files(
    coaching_path: Path,
    *,
    output: Path,
    session_path: Path | None = None,
    output_base: Path | None = None,
    generated_at: str | None = None,
    min_time_loss_s: float = DEFAULT_CURRICULUM_MIN_TIME_LOSS_S,
    overwrite: bool = False,
    pretty: bool = False,
) -> CurriculumSummary:
    """Build and write a TT harness curriculum from retained coaching evidence."""
    resolved_output = _resolve_curriculum_output_path(
        output, coaching_path=coaching_path, output_base=output_base
    )
    inputs = [coaching_path]
    paired_session_path = session_path or _paired_last_session_path(coaching_path)
    if paired_session_path is None:
        raise TTNormalizeError(
            f"no paired last-session payload found for {coaching_path} (pass --session)"
        )
    inputs.append(paired_session_path)
    for path in inputs:
        if resolved_output == path.resolve():
            raise TTNormalizeError(f"output must not overwrite retained input: {output}")
    if resolved_output.exists() and not overwrite:
        raise TTNormalizeError(f"output already exists (pass --overwrite): {output}")
    coaching = _load_json_file(coaching_path)
    session_payload = _load_json_file(paired_session_path)
    _validate_curriculum_session_pair(coaching_path, session_payload=session_payload)
    stamp = generated_at or _iso_now()
    curriculum = build_harness_curriculum(
        coaching,
        session_payload=session_payload,
        exported_at=stamp,
        min_time_loss_s=min_time_loss_s,
    )
    if pretty:
        text = json.dumps(curriculum, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(curriculum, separators=(",", ":"), sort_keys=True) + "\n"
    try:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise TTNormalizeError(f"could not write {output}: {exc}") from exc
    summary = curriculum["summary"]
    return CurriculumSummary(
        output=resolved_output,
        objectives=int(summary["objectives"]),
        total_time_loss_s=float(summary["total_time_loss_s"]),
        source=coaching_path,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``tools.tt_ingest`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.tt_ingest",
        description="Retain + index Track Titan post-race session data (issue #353).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser(
        "auth-check",
        help="Resolve the refresh token and mint access/id tokens (prints no secrets).",
    )
    auth.add_argument("--leveldb-dir", type=Path, default=None)

    export = sub.add_parser(
        "export", help="Paginate the sessions list and retain it immutably to the lake."
    )
    export.add_argument("--uid", default=None, help="User id; defaults to the token 'sub'.")
    export.add_argument("--limit", type=int, default=50, help="Page size (default 50).")
    export.add_argument(
        "--max-pages", type=int, default=None, help="Cap pages fetched (default: all)."
    )
    export.add_argument(
        "--lake-base",
        type=Path,
        default=None,
        help="Base dir for the journal/tt lake (default: cwd).",
    )
    export.add_argument("--leveldb-dir", type=Path, default=None)
    export.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch page 1 and print a sanitized summary; write nothing.",
    )

    coaching = sub.add_parser(
        "coaching",
        help="Fetch + retain per-corner reference & advice for the last session (services, M-TT1).",
    )
    coaching.add_argument("--uid", default=None, help="User id; defaults to the token 'sub'.")
    coaching.add_argument(
        "--segment-count", type=int, default=7, help="Corners (segments) to pull (default 7)."
    )
    coaching.add_argument("--lake-base", type=Path, default=None)
    coaching.add_argument("--leveldb-dir", type=Path, default=None)
    coaching.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved session + a sanitized advice summary; write nothing.",
    )

    reference = sub.add_parser(
        "reference",
        help="Build an M-TT2 lap_archive reference from retained TT last-session telemetry.",
    )
    reference.add_argument(
        "--input",
        action="append",
        type=Path,
        default=[],
        help="Retained last_session_lap*.json payload; repeat to stitch multiple windows.",
    )
    reference.add_argument(
        "--discover-lake",
        action="store_true",
        help=(
            "Discover retained last_session_lap*.json files for --session-key/--lap under "
            "--lake-base/journal/tt."
        ),
    )
    reference.add_argument("--lake-base", type=Path, default=None)
    reference.add_argument(
        "--session-key", default=None, help="Required with --discover-lake; retained session key."
    )
    reference.add_argument("--lap", default=None, help="Required with --discover-lake; one lap.")
    reference.add_argument(
        "--channel",
        choices=("reference", "user"),
        default="reference",
        help="TT telemetry channel to normalize (default: reference).",
    )
    reference.add_argument(
        "--output", type=Path, required=True, help="Reference archive JSON path."
    )
    reference.add_argument(
        "--track-length-m",
        type=float,
        default=4500.0,
        help="Track length for the archive metadata when TT does not provide one.",
    )
    reference.add_argument(
        "--min-coverage",
        type=float,
        default=DEFAULT_REFERENCE_COVERAGE_THRESHOLD,
        help="Required contiguous spline coverage for a full reference (default 0.90).",
    )
    reference.add_argument(
        "--max-spline-gap",
        type=float,
        default=DEFAULT_REFERENCE_MAX_SPLINE_GAP,
        help="Largest spline gap counted as contiguous coverage (default 0.08).",
    )
    reference.add_argument(
        "--allow-partial",
        action="store_true",
        help="Emit a debug-only archive even when full-lap coverage is not met.",
    )
    reference.add_argument("--overwrite", action="store_true")
    reference.add_argument("--pretty", action="store_true")

    curriculum = sub.add_parser(
        "curriculum",
        help=("Build an M-TT3 harness curriculum from retained TT coaching_lap*.json advice."),
    )
    curriculum.add_argument(
        "--coaching",
        type=Path,
        default=None,
        help="Retained coaching_lap*.json bundle to normalize.",
    )
    curriculum.add_argument(
        "--session",
        type=Path,
        default=None,
        help=(
            "Optional paired last_session_lap*.json payload; defaults to the sibling "
            "last_session file when present."
        ),
    )
    curriculum.add_argument(
        "--discover-lake",
        action="store_true",
        help="Discover coaching_lap*.json for --session-key/--lap under --lake-base/journal/tt.",
    )
    curriculum.add_argument("--lake-base", type=Path, default=None)
    curriculum.add_argument(
        "--session-key", default=None, help="Required with --discover-lake; retained session key."
    )
    curriculum.add_argument("--lap", default=None, help="Required with --discover-lake; one lap.")
    curriculum.add_argument(
        "--min-time-loss-s",
        type=float,
        default=DEFAULT_CURRICULUM_MIN_TIME_LOSS_S,
        help="Only emit objectives whose TT time loss is above this threshold (default 0).",
    )
    curriculum.add_argument("--output", type=Path, required=True)
    curriculum.add_argument("--overwrite", action="store_true")
    curriculum.add_argument("--pretty", action="store_true")
    return parser


def _print(message: str) -> None:  # pragma: no cover - thin stdout shim
    print(message)


def cmd_auth_check(args: argparse.Namespace) -> int:  # pragma: no cover - network
    config = TTConfig.from_env()
    refresh = resolve_refresh_token(config, leveldb_dir=args.leveldb_dir)
    minted = mint_tokens(refresh, config)
    uid = uid_from_token(minted.access_token)
    expiry = token_expiry(minted.access_token)
    expired = is_token_expired(minted.access_token)
    _print(f"auth-check OK — uid={uid}")
    _print(f"  access token expires: {expiry.isoformat() if expiry else '?'} (expired={expired})")
    return 0


def cmd_export(args: argparse.Namespace) -> int:  # pragma: no cover - network
    config = TTConfig.from_env()
    refresh = resolve_refresh_token(config, leveldb_dir=args.leveldb_dir)
    minted = mint_tokens(refresh, config)
    uid = args.uid or uid_from_token(minted.access_token)

    if args.dry_run:
        from tools.tt_ingest.tt_vulcan import fetch_sessions_page

        page = fetch_sessions_page(minted.access_token, uid, limit=args.limit, page=1)
        _print(f"dry-run — uid={uid}, count={page.count}, page size={page.limit}")
        for session in page.sessions[:10]:
            _print(f"  {session_summary(session)}")
        return 0

    sessions = list(
        iter_all_sessions(minted.access_token, uid, limit=args.limit, max_pages=args.max_pages)
    )
    summary = retain_sessions(sessions, lake_base=args.lake_base)
    _print(summary.render())
    return 0


def cmd_coaching(args: argparse.Namespace) -> int:  # pragma: no cover - network
    config = TTConfig.from_env()
    refresh = resolve_refresh_token(config, leveldb_dir=args.leveldb_dir)
    minted = mint_tokens(refresh, config)
    uid = args.uid or uid_from_token(minted.access_token)

    # M-TT1 scope: coach the LAST session's own lap. The /last-session endpoint returns the
    # full raw payload (session + referenceLap + telemetry) for exactly that lap, so the
    # retained last_session.json is COHERENT lap-specific evidence next to coaching_lap{N}.json.
    # Coaching an arbitrary lap (or older session) needs per-lap telemetry endpoints not in
    # M-TT1 scope — see the M-TT2+ follow-up — so it is intentionally not offered here (a
    # mismatched lap would pair lap-N coaching with the wrong lap's raw evidence).
    raw_last = fetch_last_session_raw(minted.access_token, uid)
    session = parse_last_session(raw_last)["session"]
    key = _session_lake_key(session)
    session_key = key["session_key"]
    lap = session.get("lap_number")
    if not session_key or lap is None:
        _print("coaching: could not resolve the last session's key/lap (no recent session?)")
        return 1

    bundle = fetch_session_coaching(
        minted.access_token, uid, session_key, lap, segment_count=args.segment_count
    )

    if args.dry_run:
        _print(f"dry-run — uid={uid}, session={session_key}, lap={lap}")
        _print(f"  dynamic reference: {bundle['reference_lap'].get('username', '?')}")
        for seg in bundle["segments"]:
            stories = seg.get("stories", [])
            head = stories[0]["diagnosis"] if stories else "(no advice)"
            _print(f"  corner {seg['segment']}: {head}")
        return 0

    summary = retain_coaching(
        session, bundle, lap=lap, last_session_payload=raw_last, lake_base=args.lake_base
    )
    _print(summary.render())
    return 0


def cmd_reference(args: argparse.Namespace) -> int:
    explicit_inputs = list(args.input or [])
    if bool(explicit_inputs) == bool(args.discover_lake):
        raise TTNormalizeError("reference requires exactly one of --input or --discover-lake")
    paths = (
        explicit_inputs
        if explicit_inputs
        else discover_reference_payloads(
            lake_base=args.lake_base, session_key=args.session_key, lap=args.lap
        )
    )
    summary = build_reference_archive_from_files(
        paths,
        output=args.output,
        channel=args.channel,
        allow_partial=args.allow_partial,
        coverage_threshold=args.min_coverage,
        max_spline_gap=args.max_spline_gap,
        track_length_m=args.track_length_m,
        overwrite=args.overwrite,
        pretty=args.pretty,
    )
    _print(summary.render())
    return 0


def cmd_curriculum(args: argparse.Namespace) -> int:
    if bool(args.coaching) == bool(args.discover_lake):
        raise TTNormalizeError("curriculum requires exactly one of --coaching or --discover-lake")
    if args.coaching:
        coaching_path = args.coaching
        session_path = args.session
    else:
        if args.session:
            coaching_path = _discover_curriculum_coaching_path(
                lake_base=args.lake_base, session_key=args.session_key, lap=args.lap
            )
            session_path = args.session
        else:
            coaching_path, session_path = discover_curriculum_payloads(
                lake_base=args.lake_base, session_key=args.session_key, lap=args.lap
            )
    summary = build_curriculum_from_files(
        coaching_path,
        output=args.output,
        session_path=session_path,
        output_base=args.lake_base,
        min_time_loss_s=args.min_time_loss_s,
        overwrite=args.overwrite,
        pretty=args.pretty,
    )
    _print(summary.render())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "auth-check":
            return cmd_auth_check(args)
        if args.command == "export":
            return cmd_export(args)
        if args.command == "coaching":
            return cmd_coaching(args)
        if args.command == "reference":
            return cmd_reference(args)
        if args.command == "curriculum":
            return cmd_curriculum(args)
    except (
        TTAuthError,
        TTServicesError,
        TTNormalizeError,
    ) as exc:  # pragma: no cover - surfaced live
        parser.exit(2, f"tt_ingest: {exc}\n")
    parser.error(f"unknown command: {args.command}")  # pragma: no cover - argparse guards
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
