"""Compute a 'pain score' for a merged GitHub PR using only `gh` CLI data.

The score captures how much *iteration* a PR required after the team thought
it was done. High scores indicate a learning opportunity; the companion
`file_issue.py` opens a `process-learning` issue in `template-repo` so a
future RMS agent can mine the PR for skill / rule / hook improvements.

Formula (intentionally conservative for v1):

    pain = 1.0 * commits_after_first_review
         + 0.5 * fix_commits             (msg starts with fix:|chore: address|chore(review))
         + 0.3 * human_review_comments
         + 0.1 * bot_review_comments     (low weight — bot noise inflation, see Mistral review)
         + 2.0 * ci_red_runs
         + 1.0 * days_open_after_first_ready_for_review

    high   >= 25.0
    medium >= 12.0
    low    <  12.0

CLI: `python -m tools.pr_pain.pain_score --repo owner/name --pr N [--json] [--gh PATH]`

Tune thresholds from real data (`reports/process_miner/...` for first sample)
before hardening into the issue-filing path.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

# Known review-bot logins. New bots will appear as `<name>[bot]` and be caught
# by the suffix check; this allowlist covers a few that don't carry the suffix.
# Operators can extend it without a code change by adding `extra_bot_logins:`
# to `.github/pr-pain-config.yml` — see `_load_extra_bots`.
_BUILTIN_KNOWN_BOTS: frozenset[str] = frozenset(
    {
        "coderabbitai",
        "coderabbit",
        "copilot",
        "sourcery-ai",
        "qodo-merge-pro",
        "qodo-code-review",
        "chatgpt-codex-connector",
        "gemini-code-assist",
        "cursor",
        "cursor-agent",
        "github-actions",
        "dependabot",
        "renovate",
        "bugbot",
        "copilot-pull-request-reviewer",
    }
)

_DEFAULT_PAIN_CONFIG = ".github/pr-pain-config.yml"
# Cached merge of built-ins + YAML extras. `None` until first lookup.
_known_bots_cache: frozenset[str] | None = None


def _load_extra_bots(config_path: str = _DEFAULT_PAIN_CONFIG) -> frozenset[str]:
    """Return the `extra_bot_logins` set from `.github/pr-pain-config.yml`.

    Empty set if the file is absent, malformed, or PyYAML isn't installed —
    the caller transparently falls back to ``_BUILTIN_KNOWN_BOTS`` so the
    function never raises during scoring. Bot detection inflates score by
    3x per missed bot (0.1 → 0.3 weight), so making this list extensible
    without a code change is a maintainability win.
    """
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return frozenset()
    from pathlib import Path as _Path

    p = _Path(config_path)
    if not p.is_file():
        return frozenset()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return frozenset()
    extras = data.get("extra_bot_logins") if isinstance(data, dict) else None
    if not isinstance(extras, list):
        return frozenset()
    return frozenset(str(x).lower() for x in extras if isinstance(x, str))


def _known_bots() -> frozenset[str]:
    """Lazy-cached union of built-in + YAML extras.

    Looks up `_DEFAULT_PAIN_CONFIG` from the module namespace at call
    time (NOT via a default-arg binding) so a test or downstream caller
    can rebind the constant after import and have the change take
    effect — Python evaluates default args at function-definition time,
    which would otherwise freeze the path forever.
    """
    global _known_bots_cache
    if _known_bots_cache is None:
        _known_bots_cache = _BUILTIN_KNOWN_BOTS | _load_extra_bots(_DEFAULT_PAIN_CONFIG)
    return _known_bots_cache


_FIX_COMMIT_RE = re.compile(
    r"^(fix(\([^)]*\))?:|chore:\s*address|chore\(review\):)",
    re.IGNORECASE,
)

THRESHOLD_HIGH = 25.0
THRESHOLD_MEDIUM = 12.0

# Single source of truth for metric → weight. file_issue.py imports this so
# the issue body's contribution column never drifts from the score formula.
METRIC_WEIGHTS: dict[str, float] = {
    "commits_after_first_review": 1.0,
    "fix_commits": 0.5,
    "human_review_comments": 0.3,
    "bot_review_comments": 0.1,
    "ci_red_runs": 2.0,
    "days_open_after_first_ready_for_review": 1.0,
}


@dataclasses.dataclass(frozen=True)
class PainScore:
    """Result of scoring a single PR."""

    score: float
    level: str  # "high" | "medium" | "low"
    breakdown: dict[str, float]
    fingerprint: str
    inputs: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _parse_iso(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    # `gh` returns RFC3339; Python's fromisoformat accepts the trailing Z in 3.11+.
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _is_bot(login: str | None, type_: str | None) -> bool:
    if not login:
        return False
    if type_ and type_.lower() == "bot":
        return True
    if login.endswith("[bot]"):
        return True
    return login.lower() in _known_bots()


# Process timeouts for `gh` calls. Without these, a slow/hanging GitHub or
# a hung TCP connection would freeze the workflow indefinitely (Qodo
# round-12 finding). Single calls get 60s; paginated ones can legitimately
# take longer on PRs with hundreds of pages, so they get 180s. Both can
# be overridden via env for the rare ops case (e.g. cold-cache cross-org
# lookups). Hitting the timeout raises an explicit `RuntimeError` with a
# remediation hint — never a silent retry-or-zero.
_GH_DEFAULT_TIMEOUT_S = float(os.environ.get("PR_PAIN_GH_TIMEOUT_S", "60"))
_GH_PAGINATED_TIMEOUT_S = float(os.environ.get("PR_PAIN_GH_PAGINATED_TIMEOUT_S", "180"))


def _run_gh(
    cmd: list[str],
    *,
    timeout: float,
    op: str,
    body_input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """One chokepoint for `subprocess.run(gh, ...)` — enforces timeout +
    re-frames `TimeoutExpired` into a `RuntimeError` with the operation name
    so the workflow log shows *which* `gh` call hung."""
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=body_input,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"`gh` timed out after {timeout:.0f}s on {op}. "
            "Set PR_PAIN_GH_TIMEOUT_S / PR_PAIN_GH_PAGINATED_TIMEOUT_S to "
            "raise the limit, or check `gh auth status` + GitHub status page."
        ) from exc


def gh_json(args: list[str], gh: str) -> Any:
    """Run `gh` and parse stdout as JSON.

    Public so sibling modules (``file_issue``) can share one implementation
    without reaching into a private helper.
    """
    cmd = [gh, *args]
    res = _run_gh(cmd, timeout=_GH_DEFAULT_TIMEOUT_S, op=" ".join(args[:3]))
    if res.returncode != 0:
        raise RuntimeError(f"gh failed ({res.returncode}): {' '.join(cmd)}\n{res.stderr.strip()}")
    out = res.stdout.strip()
    if not out:
        return None
    return json.loads(out)


def _fetch_pr(repo: str, pr: int, gh: str) -> dict[str, Any]:
    fields = "number,title,headRefName,createdAt,mergedAt,isDraft,author"
    return gh_json(["pr", "view", str(pr), "--repo", repo, "--json", fields], gh)


_SLURP_MIN_GH_VERSION = "2.28"


def _explain_gh_failure(stderr: str, op: str) -> str:
    """Re-frame `gh` errors that look like missing-flag failures into a clear
    "needs gh ≥ N.NN" message.

    The CI workflow has a separate version guard step, but local CLI usage
    hits this code path too — without the re-framing, an old `gh` produces
    a cryptic `unknown flag --slurp` that takes a beat to recognize.
    """
    low = stderr.lower()
    if "--slurp" in low or "--paginate" in low or "unknown flag" in low:
        return (
            f"`gh` rejected `{op}` with: {stderr.strip()}. "
            f"This script needs `gh` >= {_SLURP_MIN_GH_VERSION} (for "
            "`--paginate --slurp`). Upgrade with `brew upgrade gh` or pin "
            f"`cli/cli` >= {_SLURP_MIN_GH_VERSION} in CI."
        )
    return f"gh api failed: {op}\n{stderr.strip()}"


def _fetch_paginated(api_path: str, gh: str) -> list[dict[str, Any]]:
    """Fetch a paginated REST endpoint that returns a JSON array per page.

    Uses ``gh api --paginate --slurp`` (gh ≥ 2.28) which produces a single
    JSON array of pages, e.g. ``[[item, item], [item], ...]``. We flatten
    one level. Avoids the broken ``text.replace('][', ',')`` trick which
    corrupts payloads that contain ``][`` inside string values (commit
    messages, review bodies — which is most of our endpoints).
    """
    cmd = [gh, "api", "--paginate", "--slurp", api_path]
    res = _run_gh(cmd, timeout=_GH_PAGINATED_TIMEOUT_S, op=api_path)
    if res.returncode != 0:
        raise RuntimeError(f"({res.returncode}) " + _explain_gh_failure(res.stderr, api_path))
    text = res.stdout.strip()
    if not text:
        return []
    pages = json.loads(text)
    out: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            out.extend(page)
        elif isinstance(page, dict):
            # Defensive: caller passed an endpoint whose page is an object,
            # not an array. Append as-is and let the caller handle it.
            out.append(page)
    return out


_COMMITS_REST_CAP = 250  # GitHub REST `pulls/{pr}/commits` hard limit per PR.


def _fetch_commits(repo: str, pr: int, gh: str) -> list[dict[str, Any]]:
    """Fetch PR commits via REST.

    GitHub caps `GET /repos/{repo}/pulls/{pr}/commits` at 250 commits per PR
    regardless of paging — see
    https://docs.github.com/en/rest/pulls/pulls#list-commits-on-a-pull-request.
    For PRs above the cap we'd silently undercount
    `commits_after_first_review` / `fix_commits` and bias the score *down*
    exactly on the largest, most painful PRs. We can't fix that here without
    a checkout or GraphQL switch, but we DO emit a stderr warning so the cap
    is visible to the operator and to the workflow log.
    """
    commits = _fetch_paginated(f"/repos/{repo}/pulls/{pr}/commits?per_page=100", gh)
    if len(commits) >= _COMMITS_REST_CAP:
        print(
            f"warning: {repo}#{pr} hit the {_COMMITS_REST_CAP}-commit REST cap; "
            "score is undercounted (see README 'Known limitations').",
            file=sys.stderr,
        )
    return commits


def _fetch_reviews(repo: str, pr: int, gh: str) -> list[dict[str, Any]]:
    return _fetch_paginated(f"/repos/{repo}/pulls/{pr}/reviews?per_page=100", gh)


def _fetch_review_comments(repo: str, pr: int, gh: str) -> list[dict[str, Any]]:
    return _fetch_paginated(f"/repos/{repo}/pulls/{pr}/comments?per_page=100", gh)


def _fetch_issue_comments(repo: str, pr: int, gh: str) -> list[dict[str, Any]]:
    # PR conversation comments live on the issue endpoint.
    return _fetch_paginated(f"/repos/{repo}/issues/{pr}/comments?per_page=100", gh)


def _fetch_changed_files(repo: str, pr: int, gh: str) -> list[str]:
    files = _fetch_paginated(f"/repos/{repo}/pulls/{pr}/files?per_page=100", gh)
    return [f["filename"] for f in files if "filename" in f]


def _fetch_workflow_runs(repo: str, head_ref: str, gh: str) -> list[dict[str, Any]]:
    if not head_ref:
        return []
    # URL-encode the branch — names can contain `/`, `#`, etc. that would
    # otherwise break the query. Use --paginate --slurp so PRs with hundreds
    # of CI runs are fully counted (one page = 100 runs by default).
    branch = urllib.parse.quote(head_ref, safe="")
    res = _run_gh(
        [
            gh,
            "api",
            "--paginate",
            "--slurp",
            f"/repos/{repo}/actions/runs?branch={branch}&per_page=100",
        ],
        timeout=_GH_PAGINATED_TIMEOUT_S,
        op="actions/runs",
    )
    if res.returncode != 0:
        raise RuntimeError(f"({res.returncode}) " + _explain_gh_failure(res.stderr, "actions/runs"))
    text = res.stdout.strip()
    if not text:
        return []
    pages = json.loads(text)
    out: list[dict[str, Any]] = []
    for page in pages:
        out.extend(page.get("workflow_runs", []) or [])
    return out


def _top_dirs(paths: list[str], top_n: int = 3) -> list[str]:
    """First-segment directory cluster, sorted by frequency desc, take top N."""
    counts: Counter[str] = Counter()
    for p in paths:
        parts = PurePosixPath(p).parts
        if not parts:
            continue
        counts[parts[0]] += 1
    return [d for d, _ in counts.most_common(top_n)]


def _fingerprint(top_dirs: list[str]) -> str:
    """Stable 12-hex-digit fingerprint over the sorted top-dir tuple."""
    seed = "|".join(sorted(top_dirs)) or "<empty>"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def compute_pain_score(
    repo: str,
    pr: int,
    *,
    gh: str = "gh",
) -> PainScore:
    """Public entry point. Raises RuntimeError on `gh` failures."""
    if shutil.which(gh) is None:
        raise RuntimeError(f"`{gh}` CLI not found on PATH")

    pr_meta = _fetch_pr(repo, pr, gh)
    if pr_meta is None:
        raise RuntimeError(f"PR {repo}#{pr} not found")

    created = _parse_iso(pr_meta.get("createdAt"))
    merged = _parse_iso(pr_meta.get("mergedAt"))
    head_ref = pr_meta.get("headRefName") or ""

    # Pain detection is a *post-merge* heuristic: the workflow only fires on
    # `pull_request: closed` with `merged == true`, but `compute_pain_score`
    # is also reachable from CLI / `workflow_dispatch`. Refuse unmerged PRs
    # explicitly so an open PR can't be scored mid-flight (in-flight churn
    # would inflate the score) and accidentally trigger an issue file.
    if merged is None:
        raise RuntimeError(
            f"PR {repo}#{pr} is not merged — pain scoring only applies to merged PRs"
        )

    commits = _fetch_commits(repo, pr, gh)
    reviews = _fetch_reviews(repo, pr, gh)
    review_comments = _fetch_review_comments(repo, pr, gh)
    issue_comments = _fetch_issue_comments(repo, pr, gh)
    changed = _fetch_changed_files(repo, pr, gh)
    runs = _fetch_workflow_runs(repo, head_ref, gh)
    # `_fetch_workflow_runs` returns every run that ever touched this branch
    # name. Drop runs outside the PR's lifetime: anything before `createdAt`
    # (long-lived branches reused across PRs, experimental pre-PR pushes)
    # AND anything after `mergedAt` (branch kept receiving pushes, or its
    # name was reused for an unrelated PR after merge). Both extremes
    # would inflate `ci_red_runs` without telling us anything about this
    # PR's pain.
    if created is not None or merged is not None:
        kept: list[dict[str, Any]] = []
        for r in runs:
            run_created = _parse_iso(r.get("created_at"))
            if run_created is None:
                # Be lenient — without a timestamp we can't prove the run is
                # outside the window, so we keep it (matches the original
                # behavior before lifetime-window filtering existed).
                kept.append(r)
                continue
            if created is not None and run_created < created:
                continue
            if merged is not None and run_created > merged:
                continue
            kept.append(r)
        runs = kept

    # First *human* review submission timestamp. Bot reviews must NOT move
    # this boundary — otherwise an auto-review bot posting first inflates
    # both `commits_after_first_review` (every commit becomes "after") and
    # `days_open_after_first_ready_for_review` (PR appears to have lingered
    # the entire time post-bot). Bots add value as comment volume signal,
    # not as the marker for "humans engaged".
    review_times = [
        _parse_iso(r.get("submitted_at"))
        for r in reviews
        if r.get("submitted_at")
        and not _is_bot(
            ((r.get("user") or {}).get("login") or ""),
            ((r.get("user") or {}).get("type") or ""),
        )
    ]
    review_times = [t for t in review_times if t is not None]
    first_review_at = min(review_times) if review_times else None

    # commits_after_first_review
    commits_after = 0
    fix_commits = 0
    for c in commits:
        msg = (c.get("commit") or {}).get("message") or ""
        first_line = msg.split("\n", 1)[0].strip()
        if _FIX_COMMIT_RE.match(first_line):
            fix_commits += 1
        committed_str = ((c.get("commit") or {}).get("committer") or {}).get("date")
        committed_at = _parse_iso(committed_str)
        if first_review_at and committed_at and committed_at > first_review_at:
            commits_after += 1

    # Comment counts (sum of inline review + top-level conversation).
    human_comments = 0
    bot_comments = 0
    for c in [*review_comments, *issue_comments]:
        user = c.get("user") or {}
        if _is_bot(user.get("login"), user.get("type")):
            bot_comments += 1
        else:
            human_comments += 1
    # Reviews themselves (with bodies) also count once.
    for r in reviews:
        body = (r.get("body") or "").strip()
        if not body:
            continue
        user = r.get("user") or {}
        if _is_bot(user.get("login"), user.get("type")):
            bot_comments += 1
        else:
            human_comments += 1

    # CI red runs (any genuinely failed run on the head branch). We DON'T
    # count `cancelled` here: GitHub Actions cancels older runs whenever a
    # newer push lands on the same concurrency group, so counting cancels
    # would inflate the score for any normal force-push / rebase workflow
    # without telling us anything about real CI pain.
    ci_red = sum(1 for r in runs if (r.get("conclusion") or "").lower() in {"failure", "timed_out"})

    # days_open_after_first_ready_for_review — proxy: time from first review
    # to merge (we cannot easily fetch the readyForReview event without GraphQL).
    days_after_review = 0.0
    if first_review_at and merged:
        days_after_review = max(
            0.0,
            (merged - first_review_at).total_seconds() / 86400.0,
        )

    breakdown = {
        "commits_after_first_review": float(commits_after),
        "fix_commits": float(fix_commits),
        "human_review_comments": float(human_comments),
        "bot_review_comments": float(bot_comments),
        "ci_red_runs": float(ci_red),
        "days_open_after_first_ready_for_review": round(days_after_review, 2),
    }
    score = round(sum(breakdown[k] * METRIC_WEIGHTS[k] for k in breakdown), 2)

    if score >= THRESHOLD_HIGH:
        level = "high"
    elif score >= THRESHOLD_MEDIUM:
        level = "medium"
    else:
        level = "low"

    top_dirs = _top_dirs(changed, top_n=3)

    inputs = {
        "repo": repo,
        "pr": pr,
        "title": pr_meta.get("title"),
        "head_ref": head_ref,
        "created_at": created.isoformat() if created else None,
        "merged_at": merged.isoformat() if merged else None,
        "first_review_at": first_review_at.isoformat() if first_review_at else None,
        "changed_top_dirs": top_dirs,
        "n_changed_files": len(changed),
        "n_commits": len(commits),
        "n_reviews": len(reviews),
        "n_workflow_runs": len(runs),
    }

    return PainScore(
        score=score,
        level=level,
        breakdown=breakdown,
        fingerprint=_fingerprint(top_dirs),
        inputs=inputs,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int, help="PR number")
    parser.add_argument("--gh", default="gh", help="`gh` CLI binary path")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout (default: human summary).",
    )
    args = parser.parse_args(argv)

    try:
        result = compute_pain_score(args.repo, args.pr, gh=args.gh)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 20

    if args.json:
        json.dump(result.as_dict(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    print(f"{args.repo}#{args.pr} pain score: {result.score:.1f} ({result.level})")
    print(f"  fingerprint: {result.fingerprint} (top dirs: {result.inputs['changed_top_dirs']})")
    for k, v in result.breakdown.items():
        print(f"    {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
