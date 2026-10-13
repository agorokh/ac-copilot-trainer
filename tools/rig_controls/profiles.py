"""Strict, non-executable JSON profiles shared by agents and the PC worker."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONTROLS = ("button_1", "button_2", "button_3", "knob_cw", "knob_ccw", "knob_press")
MODIFIERS = {"CTRL", "SHIFT", "ALT", "WIN"}
KEYS = (
    MODIFIERS
    | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    | {
        "SPACE",
        "ENTER",
        "ESC",
        "TAB",
        "BACKSPACE",
        "UP",
        "DOWN",
        "LEFT",
        "RIGHT",
        "HOME",
        "END",
        "PAGEUP",
        "PAGEDOWN",
        "INSERT",
        "DELETE",
    }
    | {f"F{i}" for i in range(1, 25)}
)
RIG_ACTIONS = {
    "shakers.power.toggle",
    "shakers.level.increase",
    "shakers.level.decrease",
    "shakers.mute.toggle",
}


@dataclass(frozen=True)
class Context:
    foreground_process: str = ""
    title: str = ""
    running: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Binding:
    action: str
    keys: tuple[str, ...] = ()
    name: str = ""


@dataclass(frozen=True)
class Profile:
    name: str
    rgb: tuple[int, int, int]
    bindings: tuple[Binding, ...]
    priority: int = 0
    foreground: tuple[str, ...] = ()
    running: tuple[str, ...] = ()
    title: str = ""

    def matches(self, context: Context) -> bool:
        processes = {p.casefold() for p in context.running}
        return (
            (not self.foreground or context.foreground_process.casefold() in self.foreground)
            and (not self.running or bool(processes.intersection(self.running)))
            and (not self.title or self.title in context.title.casefold())
        )


@dataclass(frozen=True)
class Config:
    profiles: tuple[Profile, ...]
    default: str
    manual_override: str | None = None

    def select(self, context: Context) -> Profile:
        if self.manual_override:
            return next(p for p in self.profiles if p.name == self.manual_override)
        for profile in sorted(self.profiles, key=lambda p: -p.priority):
            if profile.name != self.default and profile.matches(context):
                return profile
        return next(p for p in self.profiles if p.name == self.default)


def _object(value: object, allowed: set[str], required: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ValueError(
            f"expected object with required keys {sorted(required)}; allowed {sorted(allowed)}"
        )
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError("expected nonempty text of at most 128 characters")
    return value.strip()


def _processes(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError("process matcher needs 1..16 exact executable names")
    names = tuple(_text(p).casefold() for p in value)
    if any("/" in p or "\\" in p or not p.endswith(".exe") for p in names):
        raise ValueError("use executable basenames, such as acs.exe")
    return names


def _binding(value: object) -> Binding:
    data = _object(value, {"action", "keys", "name"}, {"action"})
    action = data["action"]
    if action == "noop" and set(data) == {"action"}:
        return Binding("noop")
    if (
        action == "rig"
        and set(data) == {"action", "name"}
        and isinstance(data["name"], str)
        and data["name"] in RIG_ACTIONS
    ):
        return Binding("rig", name=data["name"])
    if action == "key" and set(data) == {"action", "keys"}:
        keys = data["keys"]
        if isinstance(keys, list) and 1 <= len(keys) <= 4 and all(isinstance(k, str) for k in keys):
            chord = tuple(k.upper() for k in keys)
            if len(set(chord)) == len(chord) and set(chord) <= KEYS and set(chord) - MODIFIERS:
                return Binding(
                    "key",
                    tuple(k for k in chord if k in MODIFIERS)
                    + tuple(k for k in chord if k not in MODIFIERS),
                )
    raise ValueError("binding must be noop, an allowed rig action, or a bounded key chord")


def parse_config(value: object) -> Config:
    data = _object(
        value,
        {"version", "default", "manual_override", "profiles"},
        {"version", "default", "profiles"},
    )
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("unsupported profile version")
    default = _text(data["default"])
    rows = data["profiles"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError("expected 1..32 profiles")
    profiles = []
    names = set()
    for row in rows:
        p = _object(
            row, {"name", "rgb", "bindings", "priority", "when"}, {"name", "rgb", "bindings"}
        )
        name = _text(p["name"])
        if name in names:
            raise ValueError("profile names must be unique")
        names.add(name)
        rgb = p["rgb"]
        if (
            not isinstance(rgb, list)
            or len(rgb) != 3
            or any(type(c) is not int or not 0 <= c <= 255 for c in rgb)
        ):
            raise ValueError("rgb must contain three integers in 0..255")
        priority = p.get("priority", 0)
        if type(priority) is not int or not -1000 <= priority <= 1000:
            raise ValueError("priority must be an integer in -1000..1000")
        bindings = _object(p["bindings"], set(CONTROLS), set(CONTROLS))
        when = _object(
            p.get("when", {}), {"foreground_process", "running_process", "title_contains"}, set()
        )
        if name != default and not when:
            raise ValueError("non-default profiles need a condition")
        if name == default and when:
            raise ValueError("default profile must be unconditional")
        profiles.append(
            Profile(
                name,
                tuple(rgb),
                tuple(_binding(bindings[c]) for c in CONTROLS),
                priority,
                _processes(when["foreground_process"]) if "foreground_process" in when else (),
                _processes(when["running_process"]) if "running_process" in when else (),
                _text(when["title_contains"]).casefold() if "title_contains" in when else "",
            )
        )
    manual = data.get("manual_override")
    if manual is not None:
        manual = _text(manual)
    if default not in names or (manual is not None and manual not in names):
        raise ValueError("default/manual profile does not exist")
    return Config(tuple(profiles), default, manual)


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("profile file exceeds 64 KiB")
    try:
        return parse_config(json.loads(raw.decode("utf-8-sig")))
    except RecursionError as exc:
        raise ValueError("profile JSON nesting is too deep") from exc
