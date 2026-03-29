#!/usr/bin/env python3
"""
Manual bootstrap completeness check (not run in CI).

Run from repo root after you believe bootstrap is done:
  python3 scripts/check_bootstrap_complete.py

Exits 0 always; prints actionable instructions for any incomplete step.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

TEMPLATE_VAULT_DIR = "ProjectTemplate"
TEMPLATE_PKG_DIR = "project_template"
TEMPLATE_PYPROJECT_NAME = "project-template"


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    lines: list[str] = []

    vault = repo / "docs" / "01_Vault"
    template_vault = vault / TEMPLATE_VAULT_DIR
    if template_vault.is_dir():
        lines.append(
            f"- Vault folder still named `{TEMPLATE_VAULT_DIR}/`. "
            "Rename `docs/01_Vault/ProjectTemplate` → `docs/01_Vault/<YourProjectKey>` "
            "(see docs/00_Core/BOOTSTRAP_NEW_PROJECT.md)."
        )

    pkg = repo / "src" / TEMPLATE_PKG_DIR
    if pkg.is_dir():
        lines.append(
            f"- Python package still at `src/{TEMPLATE_PKG_DIR}/`. "
            "Rename to your package layout and update pyproject "
            "`[tool.setuptools.packages.find]` if needed."
        )

    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except OSError as e:
            lines.append(f"- Could not read pyproject.toml: {e}")
        else:
            try:
                data = tomllib.loads(text)
            except tomllib.TOMLDecodeError as e:
                lines.append(f"- `pyproject.toml` is not valid TOML: {e}")
            else:
                name = (data.get("project") or {}).get("name")
                if name == TEMPLATE_PYPROJECT_NAME:
                    lines.append(
                        f"- `pyproject.toml` project name is still `{TEMPLATE_PYPROJECT_NAME}`. "
                        "Set `[project].name` to your distribution name."
                    )

    if lines:
        print(
            "Bootstrap checklist — still looks like the template in these areas:\n", file=sys.stderr
        )
        for item in lines:
            print(item, file=sys.stderr)
        print(
            "\nWhen finished, re-run this script; it should print nothing.",
            file=sys.stderr,
        )
    else:
        print(
            "Bootstrap check: no template-default vault path, package dir, "
            "or pyproject name detected."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
