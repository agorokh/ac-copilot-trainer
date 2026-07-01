"""Per-car setup schema: the full ``ac.getSetupSpinners()`` space, persisted and decodable.

Models the **entire** tunable setup — every spinner's range/step/units/``displayMultiplier`` and
enum ``items`` — not the ~25-section subset hardcoded in :mod:`setup_model`. It is the schema oracle
the optimizer constrains proposals against, and the lens that decodes a click-index into engineering
units (``CAMBER_LF=-20`` clicks → ``-3.0°``). Without it a stored AC ``.ini`` (raw spinner indices)
is uninterpretable — exactly the gap Setup Exchange punts entirely to the live game.

Source of truth on the rig is ``ac.getSetupSpinners()``; capturing it is rig-gated (a stub seam).
This module ingests a JSON dump of that call into a versioned, committable schema asset under
``assets/setups/_schema/<car_id>/<schema_hash>.json``. First increment of the Setup Intelligence
Platform (see vault ``01_Decisions/setup-intelligence-platform-2026-06-29.md``). Pure stdlib
(reuses only :func:`setup_model.spec_for` for the category/name taxonomy).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.ai_sidecar.setup_model import spec_for  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_SCHEMA_DIR = "assets/setups/_schema"
_SAFE_SCHEMA_CAR_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _schema_root(schema_dir: str | Path = DEFAULT_SCHEMA_DIR) -> Path:
    root = Path(schema_dir)
    if root.is_absolute():
        return root
    return Path(__file__).resolve().parents[2] / root


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _safe_schema_car_id(car_id: str | None) -> str | None:
    if not car_id:
        return None
    text = car_id.strip()
    if (
        not text
        or ".." in text
        or not any(char.isalnum() for char in text)
        or not _SAFE_SCHEMA_CAR_ID.fullmatch(text)
    ):
        return None
    return text


def _safe_schema_file(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not _is_relative_to(resolved, root) or not resolved.is_file():
        return None
    return resolved


def load_latest_schema(
    car_id: str | None,
    schema_dir: str | Path = DEFAULT_SCHEMA_DIR,
) -> CarSetupSchema | None:
    """Load the newest checked-in schema asset for ``car_id``, if one exists."""
    safe_car_id = _safe_schema_car_id(car_id)
    if safe_car_id is None:
        return None
    root = _schema_root(schema_dir).resolve()
    car_dir = (root / safe_car_id).resolve()
    if not _is_relative_to(car_dir, root):
        return None
    if not car_dir.is_dir():
        return None
    candidates = [
        (path, resolved)
        for path in sorted(
            car_dir.glob("*.json"),
            key=lambda path: path.name,
        )
        if (resolved := _safe_schema_file(path, root)) is not None
    ]
    if not candidates:
        return None
    marker = car_dir / "latest.json"
    for path, resolved in candidates:
        if path == marker:
            return CarSetupSchema.load(resolved)
    return CarSetupSchema.load(candidates[-1][1])


def _f(value: Any) -> float | None:
    """Coerce to a finite float, else None (booleans are not numbers here)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


@dataclass(frozen=True)
class SpinnerDesc:
    """One spinner descriptor from ``ac.getSetupSpinners()`` — a full tunable knob, not a value."""

    name: str
    label: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    value: float | None = None
    default: float | None = None
    display_multiplier: float | None = None  # click-index → engineering value (linear, per CSP)
    units: str | None = None
    items: list[str] | None = None  # enumerated labels (e.g. compounds, gearsets)
    item_values: list[float] | None = None
    read_only: bool = False

    @property
    def category(self) -> str:
        return spec_for(self.name).category

    def decode(self, click: float | None) -> float | str | None:
        """A click index → its engineering value, or the enum label for enumerated spinners.

        ``display_multiplier`` is treated as a linear click→engineering scale (the documented CSP
        convention); confirm against a real dump before trusting absolute units in coaching copy.
        """
        if click is None:
            return None
        if self.items:
            if self.item_values:
                for pos, raw in enumerate(self.item_values):
                    if raw is not None and abs(raw - float(click)) < 1e-9 and pos < len(self.items):
                        return self.items[pos]
                return None
            idx = int(round(float(click)))
            return self.items[idx] if 0 <= idx < len(self.items) else None
        if self.display_multiplier is not None:
            return float(click) * self.display_multiplier
        return float(click)

    def clamp(self, click: float) -> float:
        """Clamp a click value into ``[min, max]`` and snap it onto the ``step`` grid."""
        v = float(click)
        if self.min is not None:
            v = max(v, self.min)
        if self.max is not None:
            v = min(v, self.max)
        if self.step and self.step > 0 and self.min is not None:
            v = self.min + round((v - self.min) / self.step) * self.step
            if self.max is not None and v > self.max:
                max_steps = max(math.floor((self.max - self.min) / self.step), 0)
                v = self.min + max_steps * self.step
            if v < self.min:
                v = self.min
        return v

    def is_valid(self, click: float) -> bool:
        """True iff ``click`` is writable, in range, and on the ``step`` grid."""
        if self.read_only:
            return False
        v = float(click)
        if self.items and self.item_values:
            return any(
                raw is not None and abs(raw - v) <= 1e-9 and pos < len(self.items)
                for pos, raw in enumerate(self.item_values)
            )
        if self.min is not None and v < self.min - 1e-9:
            return False
        if self.max is not None and v > self.max + 1e-9:
            return False
        if self.step and self.step > 0 and self.min is not None:
            n = (v - self.min) / self.step
            if abs(n - round(n)) > 1e-6:
                return False
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "value": self.value,
            "default": self.default,
            "displayMultiplier": self.display_multiplier,
            "units": self.units,
            "items": self.items,
            "itemValues": self.item_values,
            "readOnly": self.read_only,
        }

    @classmethod
    def from_dump(cls, sp: dict[str, Any]) -> SpinnerDesc:
        items = sp.get("items")
        item_values = sp.get("itemValues")
        return cls(
            name=str(sp.get("name", "")).strip(),
            label=sp.get("label"),
            min=_f(sp.get("min")),
            max=_f(sp.get("max")),
            step=_f(sp.get("step")),
            value=_f(sp.get("value")),
            default=_f(sp.get("defaultValue", sp.get("default"))),
            display_multiplier=_f(sp.get("displayMultiplier")),
            units=sp.get("units", sp.get("unit")),
            items=[str(x) for x in items] if isinstance(items, list) else None,
            item_values=[_f(x) for x in item_values] if isinstance(item_values, list) else None,
            read_only=bool(sp.get("readOnly", False)),
        )


@dataclass
class CarSetupSchema:
    """The full per-car spinner space, hash-versioned so old setups stay decodable."""

    car_id: str
    spinners: dict[str, SpinnerDesc] = field(default_factory=dict)
    cautions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    schema_hash: str = ""
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_spinners_dump(cls, car_id: str, dump: list[dict[str, Any]]) -> CarSetupSchema:
        """Build from a raw ``ac.getSetupSpinners()`` list (the rig capture seam)."""
        spinners: dict[str, SpinnerDesc] = {}
        for sp in dump:
            if not isinstance(sp, dict):
                continue
            desc = SpinnerDesc.from_dump(sp)
            if desc.name:
                spinners[desc.name] = desc
        obj = cls(car_id=car_id, spinners=spinners)
        obj.schema_hash = obj.compute_hash()
        return obj

    @classmethod
    def from_car_setup(cls, setup: Any) -> CarSetupSchema | None:
        """Build from a :class:`setup_model.CarSetup` that carries a ``spinner_schema``."""
        sched = getattr(setup, "spinner_schema", None)
        if not isinstance(sched, dict) or not sched:
            return None
        dump = [{"name": name, **vals} for name, vals in sched.items() if isinstance(vals, dict)]
        return cls.from_spinners_dump(getattr(setup, "car_id", None) or "unknown", dump)

    def compute_hash(self) -> str:
        """Stable digest over the descriptor STRUCTURE (ranges/steps/enums), not current values."""
        payload = {
            "schema_version": self.schema_version,
            "spinners": {
                name: {
                    "displayMultiplier": s.display_multiplier,
                    "itemValues": s.item_values,
                    "items": s.items,
                    "max": s.max,
                    "min": s.min,
                    "readOnly": s.read_only,
                    "step": s.step,
                    "units": s.units,
                }
                for name, s in sorted(self.spinners.items())
            },
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _spinner_name(name: str) -> str:
        text = str(name)
        return text[:-6] if text.upper().endswith(".VALUE") else text

    def get(self, name: str) -> SpinnerDesc | None:
        return self.spinners.get(self._spinner_name(name))

    def validate(self, name: str, click: float) -> bool:
        sp = self.get(name)
        return True if sp is None else sp.is_valid(click)

    def clamp(self, name: str, click: float) -> float:
        sp = self.get(name)
        return float(click) if sp is None else sp.clamp(click)

    def decode(self, name: str, click: float | None) -> float | str | None:
        sp = self.get(name)
        return click if sp is None else sp.decode(click)

    def constrain_params(self, params: dict[str, float]) -> dict[str, float]:
        """Clamp a ``{SECTION[.VALUE]: click}`` candidate so every knob is in-range/on-step."""
        out: dict[str, float] = {}
        for key, val in params.items():
            out[key] = self.clamp(key, val)
        return out

    def caution_notes(
        self,
        name: str,
        *,
        direction: str | None = None,
        current: float | None = None,
    ) -> list[str]:
        notes: list[str] = []
        for rule in self.cautions.get(self._spinner_name(name), []):
            if not isinstance(rule, dict):
                continue
            rule_direction = rule.get("direction")
            if rule_direction is not None and rule_direction != direction:
                continue
            if not _current_matches_rule(current, rule):
                continue
            message = rule.get("message")
            if isinstance(message, str) and message.strip():
                notes.append(message.strip())
        return notes

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "car_id": self.car_id,
            "schema_hash": self.schema_hash,
            "cautions": self.cautions,
            "spinners": {name: sp.to_json() for name, sp in sorted(self.spinners.items())},
        }

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> CarSetupSchema:
        spinners = {
            name: SpinnerDesc.from_dump({"name": name, **desc})
            for name, desc in (obj.get("spinners") or {}).items()
            if isinstance(desc, dict)
        }
        out = cls(
            car_id=str(obj.get("car_id", "unknown")),
            spinners=spinners,
            cautions=_parse_cautions(obj.get("cautions")),
            schema_hash=str(obj.get("schema_hash") or ""),
            schema_version=int(obj.get("schema_version", SCHEMA_VERSION)),
        )
        if not out.schema_hash:
            out.schema_hash = out.compute_hash()
        return out

    def save(self, schema_dir: str | Path = DEFAULT_SCHEMA_DIR) -> Path:
        dest = Path(schema_dir) / self.car_id / f"{self.schema_hash}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_json()
        data.pop("schema_hash", None)  # hash is the filename; keep content secret-scan clean
        body = json.dumps(data, indent=2, sort_keys=True) + "\n"
        dest.write_text(body, encoding="utf-8")
        return dest

    @classmethod
    def load(cls, path: str | Path) -> CarSetupSchema:
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _current_matches_rule(current: float | None, rule: dict[str, Any]) -> bool:
    for key, predicate in (
        ("current_lt", lambda value, limit: value < limit),
        ("current_lte", lambda value, limit: value <= limit),
        ("current_gt", lambda value, limit: value > limit),
        ("current_gte", lambda value, limit: value >= limit),
    ):
        limit = _f(rule.get(key))
        if limit is not None:
            if current is None or not predicate(current, limit):
                return False
    return True


def _parse_cautions(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {}
    parsed: dict[str, list[dict[str, Any]]] = {}
    for name, rules in value.items():
        if not isinstance(name, str) or not isinstance(rules, list):
            continue
        parsed[name] = [dict(rule) for rule in rules if isinstance(rule, dict)]
    return parsed


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Ingest an ac.getSetupSpinners() dump into a schema asset."
    )
    p.add_argument("dump", help="JSON file: a list of getSetupSpinners() descriptors")
    p.add_argument("--car-id", required=True)
    p.add_argument("--schema-dir", default=DEFAULT_SCHEMA_DIR)
    args = p.parse_args(argv)
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    if isinstance(dump, dict) and "spinners" in dump:  # tolerate {spinners:[...]} wrapper
        dump = dump["spinners"]
    schema = CarSetupSchema.from_spinners_dump(args.car_id, dump)
    dest = schema.save(args.schema_dir)
    print(f"wrote {dest} ({len(schema.spinners)} spinners, schema_hash={schema.schema_hash})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
