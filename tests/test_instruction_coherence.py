"""Instruction-surface coherence guards — agent-factory#350 audit (Council-reviewed 2026-06-04).

Goal: an autonomous coding agent must not be able to read CONTRADICTORY governance instructions.
These are CURATED phrase/anchor checks (NOT AI-complete NL contradiction detection, per the Council)
plus negative controls that prove each guard fires. Historical trees (`01_Decisions/`,
`02_Investigations/`) are excluded from phrase scans — they legitimately narrate old decisions.

Guards:
  1 polarity            — no surface says local hooks are advisory/optional or server is primary
  2 headless-claim      — codex exec / agy --print never described as proven local enforcement
  3 hub-status          — governance-hub never described as an active local-gate gap
  4 workspace-provision — MEMORY_CONTRACT forbids faking a stamp from a neighboring workspace
  5 graphql-threads     — resolve-pr mandates GraphQL reviewThreads (REST insufficient)
  6 protected-data      — resolve-pr requires snapshot-before + STOP on missing protected path
  7 cross-repo-gate     — gate defines pilot = PRE-MERGE PR-branch CI; no blind fleet sweeps
  8 precedence          — INSTRUCTION_SURFACE_PRECEDENCE.md declares the reading order + polarity
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HISTORICAL = ("/01_Decisions/", "/02_Investigations/")
LIVE_GLOBS = (
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "README.md",
    "AGENT_CORE_PRINCIPLES.md",
    "docs/00_Core/*.md",
    "docs/01_Vault/*/00_System/*.md",
    "docs/01_Vault/*/00_System/invariants/*.md",
    ".claude/agents/*.md",
    ".claude/skills/*/SKILL.md",
    ".claude/rules/*.md",
    ".cursor/skills/*/SKILL.md",
    ".codex/skills/*/SKILL.md",
    ".agents/skills/*/SKILL.md",
    ".cursor/rules/*.mdc",
)


def _live_files():
    out = set()
    for g in LIVE_GLOBS:
        for p in REPO.glob(g):
            if p.is_file() and not any(h in p.as_posix() for h in HISTORICAL):
                out.add(p)
    return sorted(out)


def _scan(patterns, allow=None):
    """Return [rel:line: text] for lines matching any banned pattern and NOT the allow pattern."""
    hits = []
    for p in _live_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(rx.search(line) for rx in patterns) and not (allow and allow.search(line)):
                hits.append(f"{p.relative_to(REPO)}:{i}: {line.strip()[:110]}")
    return hits


def _line_flags(line, patterns, allow=None):
    return any(rx.search(line) for rx in patterns) and not (allow and allow.search(line))


# ---- 1. polarity ---------------------------------------------------------------------------
POLARITY_BANNED = [
    re.compile(r"client hooks are advisory", re.I),
    re.compile(r"\b(local|client)\b.{0,30}hooks? (are|is) (optional|advisory|just ux)", re.I),
    re.compile(r"real\s+enforcement is the server", re.I),
    re.compile(r"server[-\s]?side .{0,25}\b(real|primary)\b enforcement", re.I),
    re.compile(r"server (rulesets?|side) (are|is) (the )?primary", re.I),
]
POLARITY_ALLOW = re.compile(r"\bnot\b|must never|forbidden|never (say|state|imply)|BACKSTOP", re.I)


def test_polarity_local_primary_server_backstop() -> None:
    hits = _scan(POLARITY_BANNED, POLARITY_ALLOW)
    assert not hits, (
        "Enforcement-polarity inversion (local hooks are PRIMARY; server is BACKSTOP):\n  - "
        + "\n  - ".join(hits)
    )


# ---- 2. headless-claim ---------------------------------------------------------------------
HEADLESS_BANNED = [
    re.compile(
        r"(codex exec|agy --print|headless).{0,60}(proven|live enforcement|enforces|enforced)",
        re.I,
    )
]
HEADLESS_ALLOW = re.compile(
    r"accepted|registered|debt|not proven|backstop|cannot|do not|no (per-repo )?hook|fire no hook"
    r"|contract|blocked",
    re.I,
)


def test_headless_not_described_as_proven_enforcement() -> None:
    hits = _scan(HEADLESS_BANNED, HEADLESS_ALLOW)
    assert not hits, (
        "Headless mode described as proven local-hook enforcement (it is accepted debt):\n  - "
        + "\n  - ".join(hits)
    )


# ---- 3. hub-status -------------------------------------------------------------------------
HUB_BANNED = [
    re.compile(
        r"(governance-hub|the hub).{0,60}(intentionally unsupported|no local (gate|first-try)|active conceptual gap|server-belt-only)",  # noqa: E501
        re.I,
    )
]
HUB_ALLOW = re.compile(r"was|were|resolved|closed|no longer|self-gat|REMOV|SUPERSED|#361|#15", re.I)


def test_hub_not_described_as_active_gap() -> None:
    hits = _scan(HUB_BANNED, HUB_ALLOW)
    assert not hits, (
        "governance-hub described as an active local-gate gap (it self-gates now, #361):\n  - "
        + "\n  - ".join(hits)
    )


# ---- 4. workspace-provisioning -------------------------------------------------------------
def test_memory_contract_forbids_neighbor_workspace_faking() -> None:
    # The anti-faking rule may live in MEMORY_CONTRACT.md (canonical) OR the precedence doc (the
    # portable copy propagated to spokes). Pass if either carries it.
    texts = ""
    for rel in (
        "docs/00_Core/MEMORY_CONTRACT.md",
        "docs/00_Core/INSTRUCTION_SURFACE_PRECEDENCE.md",
    ):
        p = REPO / rel
        if p.is_file():
            texts += p.read_text(encoding="utf-8").lower()
    assert "neighboring" in texts and "manufacture a stamp" in texts, (
        "MEMORY_CONTRACT.md or the precedence doc must forbid querying a neighboring workspace "
        "to fake a stamp (R6)."
    )


# ---- 5. graphql reviewThreads (workflow-specific: skip where resolve-pr is not present) -----
_RESOLVE_PR = REPO / ".claude/skills/resolve-pr/SKILL.md"


def test_resolve_pr_mandates_graphql_reviewthreads() -> None:
    if not _RESOLVE_PR.is_file():
        pytest.skip("no resolve-pr skill in this repo")
    t = _RESOLVE_PR.read_text(encoding="utf-8")
    assert "reviewThreads" in t and "REST alone" in t, (
        "resolve-pr must mandate GraphQL reviewThreads and state REST is insufficient."
    )


# ---- 6. protected-data (only where the repo has protected data: a `make snapshot` target) ----
def _has_protected_data() -> bool:
    mk = REPO / "Makefile"
    return (
        mk.is_file()
        and re.search(r"^snapshot\s*:", mk.read_text(encoding="utf-8"), re.M) is not None
    )


def test_resolve_pr_requires_snapshot_and_stop_on_missing() -> None:
    if not _RESOLVE_PR.is_file():
        pytest.skip("no resolve-pr skill in this repo")
    if not _has_protected_data():
        pytest.skip("repo declares no protected data (no `make snapshot` target)")
    t = _RESOLVE_PR.read_text(encoding="utf-8").lower()
    assert "snapshot" in t and "protected" in t and ("stop" in t and "missing" in t), (
        "resolve-pr must require snapshot-before + STOP on a missing protected path."
    )


# ---- 7. cross-repo change gate -------------------------------------------------------------
SWEEP_BANNED = [
    re.compile(r"(sweep (all|the fleet|every repo))|fleet-wide (rewrite|cleanup|fix)", re.I)
]
SWEEP_ALLOW = re.compile(
    r"\bnot\b|never|without|under the gate|requires the gate|no (fleet|blind)|do not", re.I
)


def test_cross_repo_gate_defined_and_no_blind_sweep() -> None:
    # The sweep phrase-scan runs in EVERY repo. The invariant-content checks run only where the
    # cross-repo-change-gate invariant exists (control plane); globbed by vault key for portability.
    invs = list(REPO.glob("docs/01_Vault/*/00_System/invariants/cross-repo-change-gate.md"))
    if invs:
        inv = invs[0].read_text(encoding="utf-8")
        assert re.search(r"pre-merge", inv, re.I) and re.search(r"PR[-\s]?branch", inv, re.I), (
            "cross-repo gate must define pilot CI-green as PRE-MERGE PR-branch CI (R11)."
        )
        for kw in ("inventory", "rollback", "council", "pilot"):
            assert kw.lower() in inv.lower(), f"cross-repo gate missing required element: {kw}"
    hits = _scan(SWEEP_BANNED, SWEEP_ALLOW)
    assert not hits, (
        "A live surface encourages a blind fleet sweep without the change gate:\n  - "
        + "\n  - ".join(hits)
    )


# ---- 8. precedence -------------------------------------------------------------------------
def test_precedence_declaration_exists() -> None:
    p = REPO / "docs/00_Core/INSTRUCTION_SURFACE_PRECEDENCE.md"
    assert p.is_file(), "INSTRUCTION_SURFACE_PRECEDENCE.md must exist (declares the reading order)."
    t = p.read_text(encoding="utf-8")
    assert "Reading order" in t and "Active handoff" in t and "PRIMARY" in t and "BACKSTOP" in t, (
        "precedence doc must declare the reading order + the local-PRIMARY/server-BACKSTOP polarity."  # noqa: E501
    )


# ---- 9. dangling references: a referenced skill/hook must EXIST (referenced != exists) ------
_SKILL_REF = re.compile(r"\.claude/skills/([a-z0-9][a-z0-9_-]+)")
_HOOK_REF = re.compile(r"scripts/(hook_[a-z0-9_]+\.py)")
# exclude: removal/historical context, legacy aliases, and template/shell variables (e.g. ${CONCEPT})  # noqa: E501
_REF_ALLOW = re.compile(
    r"REMOV|DELET|deleted|removed|slim-down|deprecat|no longer|SUPERSED|legacy|alias|former"
    r"|\$\{|\$[A-Z]",
    re.I,
)


# hub-owned helpers are resolved from the installed hub (~/.fleet-governance), not vendored per repo —  # noqa: E501
# referencing them is not "dangling".
_HUB_HELPERS = {"hook_memory_manifest.py", "hook_repo_root.py"}


_AGENT_REF = re.compile(r"\.claude/agents/([a-z0-9][a-z0-9_-]+)")
_SUBAGENT = re.compile(r"subagent_type[\"'\s=:]+([a-z0-9_-]+)", re.I)
_CURSOR_BUILTINS = {"generalpurpose", "explore", "shell", "best-of-n-runner"}


def _existing_skills():
    d = REPO / ".claude/skills"
    return {p.name for p in d.glob("*") if p.is_dir()} if d.is_dir() else set()


def _existing_agents():
    d = REPO / ".claude/agents"
    return {p.stem for p in d.glob("*.md")} if d.is_dir() else set()


def _dangling_surfaces():
    # ACTIONABLE instruction surfaces an agent follows as current (NOT the vault, which accumulates
    # historical handoff file-lists). This is the post-merge "skill that does not exist" class.
    out = []
    for f in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        if (REPO / f).is_file():
            out.append(REPO / f)
    for g in (
        "docs/00_Core/*.md",
        ".claude/skills/*/SKILL.md",
        ".claude/rules/*.md",
        ".claude/agents/*.md",
        ".cursor/skills/*/SKILL.md",
        ".codex/skills/*/SKILL.md",
        ".agents/skills/*/SKILL.md",
        ".cursor/rules/*.mdc",
    ):
        out += [p for p in REPO.glob(g) if p.is_file()]
    return sorted(set(out))


def _dangling_refs():
    skills = _existing_skills()
    agents = _existing_agents()
    bad = []
    for p in _dangling_surfaces():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _REF_ALLOW.search(line):
                continue
            for sk in _SKILL_REF.findall(line):
                if sk not in skills:
                    bad.append(f"{p.relative_to(REPO)}:{i}: skill '{sk}' referenced but missing")
            for hk in _HOOK_REF.findall(line):
                if hk not in _HUB_HELPERS and not (REPO / "scripts" / hk).is_file():
                    bad.append(
                        f"{p.relative_to(REPO)}:{i}: hook 'scripts/{hk}' referenced but missing"
                    )
            for ag in _AGENT_REF.findall(line):
                if ag not in agents:
                    bad.append(f"{p.relative_to(REPO)}:{i}: agent '{ag}' referenced but missing")
            # github-issue-creator documents a custom multi-agent design (operator-provided
            # sub-agents); its subagent_type names are a separate domain concern, not core drift.
            ghic = "github-issue-creator" in p.as_posix()
            for st in _SUBAGENT.findall(line):
                if (
                    not ghic
                    and st.lower() not in _CURSOR_BUILTINS
                    and st not in agents
                    and st not in skills
                ):
                    bad.append(
                        f"{p.relative_to(REPO)}:{i}: subagent_type '{st}' not an agent/builtin"
                    )
    return bad


def test_no_dangling_skill_or_hook_references() -> None:
    bad = _dangling_refs()
    assert not bad, (
        "Dangling references — a skill/hook is NAMED as current in a live\n"
        "instruction surface but does NOT exist here (the post-merge 'skill\n"
        "that does not exist' class). Fix the reference or mark it removed:\n  - "
        + "\n  - ".join(bad)
    )


# ---- 10. deprecated-name guard (map-driven): REMOVED names must not appear live (bare/NL) ----
_MAP = REPO / "docs/00_Core/deprecation_map.yml"


def _removed_names():
    if not _MAP.is_file():
        return []
    out, txt = [], _MAP.read_text(encoding="utf-8")
    # crude block parse: collect `old:` where the same block has `status: REMOVED`
    blocks = re.split(r"\n\s*-\s+old:", txt)
    for b in blocks[1:]:
        name = b.splitlines()[0].strip()
        if "REMOVED" in b.split("status:", 1)[-1].splitlines()[0] if "status:" in b else False:
            out.append(name)
    return out


def _deprecated_surfaces():
    # actionable surfaces; exclude the map + guard test files (which legitimately name them)
    skip = ("deprecation_map.yml", "test_instruction_coherence.py", "test_no_stale_hook_refs.py")
    return [p for p in _dangling_surfaces() if not any(k in p.name for k in skip)]


def test_no_deprecated_name_as_current() -> None:
    names = _removed_names()
    if not names:
        pytest.skip("no deprecation map in this repo")
    bad = []
    for p in _deprecated_surfaces():
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if _REF_ALLOW.search(line):
                continue
            for nm in names:
                if nm in line:
                    bad.append(f"{p.relative_to(REPO)}:{i}: deprecated name '{nm}' used as current")
    assert not bad, (
        "Deprecated agent/hook names used as CURRENT in a live surface (deprecation_map.yml). "
        "Use the successor skill or mark removed/historical:\n  - " + "\n  - ".join(bad)
    )


# ---- 11. undeclared-memory-alias guard: obsidian + vault memory cannot both ship undeclared ----
def test_no_undeclared_memory_alias() -> None:
    sk = _existing_skills()
    if not ("obsidian-memory" in sk and "vault-memory" in sk):
        return  # no collision
    policy = _MAP.read_text(encoding="utf-8") if _MAP.is_file() else ""
    if "vault_memory_alias: ALIAS_RETAINED" in policy:
        return  # explicitly retained
    raise AssertionError(
        "Both obsidian-memory and vault-memory skills ship here, but the alias is not declared "
        "ALIAS_RETAINED in deprecation_map.yml. Remove the orphan vault-memory dir (0 refs) or "
        "declare the alias with a removal deadline."
    )


def test_negcontrol_deprecated_name_logic() -> None:
    # a removal-marked line is allowed; a current-tense line is not
    assert _REF_ALLOW.search("formerly the pr-resolution-follow-up agent (REMOVED #350)")
    assert not _REF_ALLOW.search("delegate to the pr-resolution-follow-up agent now")


# ---- 12. mirror-completeness: each canonical core skill must be PRESENT in each mirror ----
_CORE = ("orchestrate", "resolve-pr", "post-merge", "learner", "start-task", "dependency-review")


def test_core_skill_mirrors_complete() -> None:
    # An agent on Cursor/Codex/.agents that hits a missing core skill gets "unknown command" while
    # references resolve and CI passes (Council: the mirror-completeness gap). Each mirror root that
    # EXISTS must carry every core skill the canonical .claude has.
    canon = _existing_skills()
    core_here = [c for c in _CORE if c in canon]
    if not core_here:
        pytest.skip("repo has no core workflow skills (e.g. governance-hub)")
    missing = []
    for mroot in (".cursor/skills", ".codex/skills", ".agents/skills"):
        d = REPO / mroot
        if not d.is_dir():
            continue  # repo does not support this harness mirror
        present = {x.name for x in d.glob("*") if x.is_dir()}
        for c in core_here:
            if c not in present:
                missing.append(f"{mroot}/{c} (in .claude, missing in mirror)")
    assert not missing, (
        "Core-skill mirror INCOMPLETE — skill in .claude but absent from a mirror "
        "(agent there hits 'unknown command'):\n  - " + "\n  - ".join(missing)
    )


# ============================ NEGATIVE CONTROLS ============================
def test_negcontrol_dangling_ref_exclusions() -> None:
    # template variables and legacy/removed contexts are NOT flagged (false-positive guards)
    assert _REF_ALLOW.search('[ ! -d ".claude/skills/learn-${CONCEPT}" ]')
    assert _REF_ALLOW.search("legacy alias `.claude/skills/vault-memory`")
    assert _REF_ALLOW.search("`scripts/hook_stop_drift_audit.py` was removed in #205")
    # a plain current-tense reference to a non-existent target is NOT excluded → would be flagged
    assert not _REF_ALLOW.search("run `.claude/skills/does-not-exist/SKILL.md` now")


def test_negcontrol_polarity_flags_inversion() -> None:
    assert _line_flags(
        "Client hooks are advisory; the real enforcement is the server-side floor.",
        POLARITY_BANNED,
        POLARITY_ALLOW,
    )
    assert not _line_flags(
        "Local hooks are PRIMARY; the server ruleset is the BACKSTOP.",
        POLARITY_BANNED,
        POLARITY_ALLOW,
    )


def test_negcontrol_headless_flags_proven_claim() -> None:
    assert _line_flags(
        "codex exec enforcement is proven and live in every repo.", HEADLESS_BANNED, HEADLESS_ALLOW
    )
    assert not _line_flags(
        "codex exec fires no hooks — accepted registered debt, not proven.",
        HEADLESS_BANNED,
        HEADLESS_ALLOW,
    )


def test_negcontrol_hub_flags_gap_claim() -> None:
    assert _line_flags(
        "governance-hub is intentionally unsupported for local first-try gating.",
        HUB_BANNED,
        HUB_ALLOW,
    )
    assert not _line_flags(
        "governance-hub was an active conceptual gap; resolved by #361 (self-gates now).",
        HUB_BANNED,
        HUB_ALLOW,
    )


def test_negcontrol_sweep_flags_blind_sweep() -> None:
    assert _line_flags(
        "Then sweep all repos and fix the deprecated hook in one wave.", SWEEP_BANNED, SWEEP_ALLOW
    )
    assert not _line_flags(
        "Never sweep the fleet without the change gate (one repo per PR).",
        SWEEP_BANNED,
        SWEEP_ALLOW,
    )
