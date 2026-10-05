#!/usr/bin/env python3
# OWNER: @agorokh
"""Is this pull request vault-only? The scope half of the vault fast path (governance-hub#701).

Fleet policy makes the PR job that runs ``make ci-fast`` a required status check. A spoke that also
runs ``vault-automerge`` then has a problem: the composite waits ``merge-timeout-seconds`` (default
300s) for required checks, and a full build on a vault handoff routinely outlasts that. The fix is
a fast path: when every changed path is under ``docs/01_Vault/``, the build job runs the spoke's
``make ci-vault`` (the tests that read live vault notes) instead of the full ``make ci-fast``.

This script answers the one question that fast path depends on, once for the whole fleet, so the
rule cannot drift between spokes or away from the ``vault-automerge`` scope guard it mirrors:
the Files API, paginated, with the SOURCE path of every rename included (a rename of ``src/x.py``
into the vault is a deletion of code, not a vault change).

FAILS CLOSED. The verdict is ``full-build=false`` only when all of this is proven:
  * the event is ``pull_request``;
  * the PR's head, read before AND after the file list, equals the event's head SHA (the job tests
    the event's commit, so a list read from a newer head would describe a different change);
  * the file list is non-empty and shorter than the Files API cap (3000), so it is complete;
  * every ``filename`` and ``previous_filename`` starts with ``docs/01_Vault/``.
Anything else, including any API error, an unexpected payload or a crash in this script, is
``full-build=true``. The exit code is always 0: the verdict is the output, and a classifier that
cannot decide must run the full build, never fail the job or skip it.

Outputs (``$GITHUB_OUTPUT``): ``reason`` then ``full-build``. Both come from a fixed vocabulary;
no path or other PR-controlled text is ever written to the output file or a workflow command, so a
crafted file name cannot forge a ``full-build=false`` line.

Usage:
  classify_pr_scope.py [--event-name NAME] [--event-path FILE] [--json]
    --event-name  defaults to $GITHUB_EVENT_NAME
    --event-path  defaults to $GITHUB_EVENT_PATH
    --json        print the verdict as JSON instead of a workflow notice
  Token: $GH_TOKEN, else $GITHUB_TOKEN (needs ``pull-requests: read``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

# The vault-automerge scope guard's rule (`grep -Ev '^docs/01_Vault/'`). A parity test pins the two.
VAULT_PREFIX = "docs/01_Vault/"
FILES_API_CAP = 3000  # GitHub lists at most 3000 files per PR; a list this long may be truncated.
_PER_PAGE = 100
_MAX_PAGES = FILES_API_CAP // _PER_PAGE
_TIMEOUT_S = 10.0
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Reasons are fixed strings plus integers. This is the last line of defence if one ever is not.
_SAFE_REASON_RE = re.compile(r"^[A-Za-z0-9 _./()-]+$")

Fetch = Callable[[str], object]


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class Verdict:
    full_build: bool
    reason: str


def _full(reason: str) -> Verdict:
    return Verdict(True, reason)


def _api_base() -> str:
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def http_fetcher(token: str) -> Fetch:
    def fetch(path: str) -> object:
        req = urllib.request.Request(
            _api_base() + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "governance-hub-classify-pr-scope",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise FetchError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise FetchError(exc.__class__.__name__) from exc

    return fetch


def _head_sha(slug: str, number: int, fetch: Fetch) -> str:
    pr = fetch(f"/repos/{slug}/pulls/{number}")
    head = pr.get("head") if isinstance(pr, dict) else None
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise FetchError("no head SHA in the pull request payload")
    return sha


def _changed_paths(slug: str, number: int, fetch: Fetch) -> tuple[list[str], int]:
    """Every destination AND rename-source path, plus the number of file entries read."""
    paths: list[str] = []
    entries = 0
    for page in range(1, _MAX_PAGES + 1):
        batch = fetch(f"/repos/{slug}/pulls/{number}/files?per_page={_PER_PAGE}&page={page}")
        if not isinstance(batch, list):
            raise FetchError("the files payload is not a list")
        for entry in batch:
            name = entry.get("filename") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                raise FetchError("a file entry has no filename")
            paths.append(name)
            previous = entry.get("previous_filename")
            if previous is not None:
                if not isinstance(previous, str) or not previous:
                    raise FetchError("a file entry has a malformed previous_filename")
                paths.append(previous)
        entries += len(batch)
        if len(batch) < _PER_PAGE:
            break
    return paths, entries


def classify(event_name: str, event: object, fetch: Fetch | None, *, repository: str = "") -> Verdict:
    """The verdict for one workflow event. Never raises on API or payload trouble: it fails closed."""
    if event_name != "pull_request":
        return _full("not a pull_request event")
    pr = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pr, dict):
        return _full("no pull request in the event payload")
    number = pr.get("number")
    head = pr.get("head")
    event_sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        return _full("no pull request number in the event payload")
    if not isinstance(event_sha, str) or not _SHA_RE.match(event_sha):
        return _full("no head SHA in the event payload")
    repo = event.get("repository")
    slug = repo.get("full_name") if isinstance(repo, dict) else None
    if not isinstance(slug, str) or not slug:
        slug = repository
    if not _SLUG_RE.match(slug or ""):
        return _full("no repository slug")
    if fetch is None:
        return _full("no token to read the PR file list")
    try:
        before = _head_sha(slug, number, fetch)
        paths, entries = _changed_paths(slug, number, fetch)
        after = _head_sha(slug, number, fetch)
    except FetchError:
        return _full("PR file list unreadable")
    if before != event_sha or after != event_sha:
        return _full("PR head moved while its files were read")
    if entries == 0:
        return _full("PR file list is empty")
    if entries >= FILES_API_CAP:
        return _full(f"PR file list may be truncated (the Files API caps at {FILES_API_CAP})")
    outside = sum(1 for p in paths if not p.startswith(VAULT_PREFIX))
    if outside:
        return _full(f"{outside} changed path(s) outside {VAULT_PREFIX}")
    return Verdict(False, f"every changed path is under {VAULT_PREFIX}")


def _token() -> str:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def _load_event(path: str) -> object:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _emit(verdict: Verdict, *, as_json: bool) -> None:
    reason = verdict.reason if _SAFE_REASON_RE.match(verdict.reason) else "unspecified"
    flag = "true" if verdict.full_build else "false"
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"reason={reason}\nfull-build={flag}\n")
    if as_json:
        print(json.dumps({"full_build": verdict.full_build, "reason": reason}))
    else:
        print(f"::notice title=CI scope::full-build={flag} ({reason})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        token = _token()
        verdict = classify(
            args.event_name,
            _load_event(args.event_path),
            http_fetcher(token) if token else None,
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
        )
    except Exception as exc:  # noqa: BLE001 - a classifier crash must mean a full build
        verdict = _full(f"classifier error ({exc.__class__.__name__})")
    _emit(verdict, as_json=args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
