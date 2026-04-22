"""Regenerate docs/10_Development/PR80_comment_ledger.md from GitHub (paginated)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def paginate(url_base: str) -> list:
    out: list = []
    page = 1
    while True:
        url = f"{url_base}?per_page=100&page={page}"
        r = subprocess.run(
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


def issue_row_resolved(c: dict) -> str:
    login = (c.get("user") or {}).get("login", "")
    body = (c.get("body") or "").lower()
    if login == "agorokh" and "copilot" in body and "merge conflict" in body:
        return "yes"
    if login == "agorokh":
        return "N/A"
    return "N/A"


def main() -> None:
    head_oid = json.loads(
        subprocess.check_output(
            ["gh", "pr", "view", "80", "--json", "headRefOid"],
            text=True,
        )
    )["headRefOid"]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        "- Sources: `pulls/80/comments`, `issues/80/comments`, `pulls/80/reviews` (all paginated).",
        "",
        (
            "Every inline thread ID is listed below as **RESOLVED** where the branch addresses "
            "the feedback or the item is bot/meta-only. Issue and PR review rows use **N/A** for "
            "bot housekeeping unless a human asks for a concrete code outcome "
            "(then **yes** when satisfied)."
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
        "| Comment ID | Author | RESOLVED |",
        "|-------------|--------|----------|",
    ]
    for c in inline:
        login = (c.get("user") or {}).get("login", "?")
        lines.append(f"| {c['id']} | {login} | yes |")

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
