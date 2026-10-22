# OWNER: @agorokh
"""governance-hub#918: a handoff is one dated node; nothing here asks for a shared vault file.

Two handoffs that edit ``Current Focus.md``, ``Next Session Handoff.md`` or an ``_index.md``
conflict by construction (73 of 95 fleet handoff PRs did on 2026-10-18..19). This file pins the
three things in this repository that used to force that edit:

* instruction surfaces: no sentence tells a SAVE or handoff to update a shared file. The rule is
  a copy of governance-hub ``tests/test_skills_no_shared_vault_edits.py`` so this suite needs no
  hub checkout;
* ``scripts/check_vault_follow_up.sh``: one staged dated node is a vault follow-up, a code change
  without a note is still refused, and a shared file is no acknowledgement;
* session start: ``scripts/hook_session_start_handoff.py`` shows a new dated node without any
  shared file pointing at it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "check_vault_follow_up.sh"
READER = REPO_ROOT / "scripts" / "hook_session_start_handoff.py"

# --- the sentence rule (copy of governance-hub tests/test_skills_no_shared_vault_edits.py) ---

SHARED = re.compile(r"Current Focus|Next Session Handoff|_index\.md")
# Verbs that ask the reader to change a file. Reading verbs (open, read, start from, skim)
# are deliberately absent: LOAD may still read these files.
WRITE_VERB = re.compile(
    r"\b(update[sd]?|edit(?:s|ed)?|append(?:s|ed)?|prepend(?:s|ed)?|rewrit(?:e|es|ten)"
    r"|register(?:s|ed)?|reflect|ensure)\b",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(not|never|no longer)\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?;])\s+")


def instructed_shared_edits(text: str) -> list[str]:
    """Sentences that ask for a change to a shared vault file without negating it."""
    hits = []
    for line in text.splitlines():
        for sentence in _SENTENCE.split(line):
            if (
                SHARED.search(sentence)
                and WRITE_VERB.search(sentence)
                and not NEGATION.search(sentence)
            ):
                hits.append(sentence.strip())
    return hits


# Every file an agent reads as instructions, plus the reviewer pitfall the PR pre-check feeds.
INSTRUCTION_SURFACES = (
    "docs/00_Core/**/*.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
    ".claude/**/*.md",
    ".cursor/rules/**/*.mdc",
    ".cursor/rules/**/*.md",
    "docs/01_Vault/**/pitfalls/vault-path-integrity.md",
    # Agent-facing guides AGENTS.md lists as mandatory reading.
    "AGENT_CORE_PRINCIPLES.md",
    "docs/10_Development/**/*.md",
)

# Exact sentences that match the rule but are not a SAVE or handoff instruction. Keep this short:
# a new entry needs a reason a reviewer can check.
NOT_A_SAVE = {
    # One-time restructuring when a new project is bootstrapped from the template.
    (
        "docs/00_Core/BOOTSTRAP_NEW_PROJECT.md",
        "update `_index.md` files accordingly (see `00_Graph_Schema.md`).",
    ),
}


def _surfaces() -> list[Path]:
    found = {p for pattern in INSTRUCTION_SURFACES for p in REPO_ROOT.glob(pattern) if p.is_file()}
    return sorted(found)


@pytest.mark.parametrize(
    "removed",
    [
        # The instructions governance-hub#918 removed here; the rule must still catch each.
        "1. Update **`Next Session Handoff.md`**: resume pointer, what shipped, what remains, "
        "blockers.",
        "3. Update **`Current Focus.md`** if the active branch, PR, or focus changed.",
        "1. **Vault SAVE** — Update `Next Session Handoff.md`.",
        "**Session end (SAVE):** update `Next Session Handoff.md`;",
        "Update `Next Session Handoff.md` when leaving work incomplete.",
        "3. **Update `_index.md`** entries in the parent directory",
        "- Update vault **`Next Session Handoff.md`** when context will be needed later.",
        "- [ ] Vault handoff updated if the session changed focus or left loose ends "
        "(`Next Session Handoff.md`).",
    ],
)
def test_rule_catches_the_removed_instructions(removed: str) -> None:
    assert instructed_shared_edits(removed), removed


def test_rule_passes_negated_and_read_only_mentions() -> None:
    assert not instructed_shared_edits(
        "Do **not** edit `Current Focus.md`, `Next Session Handoff.md` or any `_index.md`."
    )
    assert not instructed_shared_edits("3. Open `docs/01_Vault/<key>/00_System/Current Focus.md`.")
    assert not instructed_shared_edits("2. Read vault `00_System/invariants/_index.md`")


def test_no_instruction_surface_asks_for_a_shared_vault_edit() -> None:
    surfaces = _surfaces()
    assert any(p.name == "SESSION_LIFECYCLE.md" for p in surfaces), "instruction surfaces not found"
    offenders = {}
    for path in surfaces:
        rel = path.relative_to(REPO_ROOT).as_posix()
        hits = [
            s
            for s in instructed_shared_edits(path.read_text(encoding="utf-8"))
            if (rel, s) not in NOT_A_SAVE
        ]
        if hits:
            offenders[rel] = hits
    assert offenders == {}


def test_not_a_save_entries_still_exist() -> None:
    """A stale exemption would silently allow a new sentence of the same text elsewhere."""
    for rel, sentence in NOT_A_SAVE:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert sentence in instructed_shared_edits(text), (rel, sentence)


# --- the commit hook: three cases -------------------------------------------------------------

NODE = "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-21-230000Z-post-merge-pr1-ab12.md"
_SKIP_NO_BASH = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    return tmp_path


def _stage(repo: Path, *paths: str) -> None:
    for rel in paths:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\ntype: handoff\nstatus: active\n---\n\nx\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", rel], check=True)


def _hook(repo: Path) -> subprocess.CompletedProcess[str]:
    """The invocation hook_bash_pre_tool.sh uses: no arguments, run inside the work tree."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    return subprocess.run(
        ["bash", str(HOOK)], cwd=repo, capture_output=True, text=True, env=env, timeout=15
    )


@_SKIP_NO_BASH
def test_hook_a_one_dated_node_alone_is_accepted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, NODE)
    r = _hook(repo)
    assert r.returncode == 0, r.stderr


@_SKIP_NO_BASH
def test_hook_b_code_change_without_a_note_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "scripts/new_hook.sh")
    r = _hook(repo)
    assert r.returncode == 1
    assert "without a vault follow-up" in r.stderr
    assert "handoffs/YYYY-MM-DD-HHMMSSZ-<slug>.md" in r.stderr
    for shared in ("Next Session Handoff.md", "Current Focus.md"):
        assert f"00_System/{shared}" not in r.stderr, "the hint must not ask for a shared file"


@_SKIP_NO_BASH
def test_hook_c_code_change_plus_one_dated_node_is_accepted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "scripts/new_hook.sh", NODE)
    r = _hook(repo)
    assert r.returncode == 0, r.stderr


@_SKIP_NO_BASH
@pytest.mark.parametrize(
    "not_an_ack",
    [
        "docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md",
        "docs/01_Vault/AcCopilotTrainer/00_System/Current Focus.md",
        "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/_index.md",
        "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/notes.md",
        "docs/01_Vault/AcCopilotTrainer/00_System/handoffs/2026-10-21-post-merge.md",
    ],
)
def test_hook_shared_file_or_undated_note_is_not_an_ack(tmp_path: Path, not_an_ack: str) -> None:
    repo = _repo(tmp_path)
    _stage(repo, "scripts/new_hook.sh", not_an_ack)
    assert _hook(repo).returncode == 1


# --- session start ----------------------------------------------------------------------------

SYSTEM = "docs/01_Vault/AcCopilotTrainer/00_System"


def _reader(root: Path) -> str:
    r = subprocess.run(
        [sys.executable, str(READER), str(root), SYSTEM],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_reader_shows_a_new_node_no_shared_file_points_at(tmp_path: Path) -> None:
    system = tmp_path / SYSTEM
    (system / "handoffs").mkdir(parents=True)
    (system / "Next Session Handoff.md").write_text("old monolith\n", encoding="utf-8")
    (system / "handoffs" / "_index.md").write_text("stale index\n", encoding="utf-8")
    older = system / "handoffs" / "2026-10-20-120000Z-older.md"
    older.write_text("older body\n", encoding="utf-8")
    newest = system / "handoffs" / "2026-10-21-230000Z-newest-abc123.md"
    newest.write_text("RESUME HERE\n", encoding="utf-8")
    out = _reader(tmp_path)
    assert newest.name in out and "RESUME HERE" in out
    assert "older body" not in out and older.name in out
    assert "old monolith" not in out and "stale index" not in out


def test_reader_falls_back_to_the_pointer_without_a_dated_node(tmp_path: Path) -> None:
    system = tmp_path / SYSTEM
    system.mkdir(parents=True)
    (system / "Next Session Handoff.md").write_text("pointer body\n", encoding="utf-8")
    assert "pointer body" in _reader(tmp_path)


def test_reader_never_fails_a_session(tmp_path: Path) -> None:
    assert "No handoff found." in _reader(tmp_path)


def test_session_start_runs_the_reader() -> None:
    for name in ("settings.base.json", "settings.json"):
        path = REPO_ROOT / ".claude" / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        commands = [
            hook.get("command", "")
            for entry in data.get("hooks", {}).get("SessionStart", [])
            for hook in entry.get("hooks", [])
        ]
        readers = [c for c in commands if "hook_session_start_handoff.py" in c]
        assert len(readers) == 1, name
        assert SYSTEM in readers[0], name
        assert not any("cat " in c and "Next Session Handoff" in c for c in commands), name
