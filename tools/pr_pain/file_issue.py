"""File a `process-learning` issue in the central repo when PR pain is non-low.

Inputs: a JSON pain score (stdin or `--score-file`) plus the source repo +
target repo. Behavior:

- If pain level is `low`, exit 0 silently — nothing to do.
- Compute the issue title from the fingerprint so the same root-cause cluster
  across N repos lands on the same issue.
- Search target repo for an open `process-learning` issue with `[fp:<hex>]` in
  the title. If found, append a comment with the new PR ref and update the
  body's "Linked PRs" section. If not, create a fresh issue.

CLI:
    python -m tools.pr_pain.file_issue \\
        --score-file pain.json \\
        --target-repo agorokh/template-repo \\
        [--source-repo owner/name] \\
        [--source-pr N] \\
        [--gh PATH] \\
        [--dry-run]

Exit codes:
    0  success (filed, appended, or no-op for level=low)
    1  CLI / input error
    2  gh / GitHub error
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from tools.pr_pain import pain_score
from tools.pr_pain.pain_score import METRIC_WEIGHTS, gh_json

# HTML comment marker embedded in the issue body. We currently dedup via
# the title (`[fp:<hex>]`), which Search reliably matches; this body marker
# is a forward-compat hook so a future change can also dedup via body
# search if titles ever start drifting.
_BODY_MARKER_PREFIX = "<!-- pr_pain_fingerprint: "
_BODY_MARKER_SUFFIX = " -->"
_LINKED_PRS_HEADING = "## Linked PRs"

# Suggested labels — workflow ensures these exist before posting.
LABEL_PRIMARY = "process-learning"


def _gh_run(args: list[str], gh: str, *, body_input: str | None = None) -> str:
    """Run a `gh` write/edit command and return stripped stdout.

    Wraps `pain_score._run_gh` (the chokepoint enforcing timeouts +
    re-framing `TimeoutExpired` into a clear `RuntimeError`) so a hung
    GitHub call here doesn't freeze the whole workflow run. Body-edit
    paths (`gh issue edit --body-file -`) inherit the same default
    timeout as read paths — issue edits are CPU-cheap on the GitHub side
    so a slow response strongly suggests a network / auth problem worth
    surfacing.
    """
    res = pain_score._run_gh(
        [gh, *args],
        timeout=pain_score._GH_DEFAULT_TIMEOUT_S,
        op=" ".join(args[:3]),
        body_input=body_input,
    )
    if res.returncode != 0:
        raise RuntimeError(f"gh failed ({res.returncode}): {res.stderr.strip()}")
    return res.stdout.strip()


def issue_title(fingerprint: str, top_dirs: list[str]) -> str:
    cluster = "/".join(top_dirs[:2]) if top_dirs else "unknown"
    return f"Process learning: pain pattern in `{cluster}` [fp:{fingerprint}]"


def _format_closed_related_section(closed_related: list[dict[str, Any]]) -> list[str]:
    """Render the optional "Related closed issues" body section.

    Returns an empty list when there are no closed peers — the caller
    interleaves this into the body lines, so an empty list collapses to
    nothing in the rendered markdown.
    """
    if not closed_related:
        return []
    lines = ["## Related closed issues", ""]
    for it in closed_related:
        number = it.get("number")
        title = (it.get("title") or "").strip() or "(no title)"
        url = it.get("html_url") or ""
        closed = (it.get("closed_at") or "").split("T", 1)[0] or "?"
        lines.append(f"- [#{number}]({url}) — closed {closed} — {title}")
    lines.append("")
    return lines


def issue_body(
    score: dict[str, Any],
    source_repo: str,
    source_pr: int,
    *,
    closed_related: list[dict[str, Any]] | None = None,
) -> str:
    breakdown = score["breakdown"]
    inputs = score["inputs"]
    fp = score["fingerprint"]
    # Deterministic row order (Qodo round-12 finding): iterate
    # `METRIC_WEIGHTS` first so the rendered table is stable across
    # callers that hand-build `breakdown` in arbitrary key order. Any
    # unknown metric (a future-version JSON or a hand-edited score
    # file) is rendered AFTER, sorted alphabetically, with a literal
    # `(unknown)` weight column so the operator can spot drift instead
    # of having it silently dropped or quietly mixed in.
    rows: list[str] = []
    seen: set[str] = set()
    for metric in METRIC_WEIGHTS:
        if metric not in breakdown:
            continue
        value = breakdown[metric]
        weight = METRIC_WEIGHTS[metric]
        rows.append(f"| `{metric}` | {value} | {weight} | {round(value * weight, 2)} |")
        seen.add(metric)
    for metric in sorted(set(breakdown) - seen):
        value = breakdown[metric]
        rows.append(f"| `{metric}` | {value} | (unknown) | — |")

    pr_url = f"https://github.com/{source_repo}/pull/{source_pr}"
    pr_link = f"[{source_repo}#{source_pr}]({pr_url})"
    title_text = inputs.get("title") or "(no title)"
    dirs = inputs.get("changed_top_dirs") or []
    dirs_text = ", ".join(f"`{d}`" for d in dirs) or "(none)"
    score_text = f"{score['score']:.1f}"
    level_text = score["level"]
    # `tools/process_miner/run.py` is corpus-scoped (--days/--since), not
    # PR-scoped — point at it correctly so an RMS agent can copy/paste the
    # command. The PR ref is included in the title/links so they can find
    # this PR in the miner output.
    miner_cmd = f"python -m tools.process_miner.run --repo {source_repo} --days 30 --emit-learned"
    self_url = "https://github.com/agorokh/template-repo/blob/main/tools/pr_pain/file_issue.py"

    lines = [
        f"**Source PR:** {pr_link} — {title_text}",
        "",
        f"**Pain score:** **{score_text}** ({level_text})",
        f"**Fingerprint:** `{fp}` — top changed dirs: {dirs_text}",
        "",
        "## Breakdown",
        "",
        "| Metric | Value | Weight | Contribution |",
        "|--------|-------|--------|--------------|",
        *rows,
        "",
        "## Suggested follow-up (for RMS / process-miner agent)",
        "",
        f"1. Run `tools/process_miner/` scoped to {source_repo}#{source_pr} (`{miner_cmd}`).",
        "2. Identify recurring failure modes / review themes.",
        (
            "3. Propose updates to skills (`.claude/skills/`), rules (`.claude/rules/`), "
            "hooks (`.claude/settings.base.json`), or scripts (`scripts/`)."
        ),
        (
            "4. If the change is universal, open a `template-repo` PR; "
            "`template-sync.yml` propagates to children. "
            "If repo-specific, land directly in the source repo."
        ),
        "",
        "## Linked PRs",
        "",
        f"- {pr_link} — score {score_text} ({level_text})",
        "",
        *_format_closed_related_section(closed_related or []),
        "---",
        "",
        (
            f"_Auto-filed by [`tools/pr_pain/file_issue.py`]({self_url}). "
            "The fingerprint marker below enables dedup across repos — do not remove._"
        ),
        "",
        f"{_BODY_MARKER_PREFIX}{fp}{_BODY_MARKER_SUFFIX}",
        "",
    ]
    return "\n".join(lines)


def _search_issues_by_fingerprint(
    target_repo: str, fingerprint: str, gh: str, *, state: str
) -> list[dict[str, Any]]:
    """Run a single Search API query for `[fp:<hex>]` titles in one state."""
    state_qual = {"open": "is:open", "closed": "is:closed", "any": ""}[state]
    query_parts = [
        f"[fp:{fingerprint}]",
        "in:title",
        "is:issue",
        f"repo:{target_repo}",
        f"label:{LABEL_PRIMARY}",
    ]
    if state_qual:
        query_parts.append(state_qual)
    query = " ".join(query_parts)
    result = gh_json(
        ["api", "search/issues", "-X", "GET", "-f", f"q={query}"],
        gh,
    )
    items = (result or {}).get("items") if isinstance(result, dict) else None
    return list(items) if items else []


def find_existing_issue(target_repo: str, fingerprint: str, gh: str) -> dict[str, Any] | None:
    """Return the first OPEN process-learning issue with this fingerprint.

    Open-only by design: appending a new PR ref to a closed issue would
    silently re-open or worse, leave it closed and lose the new PR's
    context. Use ``find_closed_related_issues`` to surface closed peers
    so the create path can link them in the new issue body for context.
    """
    items = _search_issues_by_fingerprint(target_repo, fingerprint, gh, state="open")
    return items[0] if items else None


def find_closed_related_issues(
    target_repo: str, fingerprint: str, gh: str, *, limit: int = 3
) -> list[dict[str, Any]]:
    """Return up to ``limit`` closed `[fp:<hex>]` peers for context-linking.

    When ``find_existing_issue`` finds nothing open and we're about to
    create a fresh issue, we still want the operator (and any RMS
    follow-up agent) to know that this fingerprint cluster has been seen
    + closed before. The new issue body's "Related closed issues"
    section links them inline so the historical thread is one click
    away, even if the underlying fix didn't actually solve the pain.
    """
    items = _search_issues_by_fingerprint(target_repo, fingerprint, gh, state="closed")
    # Newest first — Search API default is best-match, which we override
    # by sorting on `closed_at` (or `updated_at` as fallback).
    items.sort(key=lambda it: it.get("closed_at") or it.get("updated_at") or "", reverse=True)
    return items[:limit]


def append_pr_to_body(
    existing_body: str, source_repo: str, source_pr: int, score: float, level: str
) -> str:
    """Append a new bullet under the 'Linked PRs' heading, if not already present.

    Robust line-based parser (replaces the earlier regex approach — Qodo
    round-12). The previous regex `(?:- .+\\n)*` was fragile against:
      - bullets without trailing newline at EOF
      - wrapped bullet lines (continuation indented under the bullet)
      - markdown bullet variants (`*` / `+` instead of `-`)
      - manually-edited bodies with stray content between heading and
        bullets

    Strategy: split into lines, find the heading, scan forward to the
    next ATX heading (or EOF) — that slice IS the section. We insert the
    new bullet at the END of that slice (preserving any trailing blank
    line before the next section). If the heading is absent, we append a
    fresh section to the body.
    """
    bullet_marker = f"[{source_repo}#{source_pr}]"
    if bullet_marker in existing_body:
        return existing_body

    new_bullet = (
        f"- [{source_repo}#{source_pr}](https://github.com/{source_repo}/pull/{source_pr})"
        f" — score {score:.1f} ({level})"
    )

    lines = existing_body.splitlines(keepends=False)
    trailing_newline = existing_body.endswith("\n")

    heading_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() == _LINKED_PRS_HEADING),
        None,
    )
    if heading_idx is None:
        suffix = "" if trailing_newline else "\n"
        return existing_body + f"{suffix}\n{_LINKED_PRS_HEADING}\n\n{new_bullet}\n"

    # Find where the section ends. Per CommonMark, the typical
    # ``issue_body`` output uses a thematic break (``---``) followed by
    # a footer + the fingerprint HTML-comment marker — none of which are
    # ATX headings. Cursor Bugbot caught this regression in round 13:
    # if we only stop on ``## ``/``# `` headings, the new bullet leaks
    # past the section AND past the marker, ending up appended to the
    # very end of the body. We treat any of the following as a section
    # boundary: another ATX heading, a setext underline (``===``/``---``
    # following a non-blank line), a thematic break (``---``/``***``
    # /``___`` on its own), or the fingerprint marker comment.
    def _classify_boundary(idx: int, prev_blank: bool) -> str | None:
        """Return ``"here"`` if line ``idx`` IS the boundary, ``"above"``
        if the boundary is the immediately-preceding non-blank line
        (setext-heading case), or ``None`` if not a boundary.

        Per the Cursor Bugbot finding (post-9620014): only ``---`` is
        ambiguous between a thematic break and a setext H2 underline;
        ``***``/``___`` are *always* thematic breaks (CommonMark §4.1)
        regardless of what precedes them. And the setext disambiguation
        must use the *immediately preceding* line (``not prev_blank``),
        not the most-recent non-blank line — otherwise ``Foo\\n\\n===``
        is falsely classified as a setext heading despite the gap.
        """
        ln = lines[idx]
        stripped = ln.strip()
        if ln.startswith("## ") or ln.startswith("# "):
            return "here"
        if stripped.startswith(_BODY_MARKER_PREFIX):
            return "here"
        if not stripped:
            return None
        # CommonMark §4.1 thematic break: 3+ matching ``-``/``*``/``_``
        # characters, each optionally followed by spaces (``- - -``,
        # ``* * *``, ``_  _ _``). Strip internal whitespace before the
        # identical-char check.
        compact = "".join(stripped.split())
        if len(compact) < 3:
            return None
        ch = compact[0]
        same_run = compact == ch * len(compact)
        # ``***`` / ``___`` are unambiguously thematic breaks — never
        # setext underlines, no ``prev_blank`` gating needed.
        if ch in ("*", "_") and same_run:
            return "here"
        # ``---`` runs: thematic break if preceded by blank line, else
        # setext H2 underline (boundary is the line ABOVE).
        if ch == "-" and same_run:
            return "here" if prev_blank else "above"
        # ``===`` runs are *only* setext H1 underlines (not a thematic
        # break in any form). Requires immediately preceding non-blank
        # text — a blank-line gap means it's just stray ``===`` content,
        # not a heading marker.
        if ch == "=" and same_run and not prev_blank:
            return "above"
        return None

    section_end = len(lines)
    prev_blank = True  # heading line itself counts as a "fresh start"
    for j in range(heading_idx + 1, len(lines)):
        kind = _classify_boundary(j, prev_blank)
        if kind == "here":
            section_end = j
            break
        if kind == "above":
            # Walk backwards over any (defensive) blank lines to the
            # line that became the heading. Note: ``not prev_blank``
            # guarantees ``j-1`` is non-blank, so this loop usually
            # terminates immediately.
            k = j - 1
            while k > heading_idx and lines[k].strip() == "":
                k -= 1
            section_end = k
            break
        prev_blank = lines[j].strip() == ""

    insert_at = section_end
    while insert_at > heading_idx + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    new_lines = lines[:insert_at] + [new_bullet] + lines[insert_at:]
    out = "\n".join(new_lines)
    if trailing_newline:
        out += "\n"
    return out


def file_or_update_issue(
    score: dict[str, Any],
    source_repo: str,
    source_pr: int,
    target_repo: str,
    *,
    gh: str = "gh",
    dry_run: bool = False,
) -> dict[str, Any]:
    """File or update a `process-learning` issue.

    Returns one of:

    Possible return shapes:

    - `noop`              — `{action, reason}` (level=low; never touches gh)
    - `would-create`      — dry_run, new issue: `{action, title, labels,
                            body_preview, closed_related_count}` — body is
                            truncated to ~400 chars; full body is materialized
                            only on the live `created` path
    - `would-append`      — dry_run, hit:       `{action, url, number, comment_preview,
                            labels_to_add}`
    - `would-already-link`— dry_run, hit-dup:   same shape as `would-append`
    - `created`           — live, new:          `{action, url, number}`
    - `appended`          — live, hit:          `{action, url, number}`  (new comment posted)
    - `already-linked`    — live, hit-dup:      `{action, url, number}`  (idempotent no-op)

    Raises `ValueError` if `score` is missing required keys.
    """
    _required = {"level", "fingerprint", "score", "breakdown", "inputs"}
    missing = _required - set(score.keys())
    if missing:
        raise ValueError(f"score JSON missing required keys: {sorted(missing)}")
    if not isinstance(score["inputs"], dict):
        raise ValueError("score['inputs'] must be a mapping")

    if score["level"] == "low":
        return {"action": "noop", "reason": "level=low"}

    fp = score["fingerprint"]
    title = issue_title(fp, score["inputs"].get("changed_top_dirs") or [])
    existing = find_existing_issue(target_repo, fp, gh)

    if existing:
        # GitHub's Search API truncates issue bodies in some responses.
        # Refetch the full body before computing the new body so we never
        # overwrite the live issue with a truncated copy. If the refetch
        # fails, SKIP the body edit (under-linking is better than
        # clobbering) but STILL use the truncated body for the
        # already-linked check — the bullet marker for *this* PR may well
        # be in the truncated prefix, and missing it spams a duplicate
        # comment on every re-run of the workflow.
        full_body: str | None = None
        idempotency_body = existing.get("body") or ""
        if dry_run:
            # Dry-run never writes; search-API body is fine for preview.
            full_body = idempotency_body
        else:
            try:
                full = gh_json(
                    [
                        "issue",
                        "view",
                        str(existing["number"]),
                        "--repo",
                        target_repo,
                        "--json",
                        "body",
                    ],
                    gh,
                )
                if isinstance(full, dict) and isinstance(full.get("body"), str):
                    full_body = full["body"]
                    idempotency_body = full_body
            except RuntimeError as exc:
                # Per repo policy (`errors-silent-fallbacks`): the body
                # edit will be skipped (under-linking is safer than
                # clobbering with a truncated copy from the Search API)
                # but the operator MUST see why — so emit an explicit
                # warning to stderr. The workflow surfaces stderr in the
                # job log + step summary, so this becomes visible in CI.
                print(
                    f"warning: failed to refetch full body for "
                    f"{target_repo}#{existing.get('number')} ({exc}); "
                    "skipping `Linked PRs` body update — comment + label "
                    "reconciliation will still run.",
                    file=sys.stderr,
                )
                full_body = None  # explicit: skip body edit, comment-only

        # Compute the candidate new body only when we trust the source.
        new_body = (
            append_pr_to_body(
                full_body,
                source_repo,
                source_pr,
                score["score"],
                score["level"],
            )
            if full_body is not None
            else None
        )

        # Detect already-linked from whichever body we have available.
        # `append_pr_to_body` is idempotent: if the bullet marker is
        # present, it returns `existing_body` unchanged — that's our
        # signal. We use the truncated `idempotency_body` here so that a
        # refetch failure still suppresses the duplicate comment.
        bullet_marker = f"[{source_repo}#{source_pr}]"
        already_linked = bullet_marker in idempotency_body

        comment = (
            f"New PR matches this pain pattern (fingerprint `{fp}`):\n\n"
            f"- {source_repo}#{source_pr} — score **{score['score']:.1f}** ({score['level']})"
        )
        # Same `from:<repo>` / `pain:<level>` labels we'd attach on create —
        # need to apply on append too. Without this, the dedup'd issue keeps
        # only the labels from the FIRST observed PR: a later cross-repo
        # match never gets a `from:<otherrepo>` label, and a level
        # promotion (medium→high) is invisible to label-based triage. Apply
        # via `gh issue edit --add-label` (idempotent — no error if
        # already present).
        repo_label = f"from:{source_repo.split('/', 1)[-1]}"
        pain_label = f"pain:{score['level']}"
        if dry_run:
            return {
                "action": "would-already-link" if already_linked else "would-append",
                "url": existing.get("html_url"),
                "number": existing.get("number"),
                "comment_preview": comment,
                "labels_to_add": [LABEL_PRIMARY, repo_label, pain_label],
            }

        if new_body is not None and new_body != full_body:
            _gh_run(
                [
                    "issue",
                    "edit",
                    str(existing["number"]),
                    "--repo",
                    target_repo,
                    "--body-file",
                    "-",
                ],
                gh,
                body_input=new_body,
            )
        # Always reconcile labels on the append path (idempotent on the
        # GitHub side — re-adding an existing label is a no-op).
        _gh_run(
            [
                "issue",
                "edit",
                str(existing["number"]),
                "--repo",
                target_repo,
                "--add-label",
                repo_label,
                "--add-label",
                pain_label,
            ],
            gh,
        )
        if not already_linked:
            _gh_run(
                [
                    "issue",
                    "comment",
                    str(existing["number"]),
                    "--repo",
                    target_repo,
                    "--body-file",
                    "-",
                ],
                gh,
                body_input=comment,
            )
        return {
            "action": "already-linked" if already_linked else "appended",
            "url": existing.get("html_url"),
            "number": existing.get("number"),
        }

    # Surface previously-closed `[fp:<hex>]` peers in the new issue's body
    # so the operator (and any RMS follow-up agent) sees that this
    # fingerprint cluster has a history. We DO NOT reopen them — closing
    # was an explicit human decision; the new issue inherits the
    # contextual link instead. Refetch failures fall back to "no
    # related" so a transient gh error never blocks the create path.
    try:
        closed_related = find_closed_related_issues(target_repo, fp, gh)
    except RuntimeError as exc:
        print(
            f"warning: failed to search closed `[fp:{fp}]` issues in "
            f"{target_repo} ({exc}); proceeding without 'Related closed issues' "
            "section.",
            file=sys.stderr,
        )
        closed_related = []
    body = issue_body(score, source_repo, source_pr, closed_related=closed_related)
    repo_label = f"from:{source_repo.split('/', 1)[-1]}"
    pain_label = f"pain:{score['level']}"
    if dry_run:
        return {
            "action": "would-create",
            "title": title,
            "labels": [LABEL_PRIMARY, repo_label, pain_label],
            "body_preview": body[:400] + ("..." if len(body) > 400 else ""),
            "closed_related_count": len(closed_related),
        }
    url = _gh_run(
        [
            "issue",
            "create",
            "--repo",
            target_repo,
            "--title",
            title,
            "--body-file",
            "-",
            "--label",
            LABEL_PRIMARY,
            "--label",
            repo_label,
            "--label",
            pain_label,
        ],
        gh,
        body_input=body,
    )
    # `gh issue create` prints the issue URL with a trailing newline; strip
    # it and extract the trailing number so the returned dict matches the
    # docstring contract (`appended` / `already-linked` both include
    # `number`, and downstream consumers may rely on it). Per repo policy
    # (`errors-silent-fallbacks`), refuse to return `number: None` if the
    # URL didn't parse — that would silently break downstream consumers
    # and the contract documented above. A non-matching URL is a real
    # API contract change, not a transient error, so fail loud.
    url = url.strip()
    match = re.search(r"/issues/(\d+)$", url)
    if not match:
        raise RuntimeError(
            f"gh issue create returned a URL without a parseable issue number: {url!r}"
        )
    return {"action": "created", "url": url, "number": int(match.group(1))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--score-file",
        type=Path,
        help="Path to JSON file produced by `pain_score.py --json` (or '-' for stdin).",
    )
    parser.add_argument(
        "--target-repo",
        default="agorokh/template-repo",
        help="Repo to file the process-learning issue in.",
    )
    parser.add_argument(
        "--source-repo",
        help="Source repo (owner/name); defaults to value in score JSON.",
    )
    parser.add_argument(
        "--source-pr",
        type=int,
        help="Source PR number; defaults to value in score JSON.",
    )
    parser.add_argument("--gh", default="gh")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if shutil.which(args.gh) is None:
        print(f"error: `{args.gh}` not found", file=sys.stderr)
        return 2

    if args.score_file is None:
        if sys.stdin.isatty():
            parser.error("provide --score-file or pipe pain JSON on stdin")
        score_text = sys.stdin.read()
    elif str(args.score_file) == "-":
        score_text = sys.stdin.read()
    else:
        score_text = args.score_file.read_text(encoding="utf-8")

    try:
        score = json.loads(score_text)
    except json.JSONDecodeError as exc:
        print(f"error: invalid score JSON: {exc}", file=sys.stderr)
        return 1

    inputs = score.get("inputs") or {}
    source_repo = args.source_repo or inputs.get("repo")
    source_pr = args.source_pr or inputs.get("pr")
    if not source_repo or not source_pr:
        print(
            "error: source-repo and source-pr required (in score JSON or via flags)",
            file=sys.stderr,
        )
        return 1

    try:
        result = file_or_update_issue(
            score=score,
            source_repo=source_repo,
            source_pr=int(source_pr),
            target_repo=args.target_repo,
            gh=args.gh,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"error: malformed score JSON: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
