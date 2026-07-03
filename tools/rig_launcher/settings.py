"""Local settings contract for the AC Copilot Game Point launcher."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.rig_launcher.supervisor import DEFAULT_PORT, LauncherPaths

SETTINGS_SCHEMA = "ac-copilot-game-point-settings-v1"


@dataclass(frozen=True)
class LauncherSettings:
    """Non-secret settings loaded from the per-user Game Point folder."""

    sidecar_port: int | None = None
    external_bind: str | None = None
    reference_archive: str | None = None
    voice_bank: str | None = None
    voice_tts: bool | None = None
    setup_store: str | None = None
    simhub_exe: str | None = None
    start_simhub: bool | None = None

    @classmethod
    def load(cls, path: Path) -> LauncherSettings:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError, UnicodeError):
            return cls()
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            sidecar_port=_optional_int(payload.get("sidecar_port")),
            external_bind=_optional_text(payload.get("external_bind")),
            reference_archive=_optional_text(payload.get("reference_archive")),
            voice_bank=_optional_text(payload.get("voice_bank")),
            voice_tts=_optional_bool(payload.get("voice_tts")),
            setup_store=_optional_text(payload.get("setup_store")),
            simhub_exe=_optional_text(payload.get("simhub_exe")),
            start_simhub=_optional_bool(payload.get("start_simhub")),
        )


def ensure_settings_file(paths: LauncherPaths) -> Path:
    """Create the per-user settings file with non-secret defaults if missing."""
    path = paths.settings_path
    if path.exists():
        return path
    paths.root.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(default_settings_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def update_settings(paths: LauncherPaths, **changes: object) -> Path:
    """Merge ``changes`` into the per-user settings.json, preserving other keys.

    Backs the launcher UI toggles (e.g. ``start_simhub``): persist one setting without
    clobbering the operator's others. Guarantees, in order:

    * **No secrets.** Only keys in the non-secret template schema are written, so a
      ``token`` (or any non-schema field) can never round-trip into settings.json — the
      documented launcher contract keeps credentials environment-only.
    * **Preserve manual work.** A *missing* file starts from the template; a *present but
      malformed/unreadable* file is left exactly as the operator wrote it and the call
      raises (``ValueError`` for bad JSON, ``OSError`` for an unreadable file) rather than
      silently overwriting a hand-edited file with defaults.
    * **Atomic + concurrency-safe.** Writes a *unique* temp file (never a shared fixed
      name, so a CLI run and the UI cannot clobber each other) then ``os.replace``s it
      into place, so a crash mid-write cannot truncate an existing settings.json.
    """
    path = paths.settings_path
    loaded: Mapping[str, object]
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        loaded = {}
    except (OSError, UnicodeError) as exc:
        # Present but unreadable — never overwrite the operator's file with defaults.
        raise OSError(f"cannot read {path} to update it: {exc}") from exc
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Preserve manual work: never clobber a malformed hand-edited settings.json.
            raise ValueError(f"refusing to overwrite malformed {path}: {exc}") from exc
        loaded = parsed if isinstance(parsed, Mapping) else {}

    # Baseline on the template (fills partial files), overlay existing + requested keys,
    # and admit ONLY schema keys — dropping any stray secret-like field on the way out.
    allowed = set(default_settings_payload())
    payload = default_settings_payload()
    payload.update({k: v for k, v in loaded.items() if k in allowed})
    payload.update({k: v for k, v in changes.items() if k in allowed})

    paths.root.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except OSError:
        # Never leave a half-written temp file behind on a failed persist.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def default_settings_payload() -> dict[str, object]:
    """Return the editable settings template. Tokens intentionally stay out."""
    return {
        "_schema": SETTINGS_SCHEMA,
        "external_bind": "",
        "reference_archive": "",
        "setup_store": "",
        "sidecar_port": DEFAULT_PORT,
        "simhub_exe": "",
        "start_simhub": False,
        "voice_bank": "",
        "voice_tts": False,
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
