"""Tests for script-import helpers used by repo hook tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.testing.script_imports import load_script_module


def test_load_script_module_supports_sibling_import_without_sys_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_name = "_test_script_imports_sibling"
    monkeypatch.delitem(sys.modules, sibling_name, raising=False)
    monkeypatch.delitem(sys.modules, "_test_script_imports_parent", raising=False)
    (tmp_path / f"{sibling_name}.py").write_text("VALUE = 'loaded sibling'\n", encoding="utf-8")
    (tmp_path / "parent.py").write_text(
        f"import {sibling_name}\nVALUE = {sibling_name}.VALUE\n",
        encoding="utf-8",
    )
    before_path = list(sys.path)

    module = load_script_module("_test_script_imports_parent", tmp_path / "parent.py")

    assert module.VALUE == "loaded sibling"
    assert sys.path == before_path


def test_load_script_module_rejects_module_name_path_collision(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("VALUE = 'first'\n", encoding="utf-8")
    second.write_text("VALUE = 'second'\n", encoding="utf-8")

    module = load_script_module("_test_script_imports_collision", first)

    assert module.VALUE == "first"
    with pytest.raises(ImportError, match="already loaded"):
        load_script_module("_test_script_imports_collision", second)
