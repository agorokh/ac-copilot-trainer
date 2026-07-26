"""Deterministic Assetto Corsa car-class enrichment (issue #534).

The checked-in override registry is the authority for facts that ``ui_car.json``
cannot express, especially engine placement.  Metadata classification is deliberately
conservative and total: every safe car id resolves to a stable class, even when a mod
has missing or malformed UI metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ENV_AC_ROOT = "AC_COPILOT_AC_ROOT"
DEFAULT_AC_ROOT = Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa")
DEFAULT_CLASS = "road"
REGISTRY_PATH = Path(__file__).with_name("car_class_overrides.json")

CAR_CLASSES: frozenset[str] = frozenset(
    {
        "rear-engine-gt",
        "front-engine-gt",
        "mid-engine-gt",
        "formula",
        "prototype",
        "hypercar",
        "touring",
        "drift",
        "gt",
        "race",
        "road",
    }
)
_SAFE_CAR_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_WORD = re.compile(r"[a-z0-9]+")


class CarClassRegistryError(ValueError):
    """Raised when the checked-in override authority is malformed."""


@dataclass(frozen=True)
class CarClassRegistry:
    version: int
    default_class: str
    overrides: dict[str, str]


@dataclass(frozen=True)
class CarClassResolution:
    car_id: str
    car_class: str
    source: str
    registry_version: int
    ui_class: str | None = None

    def wire_fields(self) -> dict[str, Any]:
        """Fields merged into the authoritative ``session`` snapshot."""

        return {
            "car_class": self.car_class,
            "car_class_source": self.source,
            "car_class_registry_version": self.registry_version,
            "car_ui_class": self.ui_class,
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise CarClassRegistryError(f"duplicate registry key: {key!r}")
        out[key] = value
    return out


@lru_cache(maxsize=8)
def load_registry(path: str | Path = REGISTRY_PATH) -> CarClassRegistry:
    """Load the versioned JSON registry without adding a runtime parser dependency."""

    registry_path = Path(path)
    try:
        raw = json.loads(
            registry_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CarClassRegistryError(
            f"cannot load car-class registry {registry_path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise CarClassRegistryError("car-class registry root must be an object")
    if raw.get("version") != 1:
        raise CarClassRegistryError(
            f"unsupported car-class registry version: {raw.get('version')!r}"
        )
    default_class = raw.get("default_class")
    if default_class not in CAR_CLASSES:
        raise CarClassRegistryError(f"invalid default class: {default_class!r}")
    overrides_raw = raw.get("overrides")
    if not isinstance(overrides_raw, dict):
        raise CarClassRegistryError("car-class registry overrides must be an object")
    overrides: dict[str, str] = {}
    for car_id, car_class in overrides_raw.items():
        if not isinstance(car_id, str) or not _safe_car_id(car_id):
            raise CarClassRegistryError(f"invalid override car id: {car_id!r}")
        if car_class not in CAR_CLASSES:
            raise CarClassRegistryError(f"invalid class for {car_id!r}: {car_class!r}")
        folded = car_id.casefold()
        if folded in overrides:
            raise CarClassRegistryError(f"duplicate case-insensitive override: {car_id!r}")
        overrides[folded] = car_class
    return CarClassRegistry(version=1, default_class=default_class, overrides=overrides)


def _safe_car_id(car_id: str) -> bool:
    return (
        bool(car_id)
        and car_id not in {".", ".."}
        and _SAFE_CAR_ID.fullmatch(car_id) is not None
        and "/" not in car_id
        and "\\" not in car_id
    )


def resolve_ac_root(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    configured = os.environ.get(ENV_AC_ROOT)
    return Path(configured) if configured else DEFAULT_AC_ROOT


def _escape_controls_in_json_strings(text: str) -> str:
    """Repair AC UI JSON that contains raw newlines/tabs inside descriptions.

    Kunos and mod UI files commonly contain otherwise-invalid JSON strings with literal
    control characters.  This state machine changes controls only while inside a quoted
    string; structural whitespace is preserved.
    """

    out: list[str] = []
    in_string = False
    escaped = False
    for character in text:
        if not in_string:
            out.append(character)
            if character == '"':
                in_string = True
            continue
        if escaped:
            out.append(character)
            escaped = False
            continue
        if character == "\\":
            out.append(character)
            escaped = True
        elif character == '"':
            out.append(character)
            in_string = False
        elif ord(character) < 0x20:
            replacements = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
            out.append(replacements.get(character, f"\\u{ord(character):04x}"))
        else:
            out.append(character)
    return "".join(out)


def load_ui_metadata(car_id: str, *, ac_root: str | Path | None = None) -> dict[str, Any] | None:
    """Read only the UI metadata fields used by the classifier.

    Unsafe ids and all file/JSON failures resolve as missing metadata.  The resolved
    containment check is defense in depth in addition to the one-component id grammar.
    """

    if not isinstance(car_id, str) or not _safe_car_id(car_id):
        return None
    cars_root = (resolve_ac_root(ac_root) / "content" / "cars").resolve()
    ui_path = (cars_root / car_id / "ui" / "ui_car.json").resolve()
    try:
        ui_path.relative_to(cars_root)
    except ValueError:
        return None
    try:
        text = ui_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        try:
            raw = json.loads(_escape_controls_in_json_strings(text))
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    return {
        "class": raw.get("class"),
        "tags": raw.get("tags"),
        "specs": raw.get("specs"),
    }


def _metadata_words(metadata: dict[str, Any] | None) -> tuple[set[str], str]:
    if not isinstance(metadata, dict):
        return set(), ""
    values: list[str] = []
    raw_class = metadata.get("class")
    if isinstance(raw_class, str):
        values.append(raw_class)
    tags = metadata.get("tags")
    if isinstance(tags, str):
        values.append(tags)
    elif isinstance(tags, list | tuple | set):
        values.extend(str(tag) for tag in tags if isinstance(tag, str | int | float))
    specs = metadata.get("specs")
    if isinstance(specs, dict):
        values.extend(
            str(value) for value in specs.values() if isinstance(value, str | int | float)
        )
    normalized = " ".join(values).casefold()
    return set(_WORD.findall(normalized)), normalized


def _classify_metadata_rule(metadata: dict[str, Any] | None) -> str | None:
    words, normalized = _metadata_words(metadata)
    raw_class = metadata.get("class") if isinstance(metadata, dict) else None
    raw_words = set(_WORD.findall(raw_class.casefold())) if isinstance(raw_class, str) else set()

    if (
        words.intersection({"singleseater", "formula", "indy", "f1", "f2", "f3", "f4"})
        or "single seater" in normalized
    ):
        return "formula"
    if (
        words.intersection({"prototype", "lmp1", "lmp2", "lmp3", "lmdh", "lmh"})
        or "proto c" in normalized
        or "group c" in normalized
    ):
        return "prototype"
    if words.intersection({"hypercar", "hypercars"}):
        return "hypercar"
    if words.intersection({"touring", "tcr", "dtm", "btcc"}):
        return "touring"
    if "drift" in words:
        return "drift"

    gt_words = {"gt", "gt1", "gt2", "gt3", "gt4", "gte"}
    road_words = {"street", "road", "stock", "track", "supercars"}
    if raw_words.intersection(gt_words) or (
        not raw_words.intersection(road_words) and words.intersection(gt_words)
    ):
        return "gt"
    if "race" in raw_words:
        return "race"
    if raw_words.intersection(road_words):
        return "road"
    if "race" in words:
        return "race"
    return None


def classify_metadata(
    metadata: dict[str, Any] | None, *, default_class: str = DEFAULT_CLASS
) -> str:
    """Classify UI metadata using a stable, ordered vocabulary."""

    if default_class not in CAR_CLASSES:
        raise ValueError(f"invalid default class: {default_class!r}")
    return _classify_metadata_rule(metadata) or default_class


def classify_car(
    car_id: str,
    metadata: dict[str, Any] | None,
    *,
    registry: CarClassRegistry | None = None,
) -> CarClassResolution:
    """Pure override-first resolution for one car."""

    active_registry = registry or load_registry()
    override = active_registry.overrides.get(car_id.casefold()) if isinstance(car_id, str) else None
    ui_class_raw = metadata.get("class") if isinstance(metadata, dict) else None
    ui_class = ui_class_raw if isinstance(ui_class_raw, str) and ui_class_raw else None
    if override is not None:
        return CarClassResolution(
            car_id=car_id,
            car_class=override,
            source="override",
            registry_version=active_registry.version,
            ui_class=ui_class,
        )
    matched_class = _classify_metadata_rule(metadata)
    classified = matched_class or active_registry.default_class
    return CarClassResolution(
        car_id=car_id,
        car_class=classified,
        source="metadata" if matched_class is not None else "default",
        registry_version=active_registry.version,
        ui_class=ui_class,
    )


def resolve_installed_car(
    car_id: str,
    *,
    ac_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY_PATH,
) -> CarClassResolution:
    registry = load_registry(registry_path)
    return classify_car(
        car_id,
        load_ui_metadata(car_id, ac_root=ac_root),
        registry=registry,
    )


def audit_installed_fleet(*, ac_root: str | Path | None = None) -> dict[str, Any]:
    root = resolve_ac_root(ac_root)
    cars_root = root / "content" / "cars"
    rows: list[dict[str, Any]] = []
    if cars_root.is_dir():
        for car_dir in sorted(
            (path for path in cars_root.iterdir() if path.is_dir()), key=lambda p: p.name
        ):
            rows.append(asdict(resolve_installed_car(car_dir.name, ac_root=root)))
    counts: dict[str, int] = {}
    for row in rows:
        car_class = str(row["car_class"])
        counts[car_class] = counts.get(car_class, 0) + 1
    return {
        "ac_root": str(root),
        "cars": len(rows),
        "classes": dict(sorted(counts.items())),
        "resolutions": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit deterministic classes for an AC car fleet")
    parser.add_argument("--ac-root", type=Path, default=None)
    parser.add_argument("--car-id", default=None)
    args = parser.parse_args(argv)
    payload = (
        asdict(resolve_installed_car(args.car_id, ac_root=args.ac_root))
        if args.car_id
        else audit_installed_fleet(ac_root=args.ac_root)
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as an operator CLI
    raise SystemExit(main())
