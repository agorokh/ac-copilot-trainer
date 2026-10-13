"""Bounded, stable reads of individually selected JSON files; no discovery."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 20_000_000


class MozaImportError(ValueError):
    """An input cannot be represented safely; the message is a stable reason code."""


@dataclass(frozen=True)
class SelectedJSON:
    payload: dict[str, Any]
    receipt: dict[str, Any]


def _stat(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_size, value.st_mtime_ns, value.st_dev, value.st_ino


def _read_once(path: Path, limit: int) -> tuple[bytes, os.stat_result, os.stat_result]:
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise MozaImportError("input_not_regular_file")
        if before.st_size > limit:
            raise MozaImportError("input_too_large")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > limit:
        raise MozaImportError("input_too_large")
    return raw, before, after


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MozaImportError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise MozaImportError("nonfinite_json_value")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise MozaImportError("nonfinite_json_value")
    return parsed


def read_selected_json(path: Path, *, max_bytes: int = MAX_INPUT_BYTES) -> SelectedJSON:
    """Read exactly one selected file twice; never inspect neighboring files.

    A stable result describes these captured bytes, not an atomic snapshot across
    several app files. Path/fd ctime are compared within their respective APIs:
    Windows exposes different ctime semantics through stat and fstat.
    """
    if type(max_bytes) is not int or max_bytes <= 0:
        raise MozaImportError("invalid_size_limit")
    try:
        selected = path.expanduser().resolve(strict=True)
        before = selected.stat()
        if not stat.S_ISREG(before.st_mode):
            raise MozaImportError("input_not_regular_file")
        first, fd_before, fd_after = _read_once(selected, max_bytes)
        middle = selected.stat()
        second, fd_second_before, fd_second_after = _read_once(selected, max_bytes)
        after = selected.stat()
    except (OSError, RuntimeError) as exc:
        raise MozaImportError("input_unavailable_or_changed") from exc
    path_stats = (before, middle, after)
    fd_stats = (fd_before, fd_after, fd_second_before, fd_second_after)
    all_stats = (*path_stats, *fd_stats)
    if (
        any(_stat(value) != _stat(before) for value in all_stats)
        or any(value.st_ctime_ns != before.st_ctime_ns for value in path_stats)
        or any(value.st_ctime_ns != fd_before.st_ctime_ns for value in fd_stats)
        or first != second
        or len(first) != before.st_size
    ):
        raise MozaImportError("input_changed_during_read")
    try:
        payload = json.loads(
            first.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
            parse_float=_finite_json_float,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, MozaImportError):
            raise
        raise MozaImportError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise MozaImportError("json_root_not_object")
    return SelectedJSON(
        payload,
        {
            "path": str(selected),
            "sha256": hashlib.sha256(first).hexdigest(),
            "bytes": len(first),
            "mtime_ns": before.st_mtime_ns,
            "device": before.st_dev,
            "inode": before.st_ino,
            "captured_at": datetime.now(UTC).isoformat(),
            "status": "stable_captured_bytes",
            "cross_file_atomic": False,
        },
    )


def write_once_json(output: Path, value: Mapping[str, Any], *, inputs: Sequence[Path] = ()) -> None:
    """Publish complete bytes atomically without replacing any existing path.

    A same-directory temporary file is fsynced and linked into place exclusively.
    Unsupported hard links fail safely; there is no overwrite fallback.
    """
    try:
        destination = output.expanduser().absolute()
        resolved = destination.resolve()
        for source in inputs:
            if resolved == source.expanduser().resolve() or (
                destination.exists() and source.exists() and destination.samefile(source)
            ):
                raise MozaImportError("output_aliases_input")
        if destination.exists() or destination.is_symlink():
            raise MozaImportError("output_exists")
        data = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        if isinstance(exc, MozaImportError):
            raise
        raise MozaImportError("invalid_output") from exc
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".moza-import-", suffix=".tmp", dir=destination.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise MozaImportError("output_exists") from exc
    except OSError as exc:
        raise MozaImportError("output_publication_failed") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
