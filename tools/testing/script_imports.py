"""Helpers for importing repo scripts in tests without mutating ``sys.path``."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType


class _SiblingScriptFinder(importlib.abc.MetaPathFinder):
    """Import same-directory script modules without exposing packages on ``sys.path``."""

    def __init__(self, script_dir: Path) -> None:
        self._script_dir = script_dir

    def find_spec(
        self,
        fullname: str,
        path: object | None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if "." in fullname:
            return None
        candidate = self._script_dir / f"{fullname}.py"
        if not candidate.is_file():
            return None
        return importlib.util.spec_from_file_location(fullname, candidate)


@contextmanager
def _sibling_script_imports(script_dir: Path) -> Iterator[None]:
    finder = _SiblingScriptFinder(script_dir)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)


def load_script_module(module_name: str, path: Path) -> ModuleType:
    """Load a repo script by file path without putting its directory on ``sys.path``."""
    resolved_path = path.resolve()
    cached = sys.modules.get(module_name)
    if cached is not None:
        if not isinstance(cached, ModuleType):
            raise ImportError(f"{module_name!r} is already bound to a non-module object")
        cached_path = getattr(cached, "__file__", None)
        if cached_path is not None and Path(cached_path).resolve() == resolved_path:
            return cached
        raise ImportError(
            f"{module_name!r} is already loaded from {cached_path!r}; "
            f"refusing to reuse it for {resolved_path}"
        )

    spec = importlib.util.spec_from_file_location(module_name, resolved_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {module_name} at {resolved_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        with _sibling_script_imports(resolved_path.parent):
            spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module
