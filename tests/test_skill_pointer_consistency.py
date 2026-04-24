"""Verify the `.cursor/skills/<name>/SKILL.md` pointer pattern stays consistent.

Each skill in `.cursor/skills/` is intentionally a short pointer file that
defers to the canonical `.claude/skills/<name>/SKILL.md` (see CodeRabbit
nit on PR #86 about dual-copy drift). This test ensures the pointer never
goes stale: every Cursor-side skill must (a) have a matching Claude-side
canonical file and (b) reference it in its body, so adding a new skill or
renaming one will fail CI rather than silently drift.

Skip semantics (gemini-code-assist + Qodo PR #86 follow-ups):

* Iterators return ``[]`` rather than raising when their directory is
  missing. This means a one-sided checkout (e.g. only `.claude/skills/`
  present) still fails the cross-direction tests, instead of silently
  skipping and hiding genuine drift.
* The whole suite only skips when **both** directories are missing, which
  is the only context (vendored use, partial checkout) where the test is
  not meaningful.
* When this repo's canonical-repo marker is present (`AGENTS.md` at
  ``REPO_ROOT``), :func:`test_skill_dirs_present_in_canonical_repo`
  additionally asserts both directories exist, so the canonical CI run
  cannot accidentally skip drift detection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CURSOR_SKILLS = REPO_ROOT / ".cursor" / "skills"
CLAUDE_SKILLS = REPO_ROOT / ".claude" / "skills"
CANONICAL_REPO_MARKER = REPO_ROOT / "AGENTS.md"


def _maybe_skip_when_no_skill_trees() -> None:
    """Skip only when **both** skill trees are missing.

    A one-sided checkout (only `.cursor/skills/` or only `.claude/skills/`)
    must NOT skip, otherwise drift is hidden: the cross-direction tests
    rely on the empty-iterator behaviour to surface mismatches.
    """
    if not CURSOR_SKILLS.is_dir() and not CLAUDE_SKILLS.is_dir():
        pytest.skip(
            "Neither `.cursor/skills/` nor `.claude/skills/` is present; "
            "skill pointer consistency checks are not meaningful in this "
            "context (partial checkout / vendored use)."
        )


def _cursor_skill_dirs() -> list[Path]:
    """Return sorted Cursor-side skill dirs, or ``[]`` if the tree is absent.

    Returning an empty list (instead of raising ``FileNotFoundError``) lets
    the cross-direction test still run when only one side of the dual-copy
    pattern is present, surfacing genuine drift.
    """
    if not CURSOR_SKILLS.is_dir():
        return []
    return sorted(p for p in CURSOR_SKILLS.iterdir() if p.is_dir())


def _claude_skill_dirs() -> list[Path]:
    """Return sorted Claude-side skill dirs, or ``[]`` if the tree is absent."""
    if not CLAUDE_SKILLS.is_dir():
        return []
    return sorted(p for p in CLAUDE_SKILLS.iterdir() if p.is_dir())


def test_skill_dirs_present_in_canonical_repo() -> None:
    """In the canonical template-repo (signalled by `AGENTS.md`), both
    `.cursor/skills/` and `.claude/skills/` must exist; otherwise the
    cross-direction drift tests would silently skip in CI.

    Vendored / partial checkouts will not have ``AGENTS.md`` and are
    therefore unaffected by this check.
    """
    if not CANONICAL_REPO_MARKER.is_file():
        pytest.skip(
            "Not running in the canonical template-repo "
            f"(no {CANONICAL_REPO_MARKER.name} at REPO_ROOT)."
        )
    missing = [str(p) for p in (CURSOR_SKILLS, CLAUDE_SKILLS) if not p.is_dir()]
    assert not missing, (
        "The canonical template-repo must ship both `.cursor/skills/` and "
        f"`.claude/skills/`, but these are missing: {missing}. CI was about "
        "to skip the dual-copy drift tests, which would hide skill drift."
    )


def test_every_cursor_skill_has_a_claude_canonical_file() -> None:
    """Each `.cursor/skills/<name>/SKILL.md` must have a Claude canonical."""
    _maybe_skip_when_no_skill_trees()
    missing: list[str] = []
    for skill_dir in _cursor_skill_dirs():
        canonical = CLAUDE_SKILLS / skill_dir.name / "SKILL.md"
        if not canonical.is_file():
            missing.append(skill_dir.name)
    assert not missing, (
        ".cursor/skills/<name>/SKILL.md must always have a matching "
        f".claude/skills/<name>/SKILL.md (drift detected for: {missing}). "
        "Either add the canonical Claude copy or remove the pointer."
    )


def test_every_cursor_skill_pointer_references_its_claude_canonical() -> None:
    """Each Cursor pointer body must reference its `.claude/skills/<name>/SKILL.md`."""
    _maybe_skip_when_no_skill_trees()
    drifted: list[str] = []
    for skill_dir in _cursor_skill_dirs():
        pointer = skill_dir / "SKILL.md"
        if not pointer.is_file():
            drifted.append(f"{skill_dir.name} (no SKILL.md)")
            continue
        body = pointer.read_text(encoding="utf-8")
        expected_ref = f".claude/skills/{skill_dir.name}/SKILL.md"
        if expected_ref not in body:
            drifted.append(skill_dir.name)
    assert not drifted, (
        "Each .cursor/skills/<name>/SKILL.md must reference its canonical "
        f".claude/skills/<name>/SKILL.md (drift in: {drifted}). The pointer "
        "pattern keeps Cursor and Claude aligned without duplicating content."
    )


def test_every_claude_skill_has_a_cursor_pointer() -> None:
    """Reverse direction: a new canonical skill in `.claude/skills/` must
    ship with its `.cursor/skills/` pointer in the same change set,
    otherwise Cursor users silently lose access to the skill."""
    _maybe_skip_when_no_skill_trees()
    missing: list[str] = []
    for skill_dir in _claude_skill_dirs():
        pointer = CURSOR_SKILLS / skill_dir.name / "SKILL.md"
        if not pointer.is_file():
            missing.append(skill_dir.name)
    assert not missing, (
        ".claude/skills/<name>/SKILL.md must always have a matching "
        f".cursor/skills/<name>/SKILL.md pointer (drift detected for: {missing}). "
        "Add the Cursor pointer (with a body that references "
        "`.claude/skills/<name>/SKILL.md`) when introducing a new canonical skill."
    )
