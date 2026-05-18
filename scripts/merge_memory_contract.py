#!/usr/bin/env python3
"""Idempotently re-render the memory contract block into target files.

Lives at the **hub** (template-repo). Child repos pull the script via
``copier update`` (or manual sync) and run it from their ``Makefile`` so the
short memory-contract block in their ``AGENTS.md`` / ``.claude/agents/*.md``
stays in lock-step with the canonical contract at
``docs/00_Core/MEMORY_CONTRACT.md`` **without overwriting per-repo
customizations** anywhere else in those files.

Mechanism: marker-delimited sections.

::

    <!-- memory-contract:start -->
    ...auto-rendered block (do not edit by hand)...
    <!-- memory-contract:end -->

If the markers already exist in a target file, the content between them is
replaced. If they do not exist, the block is **appended** to the end of the
file with a leading newline. Everything outside the markers is preserved
byte-for-byte.

Why a separate script (vs Copier's own templating)?

* Children may rename ``ProjectTemplate`` to a project-specific vault key.
  The marker block does not embed that key — it links the canonical contract
  doc only — so the same block renders identically in every child.
* Children may have customized large stretches of ``AGENTS.md`` or
  ``.claude/agents/*.md`` that Copier would clobber on update unless heavily
  templated. The marker approach keeps the customizations intact.

Usage::

    python3 scripts/merge_memory_contract.py            # render in-place
    python3 scripts/merge_memory_contract.py --check    # exit 1 if any target would change
    python3 scripts/merge_memory_contract.py --diff     # print what would change
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MARKER_START = "<!-- memory-contract:start -->"
MARKER_END = "<!-- memory-contract:end -->"

# Default targets (relative to repo root). Each must already exist; the script
# does not create new files. Missing targets are reported but not fatal — a
# given child may not have a `learner.md` agent, for example.
DEFAULT_TARGETS: tuple[str, ...] = (
    "AGENTS.md",
    ".claude/agents/issue-driven-coding-orchestrator.md",
    ".claude/agents/pr-resolution-follow-up.md",
    ".claude/agents/post-merge-steward.md",
    ".claude/agents/dependency-review.md",
    ".claude/agents/learner.md",
)

INVARIANT_FILENAME = "memory-three-tiers.md"


def _link_prefix_for(rel_target: str) -> str:
    """Agent files live under ``.claude/agents/`` — links need ``../../``."""
    if rel_target.startswith(".claude/agents/"):
        return "../../"
    return ""


def _vault_invariant_link(root: Path, link_prefix: str) -> str:
    """Link to memory-three-tiers using this repo's vault folder name.

    Children rename ``ProjectTemplate`` to their project key on bootstrap —
    we look up whatever vault folder actually contains the invariant rather
    than hardcoding ``ProjectTemplate``.
    """
    vault_dir = root / "docs" / "01_Vault"
    if vault_dir.is_dir():
        for child in sorted(vault_dir.iterdir()):
            inv = child / "00_System" / "invariants" / INVARIANT_FILENAME
            if child.is_dir() and inv.is_file():
                rel = inv.relative_to(root).as_posix()
                return f"[`{INVARIANT_FILENAME}`]({link_prefix}{rel})"
    return (
        f"[`{INVARIANT_FILENAME}`]"
        f"({link_prefix}docs/01_Vault/<your-vault>/00_System/invariants/{INVARIANT_FILENAME})"
    )


def _block_body_agent_pointer(root: Path, *, link_prefix: str) -> str:
    """Pointer stub for ``.claude/agents/*.md`` (rules live in-procedure above)."""
    p = link_prefix
    invariant_link = _vault_invariant_link(root, p)
    return (
        "\n"
        "## Memory contract (pointer)\n"
        "\n"
        "The substantive memory rules for this agent live in the file's "
        "**`## Tier-3 Substrate Query (mandatory first step)`** section above. "
        "They are placed before the procedure on purpose, so the agent reads them "
        "in execution order.\n"
        "\n"
        "References:\n"
        "\n"
        "- Canonical contract: "
        f"[`docs/00_Core/MEMORY_CONTRACT.md`]({p}docs/00_Core/MEMORY_CONTRACT.md).\n"
        f"- Canonical invariant: {invariant_link}.\n"
        "- Runtime enforcement: `scripts/hook_memory_gate.py` (PreToolUse gate "
        "blocks code-path edits without a fresh, file-relevant Tier-3 stamp) + "
        "`scripts/hook_stop_drift_audit.py` (Stop hook scores conversational "
        "drift; next session's prefetch warns at turn-1 when drift_score is high).\n"
        "- Kill switch: `CLAUDE_MEMORY_GATE=0` bypasses the gate; surface why in "
        "the vault SAVE so the next session can correct.\n"
        "\n"
        "Originating postmortem: "
        "[template-repo#115](https://github.com/agorokh/template-repo/issues/115).\n"
    )


def _block_body_agents_md(root: Path, *, link_prefix: str) -> str:
    """Pointer stub for root ``AGENTS.md`` (no in-file Tier-3 section)."""
    p = link_prefix
    invariant_link = _vault_invariant_link(root, p)
    return (
        "\n"
        "## Memory contract (pointer)\n"
        "\n"
        "Per-agent substantive rules live in `.claude/agents/*.md` — each file "
        "opens with **`## Tier-3 Substrate Query (mandatory first step)`** before "
        "its procedure. The **Memory-first** section at the top of this file "
        "summarizes the unified requirement for all named agents.\n"
        "\n"
        "References:\n"
        "\n"
        "- Canonical contract: "
        f"[`docs/00_Core/MEMORY_CONTRACT.md`]({p}docs/00_Core/MEMORY_CONTRACT.md).\n"
        f"- Canonical invariant: {invariant_link}.\n"
        "- Runtime enforcement: `scripts/hook_memory_gate.py` + "
        "`scripts/hook_stop_drift_audit.py` (see contract doc).\n"
        "- Kill switch: `CLAUDE_MEMORY_GATE=0` bypasses the gate; surface why in "
        "the vault SAVE so the next session can correct.\n"
        "\n"
        "Originating postmortem: "
        "[template-repo#115](https://github.com/agorokh/template-repo/issues/115).\n"
    )


def _block_body(root: Path, *, link_prefix: str, rel_target: str) -> str:
    """Render the memory-contract marker block for a target file."""
    if rel_target == "AGENTS.md":
        return _block_body_agents_md(root, link_prefix=link_prefix)
    return _block_body_agent_pointer(root, link_prefix=link_prefix)


def _wrapped_block(root: Path, rel_target: str) -> str:
    do_not_edit = (
        "<!-- DO NOT EDIT BY HAND. Re-render with: python3 scripts/merge_memory_contract.py -->"
    )
    prefix = _link_prefix_for(rel_target)
    return (
        f"{MARKER_START}\n{do_not_edit}\n"
        f"{_block_body(root, link_prefix=prefix, rel_target=rel_target)}\n"
        f"{MARKER_END}\n"
    )


def _render(text: str, *, root: Path, rel_target: str) -> str:
    """Return ``text`` with the contract block in canonical position.

    * Existing markers → in-place replacement.
    * No markers → append with one blank line before the start marker.
    """
    block = _wrapped_block(root, rel_target)
    start_idx = text.find(MARKER_START)
    end_idx = text.find(MARKER_END)
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        # Replace from MARKER_START line through the end of MARKER_END line.
        # Be tolerant of trailing newline after the end marker.
        after_end = end_idx + len(MARKER_END)
        if after_end < len(text) and text[after_end] == "\n":
            after_end += 1
        new_text = text[:start_idx] + block + text[after_end:]
        # Normalize at most one trailing newline.
        return new_text.rstrip("\n") + "\n"
    # Append (with separator if file doesn't already end in blank line).
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return (text + sep + block).rstrip("\n") + "\n"


def _process(path: Path, *, root: Path, check: bool, diff: bool) -> tuple[bool, str | None]:
    """Render contract block in ``path``. Returns (changed, message)."""
    if not path.is_file():
        return False, f"skip (missing): {path}"
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"read error: {path}: {e}"
    rel_target = str(path.relative_to(root))
    updated = _render(original, root=root, rel_target=rel_target)
    if updated == original:
        return False, None
    if diff:
        sys.stdout.write(f"--- {path}\n+++ {path} (rendered)\n")
        sys.stdout.write(
            "(content differs by memory-contract block; run without --diff/--check to apply)\n"
        )
    if not check and not diff:
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as e:
            return False, f"write error: {path}: {e}"
    return True, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repo root (default: derived from script location).",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="Override default targets. Repeat for multiple. Paths are repo-relative.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any target would change; do not modify files.",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Print which targets would change (without applying).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    targets = args.target or list(DEFAULT_TARGETS)

    changes = 0
    for rel in targets:
        path = root / rel
        changed, message = _process(path, root=root, check=args.check, diff=args.diff)
        if message:
            print(message)
        if changed:
            changes += 1
            print(f"{'WOULD CHANGE' if args.check or args.diff else 'CHANGED'}: {rel}")

    if args.check:
        if changes:
            print(
                f"\nmerge_memory_contract: {changes} file(s) out of sync — "
                "run without --check to render"
            )
            return 1
        print("merge_memory_contract: OK (in sync)")
        return 0
    print(f"merge_memory_contract: rendered into {changes} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
