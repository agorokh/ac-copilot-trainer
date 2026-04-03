#!/usr/bin/env python3
"""
Static analysis: detect usage of non-existent CSP Lua APIs in .lua source files.

Maintains an explicit BLOCKLIST of APIs that are known NOT to exist in the
production CSP SDK, and an ALLOWLIST of confirmed-working render/physics/ui calls.

Exit 1 if any blocklisted symbol is found, or if an unknown render.* call is
found while --strict is set. Unknown render.* calls are warnings by default
(exit 0).

Also checks for common unit-confusion bugs (seconds vs milliseconds).

String literals are stripped with simple regexes before scanning; Lua long
strings ([[...]]) and escaped quotes inside strings are not fully removed and
could theoretically cause false positives — acceptable for this lint.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# BLOCKLIST: APIs that DO NOT EXIST in production CSP.
# Each entry is a regex pattern matched against Lua source lines.
# ──────────────────────────────────────────────────────────────────────
BLOCKLISTED_APIS: list[tuple[str, str]] = [
    # OpenGL immediate-mode family — never existed in CSP Lua
    (r"\brender\.glBegin\b", "render.glBegin does not exist in CSP Lua SDK"),
    (r"\brender\.glEnd\b", "render.glEnd does not exist in CSP Lua SDK"),
    (r"\brender\.glVertex\b", "render.glVertex does not exist in CSP Lua SDK"),
    (r"\brender\.glSetColor\b", "render.glSetColor does not exist in CSP Lua SDK"),
    (r"\brender\.glNormal\b", "render.glNormal does not exist in CSP Lua SDK"),
    (r"\brender\.glTexCoord\b", "render.glTexCoord does not exist in CSP Lua SDK"),
    # render.quad — not a real CSP function
    (r"\brender\.quad\b", "render.quad does not exist in CSP Lua SDK"),
    # render.triangle — not a real CSP function
    (r"\brender\.triangle\b", "render.triangle does not exist in CSP Lua SDK"),
    # render.line — confused with render.debugLine
    (r"\brender\.line\b(?!Strip)", "render.line does not exist; use render.debugLine"),
    # GLPrimitiveType enum — does not exist in CSP
    (
        r"\brender\.GLPrimitiveType\b",
        "render.GLPrimitiveType enum does not exist in CSP Lua SDK",
    ),
]

# ──────────────────────────────────────────────────────────────────────
# ALLOWLIST: render.* calls confirmed to exist in production CSP.
# Used to flag unknown render.* calls as warnings.
# ──────────────────────────────────────────────────────────────────────
ALLOWED_RENDER_CALLS: set[str] = {
    # Confirmed CSP render namespace functions
    "render.mesh",
    "render.shaderedQuad",
    "render.debugLine",
    "render.debugSphere",
    "render.debugCross",
    "render.debugPoint",
    "render.debugPlane",
    "render.debugArrow",
    "render.debugText",
    "render.circle",
    "render.setDepthMode",
    "render.setBlendMode",
    "render.setCullMode",
    "render.createMesh",
    "render.fullscreenPass",
    "render.measure",
    "render.setShader",
    "render.billboard",
    # Enum/constant namespaces (not calls, but accessed via render.*)
    "render.DepthMode",
    "render.BlendMode",
    "render.CullMode",
    "render.MeshFlags",
    "render.ShaderedQuadFlags",
    "render.TextureFormat",
}

# ──────────────────────────────────────────────────────────────────────
# Timer / unit confusion checks
# ──────────────────────────────────────────────────────────────────────
UNIT_CONFUSION_PATTERNS: list[tuple[str, str]] = [
    # Heuristic: tiny literals often mean "seconds" while author assumed ms (or vice versa).
    (
        r"\bsim\.time\s*[<>]=?\s*\d{1,3}(?:\.\d+)?\s*(?:--.*seconds)?",
        "sim.time compared to a small literal — confirm units match CSP ac.StateSim (seconds)",
    ),
]

# Pattern to extract render.XXXX calls from Lua
RENDER_CALL_RE = re.compile(r"\brender\.([A-Za-z_]\w*)\b")


def scan_file(path: Path, strict: bool) -> tuple[list[str], list[str]]:
    """Scan a single .lua file. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append(f"{path}: could not read: {exc}")
        return errors, warnings

    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip pure comments
        if stripped.startswith("--"):
            continue

        # Strip string literals first so `--` inside quotes does not truncate the line.
        code = line
        code = re.sub(r'"[^"]*"', '""', code)
        code = re.sub(r"'[^']*'", "''", code)
        # Strip trailing Lua comment (approximation; long strings [[ ]] still not handled).
        code = code.split("--")[0] if "--" in code else code

        # ── Blocklist check ──
        for pattern, message in BLOCKLISTED_APIS:
            # Check in code portion AND in type-checking guards like `type(render.glBegin)`
            if re.search(pattern, code):
                errors.append(f"{path}:{line_no}: BLOCKED — {message}\n  {stripped}")

        # ── Unknown render.* check ──
        for match in RENDER_CALL_RE.finditer(code):
            full_name = f"render.{match.group(1)}"
            if full_name not in ALLOWED_RENDER_CALLS:
                # Check it's not already caught by blocklist
                already_blocked = any(re.search(pat, full_name) for pat, _ in BLOCKLISTED_APIS)
                if not already_blocked:
                    msg = (
                        f"{path}:{line_no}: UNKNOWN render API — "
                        f"'{full_name}' is not in the confirmed CSP allowlist"
                    )
                    if strict:
                        errors.append(f"{msg}\n  {stripped}")
                    else:
                        warnings.append(f"{msg}\n  {stripped}")

        # ── Unit confusion check ──
        for pattern, message in UNIT_CONFUSION_PATTERNS:
            if re.search(pattern, code):
                warnings.append(f"{path}:{line_no}: UNIT WARNING — {message}\n  {stripped}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CSP Lua files for non-existent API usage")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat unknown render.* calls as errors (not just warnings)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["src"],
        help="Directories or files to scan (default: src)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent

    lua_files: list[Path] = []
    for p in args.paths:
        target = repo_root / p
        if target.is_file() and target.suffix == ".lua":
            lua_files.append(target)
        elif target.is_dir():
            lua_files.extend(sorted(target.rglob("*.lua")))

    if not lua_files:
        print(
            "No .lua files found to scan (check paths / working directory).",
            file=sys.stderr,
        )
        return 1

    all_errors: list[str] = []
    all_warnings: list[str] = []

    for lua_file in lua_files:
        errs, warns = scan_file(lua_file, args.strict)
        all_errors.extend(errs)
        all_warnings.extend(warns)

    # Print results
    if all_warnings:
        print("=== CSP API WARNINGS ===", file=sys.stderr)
        for w in all_warnings:
            print(f"  {w}", file=sys.stderr)
        print(file=sys.stderr)

    if all_errors:
        print("=== CSP API ERRORS (blocklisted APIs found) ===", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        print(
            f"\n{len(all_errors)} error(s) found. These APIs do not exist in CSP Lua SDK.",
            file=sys.stderr,
        )
        return 1

    print(
        f"CSP API check passed: {len(lua_files)} file(s) scanned, {len(all_warnings)} warning(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
