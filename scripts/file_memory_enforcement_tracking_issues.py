#!/usr/bin/env python3
# ruff: noqa: E501 — ISSUE_BODY_TEMPLATE is markdown content; wrapping changes the rendered output.
"""File per-child tracking issues for the ``memory-enforcement-v1`` invariant.

Reads ``ops/propagation_manifest.yml``, finds children with
``status: tracking`` (or any non-``converged`` status) on the new invariant,
and files **one** structured issue per child using the
``architectural-invariant-gap`` template body.

The script is **idempotent**: re-running checks for an existing open issue with
the title prefix ``Invariant gap: memory-enforcement-v1`` on each repo and
skips children that already have one.

**Dry-run by default.** This is a cross-repo public action (creates issues
on 9 repos); the operator must pass ``--apply`` to actually file. Output in
dry-run mode lists each repo + the body that would be filed.

Usage::

    python3 scripts/file_memory_enforcement_tracking_issues.py            # dry-run
    python3 scripts/file_memory_enforcement_tracking_issues.py --apply    # actually file

Requires ``gh`` CLI authenticated with `issues: write` on each child repo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INVARIANT_ID = "memory-enforcement-v1"
ISSUE_TITLE = f"Invariant gap: {INVARIANT_ID} — adopt issue-#115 memory-enforcement substrate"
ISSUE_LABELS = ["architecture", "invariant-gap", "template-sync"]

ISSUE_BODY_TEMPLATE = """\
> Tracking issue filed by `scripts/file_memory_enforcement_tracking_issues.py`
> from `agorokh/template-repo` PR #116 (merge SHA TBD) for the
> **`memory-enforcement-v1`** invariant. See the canonical hardening proposal
> at [`agorokh/template-repo#115`](https://github.com/agorokh/template-repo/issues/115)
> and the postmortem
> [`memory-enforcement-postmortem-2026-05-16.md`](https://github.com/agorokh/template-repo/blob/main/docs/01_Vault/ProjectTemplate/02_Investigations/memory-enforcement-postmortem-2026-05-16.md).

## Invariant

**`memory-enforcement-v1`** — child ships the issue-#115 memory-enforcement substrate.

Canonical contract: [`docs/00_Core/MEMORY_CONTRACT.md`](https://github.com/agorokh/template-repo/blob/main/docs/00_Core/MEMORY_CONTRACT.md).

## What this issue is for

Bring this child repo in line with the new invariant by pulling the template
changes via `copier update` (or manual cherry-pick) and re-rendering the
per-repo touchpoints.

## Acceptance criteria

- [ ] `docs/00_Core/MEMORY_CONTRACT.md` exists.
- [ ] `CLAUDE.md` carries `@docs/00_Core/MEMORY_CONTRACT.md` next to the existing `@`-includes.
- [ ] `docs/01_Vault/<ProjectKey>/00_System/invariants/memory-three-tiers.md` and `secrets-from-doppler.md` exist (rename `ProjectTemplate` to your project key). The contract enumerates **all three memory tiers** (Tier 1 `AGENTS.md`, Tier 2 vault, Tier 3 semantic substrate via `mcp__agentic-memory__*`); Tier-3 read at LOAD is mandatory.
- [ ] `CLAUDE.md` carries the memory-architecture deprecation block (heading may be
      "Memory architecture override" or "Memory architecture (three tiers, no side channels)").
- [ ] `AGENT_CORE_PRINCIPLES.md` carries the "Architectural invariant gap" routing rule.
- [ ] `.github/ISSUE_TEMPLATE/architectural-invariant-gap.md` exists.
- [ ] `scripts/hook_session_start_memory_prefetch.py`, `scripts/hook_session_start_memory_redirect.py`, `scripts/hook_memory_gate.py`, `scripts/merge_memory_contract.py` exist.
- [ ] `.claude/settings.base.json` wires the four new hooks (two SessionStart, two PreToolUse `Edit|Write` and `Bash`). Verify with `python3 -m pytest tests/test_hook_scripts.py::test_invariant_memory_hooks_wired_in_base -q`.
- [ ] `make memory-contract-check` exits 0 — the marker-delimited block is in sync in `AGENTS.md` + every `.claude/agents/*.md`.
- [ ] `make doppler-doctor` exits 0.
- [ ] Per-repo `ops/memory_manifest.yml` workspace entry exists (this child has one declared upstream — see the new rows in [`agorokh/template-repo/ops/memory_manifest.yml`](https://github.com/agorokh/template-repo/blob/main/ops/memory_manifest.yml)). Substrate-side Graphiti namespace creation is tracked separately in [`agorokh/workstation-ops`](https://github.com/agorokh/workstation-ops) — until provisioned, the gate degrades to warn-only (not blocking).
- [ ] `python3 -m pytest tests/test_invariants_present.py tests/test_doppler_doctor.py tests/test_hook_memory_gate.py tests/test_merge_memory_contract.py tests/test_hook_session_start_memory_prefetch.py tests/test_hook_session_start_memory_redirect.py tests/test_hook_scripts.py -q` passes.

## How to land this PR

1. `copier update` from template-repo, **or** cherry-pick the squash-merge SHA of `template-repo#116` and run `scripts/copier_post_copy.py` if your repo uses Copier sync.
2. `python3 scripts/merge_settings.py --no-local` to refresh `.claude/settings.json`.
3. `make memory-contract` to render the marker block into `AGENTS.md` + the 5 `.claude/agents/*.md`.
4. `python3 scripts/hook_session_start_memory_prefetch.py` to stamp `.scratch/.last_memory_query` (or the `.missing` variant if the workspace isn't yet live).
5. `make ci-fast` — required tests must pass.
6. Open PR. Drop `template-sync` label on the PR for fleet visibility.

## Per-repo notes

{notes}

## Why this matters (one-paragraph)

The 2026-05-16 postmortem caught an agent writing 6 "memories" to the per-user
auto-memory directory while the vault credential strategy sat unread, leading
to a silent OpenRouter routing on the production Graphiti deploy. Documentation
alone did not prevent the drift. This invariant adds **deterministic runtime
gating** so the same class of failure cannot recur. The substrate itself stays
warn-only when a workspace isn't yet live — children are never bricked by the
adoption process.
"""


def _load_manifest() -> dict:
    import yaml  # type: ignore

    path = REPO_ROOT / "ops" / "propagation_manifest.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _existing_open_issue(repo: str) -> int | None:
    try:
        proc = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                repo,
                "--search",
                "Invariant gap memory-enforcement-v1 in:title",
                "--state",
                "open",
                "--json",
                "number,title",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("number"), int):
            return item["number"]
    return None


def _file_issue(repo: str, title: str, body: str, labels: list[str]) -> int | None:
    """Create issue. Tries with labels first; falls back to no labels if any
    label is missing on the child repo (so the issue still lands and the
    operator can re-label via UI / `gh issue edit`)."""
    base = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    with_labels = list(base)
    for lab in labels:
        with_labels.extend(["--label", lab])

    def _try(args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(args, capture_output=True, text=True, check=False, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as e:
            sys.stderr.write(f"ERR  {repo}: {e}\n")
            return None

    proc = _try(with_labels)
    if proc is None:
        return None
    if proc.returncode != 0:
        stderr = proc.stderr or ""
        # gh emits "could not add label" / "label X not found" when one is missing.
        if any(
            kw in stderr.lower() for kw in ("not found", "could not add label", "no such label")
        ):
            sys.stderr.write(f"WARN {repo}: one or more labels missing — retrying without labels\n")
            proc = _try(base)
            if proc is None or proc.returncode != 0:
                err = proc.stderr if proc else "(no proc)"
                sys.stderr.write(f"ERR  {repo}: fallback create failed: {err}\n")
                return None
        else:
            sys.stderr.write(f"ERR  {repo}: gh issue create failed: {stderr}\n")
            return None

    # gh prints the URL on stdout; extract the trailing number.
    url = proc.stdout.strip()
    try:
        return int(url.rsplit("/", 1)[-1])
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually file issues (default is dry-run).",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help="Restrict to specific child repos (full name, e.g. agorokh/mcp-servers). Repeat.",
    )
    args = parser.parse_args()

    manifest = _load_manifest()
    children = manifest.get("children") or []
    if args.only:
        children = [c for c in children if c.get("repo") in set(args.only)]

    filed = 0
    skipped = 0
    failures = 0
    for c in children:
        repo = c.get("repo")
        status = c.get("status", "tracking")
        notes = c.get("notes") or "(none)"
        if status == "converged":
            print(f"SKIP  {repo}: already converged")
            skipped += 1
            continue
        existing = _existing_open_issue(repo)
        if existing:
            print(f"SKIP  {repo}: existing open tracking issue #{existing}")
            skipped += 1
            continue
        body = ISSUE_BODY_TEMPLATE.format(notes=notes)
        if not args.apply:
            print(f"DRY-RUN  would file on {repo}: {ISSUE_TITLE}")
            continue
        number = _file_issue(repo, ISSUE_TITLE, body, ISSUE_LABELS)
        if number:
            print(f"FILED   {repo}#{number}")
            filed += 1
        else:
            print(f"FAIL    {repo}: see stderr")
            failures += 1

    summary = "applied" if args.apply else "dry-run"
    print(f"\n{summary}: filed={filed} skipped={skipped} failures={failures}")
    if args.apply and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
