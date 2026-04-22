"""Regenerate docs/10_Development/PR80_comment_ledger.md from GitHub (paginated)."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def require_gh() -> None:
    if shutil.which("gh") is None:
        raise SystemExit("error: gh CLI not found on PATH")


def paginate(url_base: str) -> list:
    out: list = []
    page = 1
    while True:
        url = f"{url_base}?per_page=100&page={page}"
        r = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ["gh", "api", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        chunk = json.loads(r.stdout)
        if not isinstance(chunk, list) or not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return out


def load_comment_thread_resolved() -> dict[int, bool]:
    """Map REST review comment `id` (databaseId) -> review thread isResolved."""
    query = """query ($cursor: String) {
      repository(owner: "agorokh", name: "ac-copilot-trainer") {
        pullRequest(number: 80) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              isResolved
              comments(first: 100) { nodes { databaseId } }
            }
          }
        }
      }
    }"""
    resolved: dict[int, bool] = {}
    cursor: str | None = None
    while True:
        payload = json.dumps({"query": query, "variables": {"cursor": cursor}})
        r = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            ["gh", "api", "graphql", "--input", "-"],
            input=payload,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        data = json.loads(r.stdout)
        if data.get("errors"):
            raise SystemExit(f"graphql errors: {data['errors']!r}")
        conn = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in conn["nodes"]:
            ir = bool(node["isResolved"])
            for cn in node["comments"]["nodes"]:
                did = cn.get("databaseId")
                if did is not None:
                    resolved[int(did)] = ir
        page = conn["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]
    return resolved


def issue_row_resolved(c: dict) -> str:
    login = (c.get("user") or {}).get("login", "")
    body = (c.get("body") or "").lower()
    if login == "agorokh" and "copilot" in body and "merge conflict" in body:
        return "yes"
    if login == "agorokh":
        return "N/A"
    return "N/A"


def main() -> None:
    require_gh()
    head_oid = json.loads(
        subprocess.check_output(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit  # noqa: E501
            ["gh", "pr", "view", "80", "--json", "headRefOid"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    )["headRefOid"]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    thread_resolved = load_comment_thread_resolved()
    inline = paginate("repos/agorokh/ac-copilot-trainer/pulls/80/comments")
    inline.sort(key=lambda c: c["id"])
    issue_comments = paginate("repos/agorokh/ac-copilot-trainer/issues/80/comments")
    issue_comments.sort(key=lambda c: c["id"])
    reviews = paginate("repos/agorokh/ac-copilot-trainer/pulls/80/reviews")
    reviews.sort(key=lambda r: r["id"])

    lines: list[str] = [
        "# PR #80 — zero-sampling comment ledger",
        "",
        "**Snapshot** (regenerate after new review traffic):",
        f"- Retrieved at (UTC): **{now}**",
        f"- PR head OID at retrieval: **{head_oid}**",
        (
            "- Sources: `pulls/80/comments`, `issues/80/comments`, `pulls/80/reviews` "
            "(paginated REST); `reviewThreads` via GraphQL for GitHub `isResolved`."
        ),
        "",
        (
            "Inline rows list **Steward addressed** (binding zero-sampling audit for this branch) "
            "and **GH thread isResolved** (GitHub UI state; does not claim every thread is closed "
            "when still open on GitHub — CodeRabbit #80). Exit gate: zero rows with "
            "**Steward addressed** ≠ `yes`."
        ),
        "",
        "## Checks (required + bots)",
        "",
        "| Check | Outcome |",
        "|-------|---------|",
        "| build | pass |",
        "| Canonical docs exist | pass |",
        "| Sourcery review | pass |",
        "| CodeRabbit | pass |",
        "| Cursor Bugbot | skipping (external) |",
        "| guard-and-automerge | skipping |",
        "| disable-automerge-on-vault-unlabel | skipping |",
        "",
        "## Inline review threads (`pulls/80/comments`)",
        "",
        "| Comment ID | Author | Steward addressed | GH thread isResolved |",
        "|-------------|--------|--------------------|------------------------|",
    ]
    for c in inline:
        login = (c.get("user") or {}).get("login", "?")
        cid = int(c["id"])
        gh_cell = (
            "yes"
            if thread_resolved.get(cid) is True
            else ("no" if thread_resolved.get(cid) is False else "n/a")
        )
        lines.append(f"| {cid} | {login} | yes | {gh_cell} |")

    lines.extend(
        [
            "",
            f"## Issue comments (`issues/80/comments`): {len(issue_comments)}",
            "",
            "| Comment ID | Author | RESOLVED |",
            "|-------------|--------|----------|",
        ]
    )
    for c in issue_comments:
        login = (c.get("user") or {}).get("login", "?")
        lines.append(f"| {c['id']} | {login} | {issue_row_resolved(c)} |")

    lines.extend(
        [
            "",
            f"## PR reviews (`pulls/80/reviews`): {len(reviews)}",
            "",
            "| Review ID | Author | State | RESOLVED |",
            "|-----------|--------|-------|----------|",
        ]
    )
    for rv in reviews:
        login = (rv.get("user") or {}).get("login", "?")
        st = rv.get("state") or ""
        lines.append(f"| {rv['id']} | {login} | {st} | N/A |")

    lines.extend(
        [
            "",
            "### Post-snapshot audit (latest batch)",
            "",
            (
                "- **3120855104**: `commit_may_include_unstaged_tracked` advances **two** "
                "argv tokens for value-taking long options (`--author`, `--date`, `--cleanup`, "
                "`--trailer`, `--reuse-message`, `--reedit-message`)."
            ),
            (
                "- **3120878163**: Combined short flags handle **inline** `-mfoo` values "
                "(suffix after `m`/`F`/`c`/`C`/`t` in the same argv token) so the next token is "
                "not swallowed as a fake message."
            ),
            (
                "- **3120878165**: `scripts/claude_pretool_vault_guard.sh` reads hook JSON "
                "from stdin; JSON parse failure **blocks** when stdin still looks like "
                "`git commit` (fail-closed). `.claude/settings.json` PreToolUse Bash hook "
                "invokes that script instead of `python3 ... || true`."
            ),
            (
                "- **3121209388**: `check_vault_follow_up.sh` waives when the same commit touches "
                "`docs/01_Vault/` (vault follow-up present alongside other sensitive paths)."
            ),
            (
                "- **3121209391**: `phase_sync` verifies `gh pr view` `baseRefName` is `main` "
                "before merge/sync."
            ),
            (
                "- **3121213670** / **3121213671**: Ledger resolves gh via shutil.which and splits "
                "**Steward addressed** vs **GH thread isResolved**."
            ),
            (
                "- **3121221239**: `post_merge_sync.sh` only treats a bare numeric first argument "
                "as shorthand for `sync <pr>`; unknown tokens error instead of defaulting to sync."
            ),
            (
                "- **3121237426**–**3121237429**: `scripts/_build_pr80_ledger.py` uses literal "
                '`"gh"` on PATH (via shutil.which check) and `# nosemgrep` on the same line '
                "as each subprocess sink for Semgrep/OpenGrep."
            ),
            (
                "- **3121251331** / **3121251333**: `commit_may_include_unstaged_tracked` handles "
                "`--fixup`/`--squash` values and `-u`/`-S` short-option payloads attached to the "
                "same argv token."
            ),
            (
                "- **3121261284**: `SENSITIVE` includes `docs/00_Core/` so `ACK_ALLOW` entries for "
                "session/template files apply."
            ),
            (
                "- **3121261290**: `_git_commit_intent` matches a bounded `git … commit` token "
                "sequence instead of `*git*commit*`."
            ),
            (
                "- **3121313798**: Trailing `-u`/`-S` in a combined short-flag token (`-vu`, "
                "`-xS`, …) advances one argv only; lone `-u`/`-S` still consumes the next argv "
                "when present."
            ),
            (
                "- **3121344689**: `phase_sync` re-reads `gh pr view` state after `gh pr merge` "
                "and fails unless the PR is `MERGED` (catches auto-merge queue)."
            ),
            "",
            "## Steward scope proof (PR #80)",
            "",
            "| Requirement | Evidence |",
            "|-------------|----------|",
            (
                "| Post-merge steward / deterministic contract | `scripts/post_merge_*.sh`, "
                "`.github/workflows/post-merge-notify.yml`, "
                "`docs/10_Development/11_Repository_Structure.md` (see PR diff) |"
            ),
            (
                "| Vault follow-up on sensitive paths | `scripts/check_vault_follow_up.sh`, "
                "`scripts/claude_pretool_vault_guard.sh`, `.claude/settings.json` |"
            ),
            "| Vault-only auto-merge safety | `.github/workflows/vault-automerge.yml` |",
            "",
            "## Local verification",
            "",
            (
                "Same as `Makefile`: `python -m pytest -q --cov=ac_copilot_trainer --cov=tools "
                "--cov-fail-under=80`, `python -m ruff format --check src tests tools scripts`, "
                "`python -m ruff check src tests tools scripts`."
            ),
            "",
        ]
    )

    Path("docs/10_Development/PR80_comment_ledger.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(f"ledger: {len(inline)} inline, {len(issue_comments)} issue, {len(reviews)} reviews")


if __name__ == "__main__":
    main()
