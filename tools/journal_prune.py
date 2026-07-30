"""Selective retention for the lap-archive journal (#627).

The journal is **not** unbounded — `lap_archive.M.rotate` runs after every completed lap and
evicts oldest-first until the directory is under a size cap (default 500 MB). The rig's measured
"403 files / 486 MB" is that cap working as designed, not runaway growth.

What `rotate` cannot do is choose *well*. It sorts by filename and deletes until the number goes
down: no notion of which archives are still referenced, and — before #627 — no notion of which
were imported rather than driven. This tool is the deliberate, operator-driven counterpart: it
frees space by *what a file is*, not by how old its name looks, so an operator who wants headroom
does not have to spend it on archives that are still wired into their coaching.

It is **deliberately conservative** because these are the operator's own telemetry files. Three
independent protections, any one of which spares a file:

1. **Imported archives are never pruned.** They are user-supplied data that cannot be regenerated
   by driving. Detected without a full JSON decode (see :func:`archive_source`).
2. **Anything a persisted state file still references is never pruned** — that is the reference /
   best-lap wiring, and deleting it would silently break coaching.
3. **The newest ``--keep`` archives are never pruned**, regardless of anything else.

Default is a **dry run**: it reports and changes nothing. Deleting requires ``--apply``.

    python -m tools.journal_prune                     # report only
    python -m tools.journal_prune --keep 150          # report with a different retention
    python -m tools.journal_prune --apply             # actually delete

Exit codes: ``0`` report produced or prune fully applied, ``1`` no journal at the resolved path,
``2`` bad arguments, ``3`` ``--apply`` ran but at least one file could not be removed, ``4`` the
reference scan was incomplete so nothing was pruned.
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

    Same technique as ``persistence.archiveMayBeImported`` — a plain substring scan, because
    decoding a 250 KB float-heavy archive just to read one string is what made this subsystem slow
    in the first place — but **deliberately stricter**, not a mirror of it. The Lua side has a
    tolerant path for whitespace-spaced JSON because falling back there only costs it a decode.
    Here the fallback costs a deletion, so a spaced or otherwise unrecognised file yields ``None``.

    ``None`` means "could not tell" and callers MUST treat it as protected. The whole-buffer check
    for the imported form runs FIRST, which is what makes the unsafe direction unreachable: a file
    containing that string anywhere is reported imported, so a nested ``source`` key can only ever
    over-protect.
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
#: cannot match unrelated keys like ``lap_history`` or ``lap_ms``. Case-insensitive to match the
#: filesystem this runs on; :func:`referenced_names` lower-cases what it captures.
_ARCHIVE_TOKEN = re.compile(rb"lap_[0-9A-Za-z._-]+\.json", re.IGNORECASE)


def referenced_names(state_dir: Path) -> tuple[set[str], list[str]]:
    """Archive names mentioned by any state file under ``state_dir``, and what could not be read.

    Returns ``(names, unreadable)``. **The second element is not diagnostics — it is a veto.**
    An empty reference set is what authorises deletion, so a state file we failed to read is
    indistinguishable from one that protects nothing. Silently skipping it (``continue``) would
    make an AC-held file lock, a dehydrated OneDrive placeholder, or an antivirus scan look like
    consent to delete. Callers must refuse to prune while ``unreadable`` is non-empty; this is the
    same fail-closed posture :func:`archive_source` takes when it returns ``None``.

    **Recursive on purpose.** On the rig, ``journal/reports/*.json`` names 187 lap archives while
    the per-combo files at the top level name none — a top-level-only scan left every one of those
    unprotected. Anything that can name an archive, at any depth, can protect it.

    Token extraction rather than schema parsing, so a schema change cannot silently un-protect a
    referenced archive, and one pass over the bytes rather than a scan per archive. Over-matching
    is the safe direction: a spurious name protects a file that did not need protecting.

    The ``journal/laps`` tree is excluded — archives referencing each other must not keep each
    other alive, and reading them here would re-introduce the very cost this work removes.

    Names are lower-cased for comparison: this runs on a case-insensitive filesystem, where a
    state file naming ``lap_Ref.JSON`` must still protect ``lap_ref.json``.
    """
    names: set[str] = set()
    unreadable: list[str] = []
    if not state_dir.is_dir():
        # Not "nothing is protected" — we have no idea what is protected.
        return names, [f"{state_dir}: not a directory"]
    for candidate in sorted(state_dir.rglob("*.json")):
        relative = candidate.relative_to(state_dir).parts
        if relative[:2] == ("journal", "laps"):
            continue
        try:
            raw = candidate.read_bytes()
        except OSError as exc:
            unreadable.append(f"{'/'.join(relative)}: {exc}")
            continue
        for match in _ARCHIVE_TOKEN.finditer(raw):
            names.add(match.group(0).decode("ascii").lower())
    return names, unreadable


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
    #: State files the reference scan could not read. Non-empty forces `prune` to be empty.
    unreadable_state: tuple[str, ...] = ()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime(path: Path) -> float:
    """Sort key that tolerates the file vanishing mid-run. Missing sorts oldest; it is gone."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def build_plan(laps_dir: Path, state_dir: Path, *, keep: int = DEFAULT_KEEP) -> Plan:
    """Decide which archives may be removed. Pure w.r.t. the filesystem: it never deletes."""
    if keep < 0:
        raise ValueError("keep must be >= 0")
    # `_size` rather than a bare `p.stat()`: the app's own `lap_archive.rotate` deletes from this
    # directory after every completed lap, so a file can vanish between the glob and the sort.
    # An unhandled FileNotFoundError out of the sort key is not an acceptable way to find out.
    archives = sorted(laps_dir.glob("lap_*.json"), key=lambda p: (_mtime(p), p.name))
    total_bytes = sum(_size(p) for p in archives)
    newest = set(archives[len(archives) - keep :]) if keep else set()
    referenced, unreadable = referenced_names(state_dir)

    prune: list[Path] = []
    imported: list[Path] = []
    ref_protected: list[Path] = []
    for path in archives:
        if path in newest:
            continue
        if path.name.lower() in referenced:
            ref_protected.append(path)
            continue
        # `None` (undetermined) is treated exactly like "imported": protected.
        if archive_source(path) != "in_game":
            imported.append(path)
            continue
        prune.append(path)
    if unreadable:
        # Fail closed: an incomplete reference scan cannot authorise a single deletion.
        ref_protected.extend(prune)
        prune = []
    return Plan(
        keep_newest=keep,
        total=len(archives),
        total_bytes=total_bytes,
        prune=tuple(prune),
        protected_imported=tuple(imported),
        protected_referenced=tuple(ref_protected),
        reclaimed_bytes=sum(_size(p) for p in prune),
        unreadable_state=tuple(unreadable),
    )


def apply_plan(plan: Plan) -> tuple[int, list[str]]:
    """Delete the planned archives. Returns ``(removed, errors)``; never raises on one bad file.

    Re-checks each archive's ``source`` immediately before unlinking. A lap can be completed and
    archived while this runs, and the plan is a snapshot; the re-check costs one plain scan of a
    file we are about to destroy, which is a trivial price for not destroying the wrong one.
    """
    removed = 0
    errors: list[str] = []
    for path in plan.prune:
        if archive_source(path) != "in_game":
            errors.append(f"{path.name}: no longer classifies as in_game, kept")
            continue
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
    if plan.unreadable_state:
        yield ""
        yield "REFUSING TO PRUNE: the reference scan was incomplete, so an archive that is still"
        yield "referenced cannot be told apart from one that is not. Unreadable state file(s):"
        for entry in plan.unreadable_state[:5]:
            yield f"  {entry}"
        if len(plan.unreadable_state) > 5:
            yield f"  ... and {len(plan.unreadable_state) - 5} more"
        yield ""
        yield "Close Assetto Corsa (or whatever holds these open) and re-run."
        return
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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="required with --apply --keep 0, which disables the newest-N protection entirely",
    )
    args = parser.parse_args(argv)

    # Argument validation before environment inspection: a bad `--keep` is a bad `--keep`
    # whether or not a journal happens to exist.
    if args.keep < 0:
        print("--keep must be >= 0", file=sys.stderr)
        return 2
    if args.apply and args.keep == 0 and not args.yes:
        # `--keep 0` turns off the only protection that does not depend on reading a file
        # correctly, and `0` is one keystroke from `10`. Make it deliberate.
        print("--apply --keep 0 disables the newest-N protection; pass --yes", file=sys.stderr)
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
    if plan.unreadable_state:
        return 4
    if errors:
        # A wrapper script must be able to see that the prune was only partly carried out.
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
