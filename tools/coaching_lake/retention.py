"""Retention planner for AC Copilot journal data (issue #402).

The raw lap and Track Titan lakes are immutable evidence until an explicit lifecycle
policy prunes them. This module makes that pruning deterministic and auditable:
planning is pure, dry-run is the CLI default, and deletion preserves PB, imported
reference, sidecar-pinned, and profile-ledger PB files.

It also preserves any archive **another persisted file still cites** (#627). Every other
protection here is record-local — it reads the archive and decides from that archive's own
contents — so none of them can see that a session report or the setup-experiment store still
points at it. See :func:`_cited_archive_names`.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.ai_sidecar.driver_profile import DEFAULT_PROFILE_PATH, load_profile
from tools.lap_archive_export import LapArchiveExportError, iter_lap_archive_paths, load_lap_archive
from tools.tt_ingest.tt_export import COACHING_ENDPOINT_PREFIX, CURRICULUM_ENDPOINT_PREFIX

DERIVED_TT_INDEXES = frozenset({"index.json", "sessions_index.json"})
DERIVED_TT_PATTERNS = (f"{CURRICULUM_ENDPOINT_PREFIX}*.json",)


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention caps. ``None`` means that dimension is disabled."""

    max_lap_files: int | None = None
    max_lap_age_days: int | None = None
    max_tt_files: int | None = None
    max_tt_age_days: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_lap_files",
            "max_lap_age_days",
            "max_tt_files",
            "max_tt_age_days",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class RetentionItem:
    """One file considered by the retention planner."""

    path: Path
    domain: str
    protected: bool
    reasons: tuple[str, ...]
    sort_time: datetime
    bytes: int = 0


@dataclass(frozen=True)
class RetentionPlan:
    """Deterministic retention outcome."""

    policy: RetentionPolicy
    items: tuple[RetentionItem, ...] = field(default_factory=tuple)
    delete: tuple[RetentionItem, ...] = field(default_factory=tuple)
    #: State files the citation scan could not read. Non-empty means every archive was protected
    #: regardless of policy, so it MUST be rendered — otherwise the operator sees a plan with zero
    #: candidates and no way to tell a satisfied policy from a parked one.
    unreadable_state: tuple[str, ...] = ()

    @property
    def protected(self) -> tuple[RetentionItem, ...]:
        return tuple(item for item in self.items if item.protected)

    def render(self) -> str:
        lines = [
            f"retention plan: {len(self.delete)} delete candidate(s), "
            f"{len(self.protected)} protected, {len(self.items)} scanned"
        ]
        if self.unreadable_state:
            lines.append(
                "  RETENTION PARKED: a state file could not be read, so no archive can be shown "
                "to be uncited. Every archive is protected until this is resolved:"
            )
            for entry in self.unreadable_state[:10]:
                lines.append(f"    {entry}")
            if len(self.unreadable_state) > 10:
                lines.append(f"    ... {len(self.unreadable_state) - 10} more")
        for item in self.delete[:20]:
            lines.append(f"  DELETE {item.domain} {item.path} ({', '.join(item.reasons)})")
        if len(self.delete) > 20:
            lines.append(f"  ... {len(self.delete) - 20} more")
        return "\n".join(lines)


@dataclass(frozen=True)
class RetentionApplyResult:
    """Summary of files removed by ``apply_retention``."""

    deleted: int
    bytes_deleted: int
    invalidated_indexes: int = 0
    failures: tuple[str, ...] = ()

    def render(self) -> str:
        text = f"retention applied: deleted={self.deleted}, bytes={self.bytes_deleted}"
        if self.invalidated_indexes:
            text += f", invalidated_indexes={self.invalidated_indexes}"
        if self.failures:
            text += f", failures={len(self.failures)}"
        return text


def _parse_time(raw: Any, fallback: datetime) -> datetime:
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return fallback


def _mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return datetime.fromtimestamp(0, tz=UTC)


def _has_pin_marker(path: Path) -> bool:
    markers = (
        path.with_suffix(path.suffix + ".pin"),
        path.with_suffix(path.suffix + ".keep"),
        path.with_suffix(".pin"),
        path.with_suffix(".keep"),
    )
    return any(marker.exists() for marker in markers)


def _profile_pb_lap_uuids(profile: Mapping[str, Any] | None) -> set[str]:
    out: set[str] = set()
    if not isinstance(profile, Mapping):
        return out
    for row in (profile.get("personal_bests") or {}).values():
        if isinstance(row, Mapping) and isinstance(row.get("lap_uuid"), str):
            out.add(row["lap_uuid"])
    return out


def _is_reference_archive(record: Mapping[str, Any]) -> bool:
    return (
        record.get("source") == "imported"
        or isinstance(record.get("import_format"), str)
        or isinstance(record.get("generator"), Mapping)
    )


#: An archive filename as it appears inside a state file. The ``.json`` suffix is required so it
#: cannot match unrelated keys like ``lap_history`` or ``lap_ms``, which appear in every session
#: file. Case-insensitive to match the filesystem this runs on.
_ARCHIVE_CITATION = re.compile(rb"lap_[0-9A-Za-z._-]+\.json", re.IGNORECASE)

#: Persisted stores that can cite an archive. ``.jsonl`` matters: the setup-experiment store
#: (``journal/setup_experiments/experiments.jsonl``) records an ``archive_path`` per row.
_STATE_SUFFIXES = ("*.json", "*.jsonl")


def _cited_archive_names(lap_dir: Path) -> tuple[set[str], list[str]]:
    """Archive names cited by any persisted state file, plus any file that could not be read.

    A record-local check (:func:`_is_reference_archive`) cannot see that some *other* file still
    points at an archive. Measured on the rig: ``journal/reports/*.json`` cites **187** archives,
    125 of which this planner otherwise classified ``eligible`` — deleting them would have
    silently orphaned the operator's own session reports.

    Returns ``(names, unreadable)``. **The second element is a veto, not diagnostics.** An empty
    citation set is what makes an archive eligible, so a state file we failed to read is
    indistinguishable from one that cites nothing; AC holding it open, a dehydrated OneDrive
    placeholder, or an antivirus lock would otherwise read as consent to delete. Callers must
    protect everything while it is non-empty — the same fail-closed posture this module already
    takes for an unreadable archive.

    The ``journal/laps`` tree is excluded: archives must not keep each other alive, and reading
    them here would duplicate the decode cost that made this subsystem slow (#627).
    """
    names: set[str] = set()
    unreadable: list[str] = []
    # Only derive a state root from a directory that IS `<state>/journal/laps`. A bare
    # `--lap-dir /data/laps` would otherwise take `parent.parent` to the volume root and recursively
    # glob the entire filesystem — slow, and any unrelated unreadable JSON anywhere on the machine
    # would trip the fail-closed veto and protect everything. A caller-supplied directory with no
    # surrounding state simply has no citations, which is not an error.
    parts = lap_dir.parts
    if len(parts) < 3 or tuple(part.lower() for part in parts[-2:]) != ("journal", "laps"):
        return names, unreadable
    state_dir = lap_dir.parent.parent
    if not state_dir.is_dir():
        return names, unreadable
    for pattern in _STATE_SUFFIXES:
        for candidate in sorted(state_dir.rglob(pattern)):
            try:
                relative = candidate.relative_to(state_dir).parts
            except ValueError:  # pragma: no cover - rglob results are always relative
                continue
            if relative[:2] == ("journal", "laps"):
                continue
            try:
                raw = candidate.read_bytes()
            except OSError as exc:
                unreadable.append(f"{'/'.join(relative)}: {exc}")
                continue
            for match in _ARCHIVE_CITATION.finditer(raw):
                names.add(match.group(0).decode("ascii").lower())
    return names, unreadable


def _lap_items(
    lap_dir: Path, profile: Mapping[str, Any] | None
) -> tuple[list[RetentionItem], list[str]]:
    """Returns ``(items, unreadable_state)``; the veto list is surfaced in the rendered plan."""
    pb_lap_uuids = _profile_pb_lap_uuids(profile)
    cited, unreadable_state = _cited_archive_names(lap_dir)
    items: list[RetentionItem] = []
    for path in iter_lap_archive_paths([lap_dir]):
        reasons: list[str] = []
        protected = False
        fallback_time = _mtime(path)
        sort_time = fallback_time
        try:
            record = load_lap_archive(path)
        except (LapArchiveExportError, OSError, ValueError):
            record = {}
            protected = True
            reasons.append("unreadable")
        if record:
            sort_time = _parse_time(record.get("exported_at"), fallback_time)
            lap = record.get("lap") if isinstance(record.get("lap"), Mapping) else {}
            if lap.get("is_pb") is True:
                protected = True
                reasons.append("lap-pb")
            if record.get("lap_uuid") in pb_lap_uuids:
                protected = True
                reasons.append("profile-pb")
            if _is_reference_archive(record):
                protected = True
                reasons.append("reference")
        if _has_pin_marker(path):
            protected = True
            reasons.append("pinned")
        if path.name.lower() in cited:
            protected = True
            reasons.append("cited-by-state")
        if unreadable_state:
            # Fail closed: we could not read every file that might cite an archive, so we cannot
            # prove that any archive is uncited.
            protected = True
            reasons.append("state-scan-incomplete")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        items.append(
            RetentionItem(
                path=path,
                domain="laps",
                protected=protected,
                reasons=tuple(reasons) if reasons else ("eligible",),
                sort_time=sort_time,
                bytes=size,
            )
        )
    ordered = sorted(items, key=lambda item: (item.sort_time, item.path.as_posix()))
    return ordered, unreadable_state


def _tt_raw_paths(tt_dir: Path) -> Iterable[Path]:
    if not tt_dir.exists():
        return []
    return (
        path
        for path in sorted(tt_dir.rglob("*.json"))
        if path.is_file()
        and path.name not in DERIVED_TT_INDEXES
        and not any(path.match(pattern) for pattern in DERIVED_TT_PATTERNS)
    )


def _tt_items(tt_dir: Path) -> list[RetentionItem]:
    items: list[RetentionItem] = []
    for path in _tt_raw_paths(tt_dir):
        reasons: list[str] = []
        protected = False
        if _has_pin_marker(path):
            protected = True
            reasons.append("pinned")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        items.append(
            RetentionItem(
                path=path,
                domain="tt",
                protected=protected,
                reasons=tuple(reasons) if reasons else ("eligible",),
                sort_time=_mtime(path),
                bytes=size,
            )
        )
    return sorted(items, key=lambda item: (item.sort_time, item.path.as_posix()))


def _select_by_cap(
    items: Sequence[RetentionItem],
    *,
    max_files: int | None,
    max_age_days: int | None,
    now: datetime,
) -> list[RetentionItem]:
    eligible = [item for item in items if not item.protected]
    selected: dict[Path, RetentionItem] = {}
    if max_age_days is not None:
        cutoff = now - timedelta(days=max_age_days)
        for item in eligible:
            if item.sort_time < cutoff:
                selected[item.path] = RetentionItem(
                    path=item.path,
                    domain=item.domain,
                    protected=item.protected,
                    reasons=tuple(sorted(set(item.reasons + ("age-cap",)))),
                    sort_time=item.sort_time,
                    bytes=item.bytes,
                )
    if max_files is not None and max_files >= 0 and len(items) > max_files:
        needed = len(items) - max_files
        for item in eligible[:needed]:
            selected[item.path] = RetentionItem(
                path=item.path,
                domain=item.domain,
                protected=item.protected,
                reasons=tuple(sorted(set(item.reasons + ("count-cap",)))),
                sort_time=item.sort_time,
                bytes=item.bytes,
            )
    return sorted(selected.values(), key=lambda item: (item.sort_time, item.path.as_posix()))


def _tt_index_paths_for_deleted(items: Sequence[RetentionItem]) -> list[Path]:
    roots: set[Path] = set()
    for item in items:
        if item.domain != "tt":
            continue
        for parent in item.path.parents:
            if any((parent / name).exists() for name in DERIVED_TT_INDEXES):
                roots.add(parent)
                break
    return sorted(
        (root / name for root in roots for name in DERIVED_TT_INDEXES if (root / name).exists()),
        key=lambda path: path.as_posix(),
    )


def _curriculum_path_for_tt_source(path: Path) -> Path | None:
    stem = path.stem
    if not stem.startswith(COACHING_ENDPOINT_PREFIX):
        return None
    lap = stem[len(COACHING_ENDPOINT_PREFIX) :]
    if not lap:
        return None
    return path.with_name(f"{CURRICULUM_ENDPOINT_PREFIX}{lap}.json")


def _cascade_tt_items(items: Sequence[RetentionItem]) -> list[RetentionItem]:
    cascade: list[RetentionItem] = []
    seen: set[Path] = set()
    for item in items:
        curriculum_path = _curriculum_path_for_tt_source(item.path)
        if curriculum_path is None or curriculum_path in seen:
            continue
        seen.add(curriculum_path)
        if (
            curriculum_path.is_symlink()
            or not curriculum_path.is_file()
            or _has_pin_marker(curriculum_path)
        ):
            continue
        try:
            size = curriculum_path.stat().st_size
        except OSError:
            size = 0
        cascade.append(
            RetentionItem(
                path=curriculum_path,
                domain="tt",
                protected=False,
                reasons=("cascade-from-coaching",),
                sort_time=item.sort_time,
                bytes=size,
            )
        )
    return cascade


def plan_retention(
    *,
    lap_dir: str | Path | None = None,
    tt_dir: str | Path | None = None,
    policy: RetentionPolicy,
    profile_path: str | Path | None = DEFAULT_PROFILE_PATH,
    now: datetime | None = None,
) -> RetentionPlan:
    """Build a deterministic retention plan without deleting anything."""
    stamp = now or datetime.now(UTC)
    profile = load_profile(profile_path, strict=True) if profile_path is not None else None
    items: list[RetentionItem] = []
    delete: list[RetentionItem] = []
    unreadable_state: list[str] = []

    if lap_dir is not None:
        lap_items, unreadable_state = _lap_items(Path(lap_dir), profile)
        items.extend(lap_items)
        delete.extend(
            _select_by_cap(
                lap_items,
                max_files=policy.max_lap_files,
                max_age_days=policy.max_lap_age_days,
                now=stamp,
            )
        )

    if tt_dir is not None:
        tt_items = _tt_items(Path(tt_dir))
        tt_delete = _select_by_cap(
            tt_items,
            max_files=policy.max_tt_files,
            max_age_days=policy.max_tt_age_days,
            now=stamp,
        )
        tt_cascade = _cascade_tt_items(tt_delete)
        items.extend(tt_items)
        items.extend(tt_cascade)
        delete.extend(tt_delete)
        delete.extend(tt_cascade)

    return RetentionPlan(
        policy=policy,
        items=tuple(
            sorted(items, key=lambda item: (item.domain, item.sort_time, item.path.as_posix()))
        ),
        delete=tuple(
            sorted(delete, key=lambda item: (item.domain, item.sort_time, item.path.as_posix()))
        ),
        unreadable_state=tuple(unreadable_state),
    )


def apply_retention(plan: RetentionPlan) -> RetentionApplyResult:
    """Delete files selected by a plan. Pin/protection is decided only during planning."""
    deleted = 0
    bytes_deleted = 0
    deleted_tt_items: list[RetentionItem] = []
    failures: list[str] = []
    for item in plan.delete:
        try:
            item.path.unlink()
        except OSError as exc:
            failures.append(f"{item.path}: {exc}")
            continue
        deleted += 1
        bytes_deleted += item.bytes
        if item.domain == "tt":
            deleted_tt_items.append(item)
    invalidated_indexes = 0
    for index_path in _tt_index_paths_for_deleted(deleted_tt_items):
        try:
            index_path.unlink()
        except OSError as exc:
            failures.append(f"{index_path}: {exc}")
            continue
        invalidated_indexes += 1
    return RetentionApplyResult(
        deleted=deleted,
        bytes_deleted=bytes_deleted,
        invalidated_indexes=invalidated_indexes,
        failures=tuple(failures),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lap-dir", type=Path, default=None)
    parser.add_argument("--tt-dir", type=Path, default=None)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--max-lap-files", type=int, default=None)
    parser.add_argument("--max-lap-age-days", type=int, default=None)
    parser.add_argument("--max-tt-files", type=int, default=None)
    parser.add_argument("--max-tt-age-days", type=int, default=None)
    parser.add_argument(
        "--apply", action="store_true", help="delete planned files; default is dry-run"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.lap_dir is None and args.tt_dir is None:
        parser.error("pass --lap-dir and/or --tt-dir")
    try:
        policy = RetentionPolicy(
            max_lap_files=args.max_lap_files,
            max_lap_age_days=args.max_lap_age_days,
            max_tt_files=args.max_tt_files,
            max_tt_age_days=args.max_tt_age_days,
        )
        plan = plan_retention(
            lap_dir=args.lap_dir,
            tt_dir=args.tt_dir,
            policy=policy,
            profile_path=args.profile,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(plan.render())
    if args.apply:
        print(apply_retention(plan).render())
    else:
        print("dry-run only; pass --apply to delete planned files")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
