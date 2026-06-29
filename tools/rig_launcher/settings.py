"""Local settings contract for the AC Copilot Game Point launcher."""

from __future__ import annotations

import json
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
