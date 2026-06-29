"""Register a curated AC setup as a first-class data-platform entity.

WHY THIS EXISTS
---------------
The coaching lakehouse (``tools/coaching_lake``) keys every lap on ``laps.setup_hash`` and
bridges setup parameters to outcomes through ``setup_params`` — but those rows only exist for
setups that have been *driven* and archived. A **curated** setup (one we author and want to
coach against) had no place in the data platform until it was driven. This module closes that
gap: it turns a curated ``.ini`` into a catalog row whose ``canonical_hash`` is **byte-for-byte
the same hash the rig computes for a driven lap**, so the moment the operator drives the setup,
the curated catalog row and the lakehouse lap rows join on a single key — with a name/path
fallback when the byte hash misses.

THE JOIN KEY (verified against source; confirmed by an adversarial data-platform review)
----------------------------------------------------------------------------------------
The authoritative hash is produced in Lua by ``src/ac_copilot_trainer/modules/setup_reader.lua``:

  * ``canonicalSetupString``: for every ``[SECTION] KEY=value`` tuple harvested from the INI,
    build ``"<SECTION>|<KEY>=<value>"`` (RAW string value, ALL keys incl. ``CAR.MODEL`` /
    ``__EXT_PATCH``), **sort** the parts, join with ``";"``.
  * ``digestSetup``: djb2 over the canonical string — ``h = 5381; h = (h*33 + byte) mod 2**32``
    — emitted as zero-padded lowercase ``%08x`` (8 hex chars).

That 8-hex digest is written to the lap archive as ``setup.hash`` (``lap_archive.lua``), which
the lakehouse stores verbatim as ``laps.setup_hash`` / ``setup_params.setup_hash`` and which
``setup_optimizer.record_from_lap_archive`` adopts as the experiment key (its ``_stable_hash``
sha1 is a *fallback* the real driven path never reaches). So replicating the **djb2** here — NOT
a sha1 — is what bridges both stores. A sha1/16-hex hash could never collide with a djb2/8-hex
one; that mismatch was the trap the design review flagged, and this module avoids it.

HONEST CAVEAT
-------------
The driven-lap hash is computed over the *live* ``setup.ini`` Assetto Corsa materializes after a
setup is loaded. If AC normalizes/adds sections vs. our source file, the canonical hashes can
differ. We therefore also record ``name`` + ``source_path`` + a meta-independent ``tunable_hash``
so the catalog still joins by setup name/path (the lakehouse keeps ``laps.setup_path``) and by
tune fingerprint even if the exact byte match is missed. Treat ``canonical_hash`` as the
*expected* key — confirm it against the first driven lap. The robust, hash-independent path is
the name/path join baked into :func:`catalog_join_sql`. Future hardening (recommended by the
review): centralize this projection in ``setup_model`` and recompute it on the lake side into its
own column. See vault node ``03_Investigations/curated-setup-hash-bridge-2026-06-28.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.ai_sidecar.setup_model import from_snapshot, parse_setup_ini

SCHEMA_VERSION = 1
DEFAULT_REGISTRY = "assets/setups/_catalog/registry.jsonl"
_MOD32 = 4294967296  # 2**32

# Mirrors Lua readIniSnapshot: a section is ``^[name]``; a key line is ``^WORD = value`` anchored at
# column 0 (no indentation), value is the trimmed remainder. %w in Lua is [A-Za-z0-9]; '_' is added.
_SECTION_RE = re.compile(r"^\[([^\]]+)\]")
_KEY_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def _canonical_pairs(text: str) -> list[tuple[str, str, str]]:
    """Harvest ``(section, key, value)`` tuples like ``setup_reader.lua::readIniSnapshot``."""
    pairs: list[tuple[str, str, str]] = []
    section = ""
    for line in text.splitlines():  # splitlines() strips \n and \r\n like Lua's [^\r\n]+ does
        sec = _SECTION_RE.match(line)
        if sec:
            section = sec.group(1)
            continue
        kv = _KEY_RE.match(line)
        if kv:
            pairs.append((section, kv.group(1), kv.group(2)))
    return pairs


def canonical_setup_string(text: str) -> str:
    """Sorted ``SECTION|KEY=value`` join — the string the rig hashes (``canonicalSetupString``)."""
    parts = [f"{sec}|{key}={val}" for (sec, key, val) in _canonical_pairs(text)]
    parts.sort()
    return ";".join(parts)


def djb2_8hex(s: str) -> str:
    """djb2 digest as zero-padded lowercase 8-hex — matches ``setup_reader.lua::digestSetup``.

    Empty input yields ``""`` (the Lua function's documented empty-canonical short-circuit).
    """
    if not s:
        return ""
    h = 5381
    for b in s.encode("utf-8"):  # iterate bytes to match Lua string.byte over the UTF-8 buffer
        h = (h * 33 + b) % _MOD32
    return f"{h:08x}"


def canonical_hash(ini_text: str) -> str:
    """The rig-faithful join key (8-hex djb2 over the canonical string) for a setup INI's text."""
    return djb2_8hex(canonical_setup_string(ini_text))


def _numeric_params(snapshot: dict[str, str]) -> dict[str, float]:
    """``{SECTION.KEY: float}`` for finite-numeric entries of a snapshot (drops MODEL/VERSION)."""
    out: dict[str, float] = {}
    for key, raw in snapshot.items():
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val == val and val not in (float("inf"), float("-inf")):  # finite
            out[str(key)] = val
    return out


def tunable_hash(snapshot: dict[str, str]) -> str:
    """Meta-independent fingerprint of the tunable numerics (sha1-12 of sorted key=value pairs).

    Stable across ``[ABOUT]``/``[CAR]``/``[__EXT_PATCH]`` differences, so it identifies "the same
    tune" even when the canonical (whole-file) hash would differ on metadata. Secondary dedup key
    only — it is deliberately NOT the cross-store join key (that is :func:`canonical_hash`).
    """
    params = _numeric_params(snapshot)
    canonical = ";".join(f"{k}={params[k]!r}" for k in sorted(params))
    if not canonical:
        return ""
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


@dataclass
class SetupRecord:
    """One curated-setup catalog row."""

    name: str
    car_id: str
    track_id: str | None
    source_path: str
    canonical_hash: str
    tunable_hash: str
    param_count: int
    params: dict[str, float] = field(default_factory=dict)
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)
    author: str | None = None
    provenance: str | None = None
    registered_at: str | None = None
    schema_version: int = SCHEMA_VERSION

    def catalog_key(self) -> tuple[str, str, str]:
        """Idempotency key for the registry upsert."""
        return (self.car_id, self.track_id or "", self.name)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "car_id": self.car_id,
            "track_id": self.track_id,
            "source_path": self.source_path,
            "canonical_hash": self.canonical_hash,
            "tunable_hash": self.tunable_hash,
            "param_count": self.param_count,
            "params": self.params,
            "by_category": self.by_category,
            "author": self.author,
            "provenance": self.provenance,
            "registered_at": self.registered_at,
        }


def build_record(
    ini_path: str | Path,
    *,
    car_id: str | None = None,
    track_id: str | None = None,
    name: str | None = None,
    author: str | None = None,
    provenance: str | None = None,
    source_path: str | None = None,
    now: datetime | None = None,
) -> SetupRecord:
    """Parse a curated ``.ini`` into a :class:`SetupRecord` (no I/O beyond reading ``ini_path``)."""
    path = Path(ini_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    snapshot = parse_setup_ini(text)
    setup = from_snapshot(snapshot)
    resolved_car = (
        car_id or snapshot.get("CAR.MODEL") or snapshot.get("CAR.SCREEN_NAME") or "unknown"
    )
    by_cat: dict[str, dict[str, float]] = {}
    for cat, params in setup.by_category().items():
        bucket = {p.section: p.value for p in params if p.value is not None}
        if bucket:
            by_cat[cat] = bucket
    numeric = _numeric_params(snapshot)
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # POSIX-normalize the stored path so the version-controlled catalog is portable across OSes.
    stored_path = (source_path or str(path)).replace("\\", "/")
    return SetupRecord(
        name=name or path.stem,
        car_id=resolved_car,
        track_id=track_id,
        source_path=stored_path,
        canonical_hash=canonical_hash(text),
        tunable_hash=tunable_hash(snapshot),
        param_count=len(numeric),
        params=numeric,
        by_category=by_cat,
        author=author,
        provenance=provenance,
        registered_at=stamp,
    )


def load_registry(registry_path: str | Path) -> list[dict[str, Any]]:
    """Read the JSONL registry into a list of dicts (empty if the file is absent)."""
    path = Path(registry_path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("car_id", "")), str(row.get("track_id") or ""), str(row.get("name", "")))


def register_setup(
    ini_path: str | Path,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY,
    car_id: str | None = None,
    track_id: str | None = None,
    name: str | None = None,
    author: str | None = None,
    provenance: str | None = None,
    source_path: str | None = None,
    now: datetime | None = None,
) -> SetupRecord:
    """Build a record and **upsert** it into the JSONL registry (idempotent by car/track/name)."""
    record = build_record(
        ini_path,
        car_id=car_id,
        track_id=track_id,
        name=name,
        author=author,
        provenance=provenance,
        source_path=source_path,
        now=now,
    )
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in load_registry(path) if _row_key(r) != record.catalog_key()]
    rows.append(record.to_json())
    rows.sort(key=_row_key)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    return record


def deploy_setup(
    ini_path: str | Path,
    ac_userdata: str | Path,
    *,
    car_id: str | None = None,
    track_id: str | None = None,
    force: bool = False,
) -> Path:
    """Copy a curated ``.ini`` into ``<ac_userdata>/setups/<carID>/[<track>/]`` (additive).

    Deployment is a deliberate, separate action from registration. Guards (per the DP review):

    * The ``<ac_userdata>/setups`` root MUST already exist — i.e. a real AC install / rig host.
      On a non-rig host (no such folder) we raise instead of fabricating a fake AC tree.
    * Refuses to overwrite an existing destination unless ``force=True`` — we never clobber the
      operator's own setups (preserve-manual-work invariant).

    Returns the destination path.
    """
    src = Path(ini_path)
    setups_root = Path(ac_userdata) / "setups"
    if not setups_root.is_dir():
        raise FileNotFoundError(
            f"no AC setups folder at {setups_root} — not a rig host? "
            "Deploy only on a machine with Assetto Corsa user-data present."
        )
    text = src.read_text(encoding="utf-8", errors="replace")
    resolved_car = car_id or parse_setup_ini(text).get("CAR.MODEL") or "unknown"
    dest_dir = setups_root / resolved_car
    if track_id:
        dest_dir = dest_dir / track_id
    dest = dest_dir / src.name
    if dest.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing setup: {dest} (pass force=True)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


# ---------------------------------------------------------------------------
# Catalog ↔ lakehouse join (DuckDB reads the JSONL registry natively; no lake change needed).
# ---------------------------------------------------------------------------
def catalog_join_sql(registry_path: str | Path = DEFAULT_REGISTRY) -> str:
    """SQL that attaches the curated catalog to driven laps in the coaching lake.

    Run inside the lake (``tools.coaching_lake.run_query``). Each curated setup gets its driven-lap
    count + best time, ``NULL`` until it is driven. The join is **robust**: it matches on the exact
    ``canonical_hash`` (the rig djb2) OR, as a fallback, on the setup *name* embedded in
    ``laps.setup_path`` — so a byte-hash miss (AC re-materializing ``setup.ini``) still joins.
    """
    reg = str(Path(registry_path)).replace("\\", "/")
    return f"""
        WITH catalog AS (SELECT * FROM read_json_auto('{reg}'))
        SELECT c.name, c.car_id, c.track_id, c.canonical_hash,
               count(l.lap_uuid) AS driven_laps,
               min(l.lap_ms) FILTER (WHERE l.is_valid) AS best_ms
        FROM catalog c
        LEFT JOIN laps l
          ON l.car_id = c.car_id
         AND (
              l.setup_hash = c.canonical_hash
              OR (l.setup_path IS NOT NULL
                  AND lower(l.setup_path) LIKE '%' || lower(c.name) || '.ini')
         )
        GROUP BY c.name, c.car_id, c.track_id, c.canonical_hash
        ORDER BY c.car_id, c.track_id, c.name
    """


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Register / deploy a curated AC setup (data-platform entity)."
    )
    p.add_argument("ini", nargs="?", help="path to the curated setup .ini")
    p.add_argument("--registry", default=DEFAULT_REGISTRY, help="catalog JSONL path")
    p.add_argument("--car-id", default=None)
    p.add_argument("--track-id", default=None)
    p.add_argument("--name", default=None)
    p.add_argument("--author", default=None)
    p.add_argument("--provenance", default=None)
    p.add_argument("--register", action="store_true", help="upsert the setup into the registry")
    p.add_argument(
        "--deploy", metavar="AC_USERDATA", default=None, help="deploy into <AC_USERDATA>/setups/"
    )
    p.add_argument("--force", action="store_true", help="allow overwrite on deploy")
    p.add_argument("--list", action="store_true", help="print the current registry")
    p.add_argument(
        "--join-sql", action="store_true", help="print the catalog-lake join SQL and exit"
    )
    args = p.parse_args(argv)

    if args.join_sql:
        print(catalog_join_sql(args.registry))
        return 0
    if args.list:
        for row in load_registry(args.registry):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if not args.ini:
        p.error("ini path required unless --list/--join-sql")
    if args.register:
        rec = register_setup(
            args.ini,
            registry_path=args.registry,
            car_id=args.car_id,
            track_id=args.track_id,
            name=args.name,
            author=args.author,
            provenance=args.provenance,
        )
        print(
            f"registered {rec.name} car={rec.car_id} track={rec.track_id} "
            f"canonical_hash={rec.canonical_hash} params={rec.param_count}"
        )
    if args.deploy:
        dest = deploy_setup(
            args.ini, args.deploy, car_id=args.car_id, track_id=args.track_id, force=args.force
        )
        print(f"deployed -> {dest}")
    if not args.register and not args.deploy:
        p.error("nothing to do: pass --register and/or --deploy (or --list/--join-sql)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
