"""Bounded retention for the lap-archive journal (#627).

The journal grows without limit: one ~250 KB JSON per completed lap, forever. Measured on the rig
2026-07-30 it held **403 files / 480 MB**, and every one of them was re-read by the reference scan
until #730 gated that away. Unbounded growth is still a disk problem and still makes any future
whole-journal pass quadratic in "laps ever driven".

This prunes it, and it is **deliberately conservative** because these are the operator's own
telemetry files. Three independent protections, any one of which spares a file:

1. **Imported archives are never pruned.** They are user-supplied data that cannot be regenerated
   by driving. Detected without a full JSON decode (see :func:`archive_source`).
2. **Anything a persisted state file still references is never pruned** — that is the reference /
   best-lap wiring, and deleting it would silently break coaching.
3. **The newest ``--keep`` archives are never pruned**, regardless of anything else.

Default is a **dry run**: it reports and changes nothing. Deleting requires ``--apply``.

    python -m tools.journal_prune                     # report only
    python -m tools.journal_prune --keep 150          # report with a different retention
    python -m tools.journal_prune --apply             # actually delete

Exit codes: ``0`` nothing to do or report produced, ``0`` after a successful ``--apply``.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: Compact form our Lua JSON encoder emits, e.g. ``"source":"in_game"``.
_SOURCE_COMPACT = b'"source":"'
_SOURCE_IMPORTED_COMPACT = b'"source":"imported"'

#: Keep this many newest archives no matter what. Generous on purpose: a lap you drove ten minutes
#: ago is far more likely to matter than disk pressure.
DEFAULT_KEEP = 100


def archive_source(path: Path) -> str | None:
    """Return the archive's ``source`` without JSON-decoding it, or ``None`` if undetermined.

    Mirrors ``persistence.archiveMayBeImported``: a plain substring scan, because decoding a
    250 KB float-heavy archive just to read one string is what made this subsystem slow in the
    first place. ``None`` means "could not tell" and callers MUST treat it as protected.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw.find(_SOURCE_IMPORTED_COMPACT) >= 0:
        return "imported"
    i = raw.find(_SOURCE_COMPACT)
    if i >= 0:
        start = i + len(_SOURCE_COMPACT)
        end = raw.find(b'"', start)
        if end > start:
            return raw[start:end].decode("utf-8", "replace")
    return None


#: An archive filename as it appears inside a state file. Requires the ``.json`` suffix so it
#: cannot match unrelated keys like ``lap_history`` or ``lap_ms``.
_ARCHIVE_TOKEN = re.compile(rb"lap_[0-9A-Za-z._-]+\.json")


def referenced_names(state_dir: Path) -> set[str]:
    """Archive filenames mentioned by any persisted state file under ``state_dir``, recursively.

    **Recursive on purpose.** On the rig, ``journal/reports/*.json`` names 187 lap archives while
    the per-combo files at the top level name none — a top-level-only scan would have left every
    one of those unprotected. Anything that can name an archive can protect it.

    Token extraction rather than schema parsing, so a schema change cannot silently un-protect a
    referenced archive, and one pass over the bytes rather than a scan per archive. Over-matching
    is the safe direction: a spurious name protects a file that did not need protecting.

    The ``journal/laps`` tree is excluded — archives referencing each other must not keep each
    other alive, and reading them here would re-introduce the very cost this work removes.
    """
    names: set[str] = set()
    if not state_dir.is_dir():
        return names
    for candidate in state_dir.rglob("*.json"):
        try:
            relative = candidate.relative_to(state_dir).parts
        except ValueError:  # pragma: no cover - rglob results are always relative
            continue
        if relative[:2] == ("journal", "laps"):
            continue
        try:
            raw = candidate.read_bytes()
        except OSError:
            continue
        for match in _ARCHIVE_TOKEN.finditer(raw):
            names.add(match.group(0).decode("ascii"))
    return names


@dataclass(frozen=True)
class Plan:
    """What a prune would do. ``prune`` is empty on a no-op."""

    keep_newest: int
    total: int
    total_bytes: int
    prune: tuple[Path, ...]
    protected_imported: tuple[Path, ...]
    protected_referenced: tuple[Path, ...]
    #: Measured while the files still exist. It cannot be a property: the report is rendered AFTER
    #: `apply_plan` has unlinked them, and re-stat'ing a deleted file yields 0 — an `--apply` run
    #: would have cheerfully reported reclaiming 0.0 MB.
    reclaimed_bytes: int


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def build_plan(laps_dir: Path, state_dir: Path, *, keep: int = DEFAULT_KEEP) -> Plan:
    """Decide which archives may be removed. Pure w.r.t. the filesystem: it never deletes."""
    if keep < 0:
        raise ValueError("keep must be >= 0")
    archives = sorted(laps_dir.glob("lap_*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    total_bytes = sum(_size(p) for p in archives)
    newest = set(archives[len(archives) - keep :]) if keep else set()
    referenced = referenced_names(state_dir)

    prune: list[Path] = []
    imported: list[Path] = []
    ref_protected: list[Path] = []
    for path in archives:
        if path in newest:
            continue
        if path.name in referenced:
            ref_protected.append(path)
            continue
        # `None` (undetermined) is treated exactly like "imported": protected.
        if archive_source(path) != "in_game":
            imported.append(path)
            continue
        prune.append(path)
    return Plan(
        keep_newest=keep,
        total=len(archives),
        total_bytes=total_bytes,
        prune=tuple(prune),
        protected_imported=tuple(imported),
        protected_referenced=tuple(ref_protected),
        reclaimed_bytes=sum(_size(p) for p in prune),
    )


def apply_plan(plan: Plan) -> tuple[int, list[str]]:
    """Delete the planned archives. Returns ``(removed, errors)``; never raises on one bad file."""
    removed = 0
    errors: list[str] = []
    for path in plan.prune:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
    return removed, errors


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def render(plan: Plan, *, applied: bool) -> Iterable[str]:
    yield f"journal archives : {plan.total} ({_mb(plan.total_bytes)})"
    yield f"keep newest      : {plan.keep_newest}"
    yield f"protected (imported/undetermined): {len(plan.protected_imported)}"
    yield f"protected (referenced by state)  : {len(plan.protected_referenced)}"
    verb = "removed" if applied else "would remove"
    yield f"{verb}          : {len(plan.prune)} ({_mb(plan.reclaimed_bytes)})"
    if plan.prune and not applied:
        yield ""
        yield "oldest 5 that would go:"
        for path in plan.prune[:5]:
            yield f"  {path.name}  ({_mb(_size(path))})"
        yield ""
        yield "re-run with --apply to delete them"


def default_state_dir() -> Path:
    """The app's ScriptConfig root, honouring a OneDrive-redirected Documents folder."""
    home = Path.home()
    for base in (home / "Documents", home / "OneDrive" / "Documents"):
        candidate = (
            base
            / "Assetto Corsa"
            / "cfg"
            / "extension"
            / "state"
            / "lua"
            / "app"
            / "ac_copilot_trainer"
            / "ac_copilot_trainer"
        )
        if candidate.is_dir():
            return candidate
    return home / "Documents" / "Assetto Corsa"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=None, help="app ScriptConfig root")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="newest archives to keep")
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = parser.parse_args(argv)

    # Argument validation before environment inspection: a bad `--keep` is a bad `--keep`
    # whether or not a journal happens to exist.
    if args.keep < 0:
        print("--keep must be >= 0", file=sys.stderr)
        return 2
    state_dir = args.state_dir or default_state_dir()
    laps_dir = state_dir / "journal" / "laps"
    if not laps_dir.is_dir():
        print(f"no lap journal at {laps_dir}", file=sys.stderr)
        return 1

    plan = build_plan(laps_dir, state_dir, keep=args.keep)
    removed = 0
    errors: list[str] = []
    if args.apply and plan.prune:
        removed, errors = apply_plan(plan)
    for line in render(plan, applied=bool(args.apply)):
        print(line)
    for err in errors:
        print(f"  ERROR {err}", file=sys.stderr)
    if args.apply:
        print(f"deleted {removed} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
