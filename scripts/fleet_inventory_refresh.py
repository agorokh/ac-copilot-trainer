#!/usr/bin/env python3
"""Refresh fleet_inventory.yml and fleet/_index.md from the GitHub API.

Reads static repo entries from docs/01_Vault/AcCopilotTrainer/fleet/fleet_inventory.yml,
merges snapshot blocks (GitHub metadata, Copier file, vault layout, Claude settings hooks),
and regenerates the summary table in fleet/_index.md.

Environment: set GITHUB_TOKEN or GH_TOKEN for normal rate limits (or use ``gh auth``-backed
tools in your shell — this script only reads those env vars).

Usage:
  python3 scripts/fleet_inventory_refresh.py
  python3 scripts/fleet_inventory_refresh.py --dry-run
  python3 scripts/fleet_inventory_refresh.py --only-index   # YAML already fresh; rewrite table
  python3 scripts/fleet_inventory_refresh.py --from-fleet-py  # append any fleet.py slugs missing
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "docs/01_Vault/AcCopilotTrainer/fleet/fleet_inventory.yml"
INDEX_PATH = ROOT / "docs/01_Vault/AcCopilotTrainer/fleet/_index.md"

MARK_BEGIN = "<!-- FLEET_INVENTORY_TABLE:BEGIN -->"
MARK_END = "<!-- FLEET_INVENTORY_TABLE:END -->"


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _is_not_found(err: str | None) -> bool:
    if not err:
        return False
    e = err.lower()
    return "404" in e or "not found" in e


def api_json(path: str, token: str | None) -> tuple[Any | None, str | None]:
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "template-repo-fleet-inventory",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read().decode()
    except HTTPError as e:
        body = e.read().decode(errors="replace") if e.fp else ""
        return None, f"HTTP {e.code}: {body[:300]}"
    except URLError as e:
        return None, f"URL error: {e.reason}"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON from GitHub API: {e}"


def _encode_contents_path(path: str) -> str:
    return "/".join(quote(seg, safe="") for seg in path.split("/") if seg)


def fetch_contents_array(
    owner: str,
    repo: str,
    path: str,
    token: str | None,
) -> tuple[list | None, str | None]:
    enc = _encode_contents_path(path)
    data, err = api_json(f"/repos/{owner}/{repo}/contents/{enc}", token)
    if err:
        return None, err
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict) and data.get("type") == "file":
        return [data], None
    return None, "unexpected contents shape"


def detect_vault_project_key(owner: str, repo: str, token: str | None) -> dict[str, Any]:
    items, err = fetch_contents_array(owner, repo, "docs/01_Vault", token)
    if err:
        if _is_not_found(err):
            return {"vault_root_present": False, "project_key": None, "error": None}
        return {"vault_root_present": False, "project_key": None, "error": err}
    if items is not None and len(items) == 1 and items[0].get("type") == "file":
        return {"vault_root_present": False, "project_key": None, "error": None}
    dirs: list[str] = []
    for it in items or []:
        if it.get("type") != "dir":
            continue
        n = it.get("name") or ""
        if n.startswith(".") or n == "":
            continue
        dirs.append(n)
    dirs.sort()

    def _is_numbered_prefix(name: str) -> bool:
        return len(name) >= 3 and name[0].isdigit() and name[1].isdigit() and name[2] == "_"

    project_dirs = [d for d in dirs if not _is_numbered_prefix(d)]
    pick = project_dirs[0] if project_dirs else (dirs[0] if dirs else None)
    return {"vault_root_present": True, "project_key": pick, "error": None}


def _claude_dir_exists(owner: str, repo: str, token: str | None) -> tuple[bool, str | None]:
    """Return (exists, error_if_not_discernible)."""
    items, err = fetch_contents_array(owner, repo, ".claude", token)
    if err:
        if _is_not_found(err):
            return False, None
        return False, err
    if items is not None and len(items) == 1 and items[0].get("type") == "file":
        return False, None
    return True, None


def fetch_settings_hooks(owner: str, repo: str, token: str | None) -> dict[str, Any]:
    settings_path = _encode_contents_path(".claude/settings.json")
    data, err = api_json(f"/repos/{owner}/{repo}/contents/{settings_path}", token)
    if err:
        if _is_not_found(err):
            has_claude, dir_err = _claude_dir_exists(owner, repo, token)
            if dir_err:
                return {
                    "claude_dir_present": False,
                    "settings_json_present": False,
                    "hook_event_count": None,
                    "error": dir_err,
                }
            return {
                "claude_dir_present": has_claude,
                "settings_json_present": False,
                "hook_event_count": None,
                "error": None,
            }
        return {
            "claude_dir_present": False,
            "settings_json_present": False,
            "hook_event_count": None,
            "error": err,
        }
    if not isinstance(data, dict) or data.get("type") != "file":
        has_claude, dir_err = _claude_dir_exists(owner, repo, token)
        if dir_err:
            return {
                "claude_dir_present": False,
                "settings_json_present": False,
                "hook_event_count": None,
                "error": dir_err,
            }
        return {
            "claude_dir_present": has_claude,
            "settings_json_present": False,
            "hook_event_count": None,
            "error": None,
        }
    raw_b64 = data.get("content") or ""
    try:
        raw = base64.b64decode(raw_b64.replace("\n", "")).decode("utf-8")
        parsed = json.loads(raw)
    except (binascii.Error, OSError, UnicodeError, ValueError):
        return {
            "claude_dir_present": True,
            "settings_json_present": True,
            "hook_event_count": None,
            "error": "settings.json not valid JSON",
        }
    if not isinstance(parsed, dict):
        return {
            "claude_dir_present": True,
            "settings_json_present": True,
            "hook_event_count": None,
            "error": "settings.json root must be a JSON object",
        }
    hooks = parsed.get("hooks")
    count = None
    if isinstance(hooks, dict):
        count = sum(len(v) if isinstance(v, list) else 0 for v in hooks.values())
    return {
        "claude_dir_present": True,
        "settings_json_present": True,
        "hook_event_count": count,
        "error": None,
    }


def fetch_copier(owner: str, repo: str, token: str | None) -> dict[str, Any]:
    data, err = api_json(
        f"/repos/{owner}/{repo}/contents/{_encode_contents_path('.copier-answers.yml')}",
        token,
    )
    if err:
        empty = {"copier_answers_present": False, "copier_answers_short_sha": None}
        if _is_not_found(err):
            return {**empty, "error": None}
        return {**empty, "error": err}
    if isinstance(data, dict) and data.get("type") == "file":
        full = data.get("sha")
        short = full[:7] if isinstance(full, str) and len(full) >= 7 else None
        return {
            "copier_answers_present": True,
            "copier_answers_short_sha": short,
            "error": None,
        }
    return {"copier_answers_present": False, "copier_answers_short_sha": None, "error": None}


def fetch_repo_snapshot(owner: str, repo: str, token: str | None) -> dict[str, Any]:
    meta, err = api_json(f"/repos/{owner}/{repo}", token)
    if err or not isinstance(meta, dict):
        return {
            "github": {"error": err or "no meta"},
            "template_sync": {"error": "skipped"},
            "vault": {"error": "skipped"},
            "agent_config": {"error": "skipped"},
        }
    gh: dict[str, Any] = {
        "default_branch": meta.get("default_branch"),
        "language": meta.get("language"),
        "archived": meta.get("archived"),
        "pushed_at": meta.get("pushed_at"),
        "updated_at": meta.get("updated_at"),
        "stars": meta.get("stargazers_count"),
        "open_issues_count": meta.get("open_issues_count"),
        "visibility": meta.get("visibility"),
        "error": None,
    }
    return {
        "github": gh,
        "template_sync": fetch_copier(owner, repo, token),
        "vault": detect_vault_project_key(owner, repo, token),
        "agent_config": fetch_settings_hooks(owner, repo, token),
    }


def _fmt_pushed(iso: str | None) -> str:
    if not iso:
        return "—"
    if "T" in iso and len(iso) >= 19:
        return f"{iso[:10]} {iso[11:19]}"
    return iso[:19] if len(iso) > 19 else iso


def render_table_row(r: dict[str, Any]) -> str:
    slug = r.get("slug", "")
    dom = r.get("domain", "")
    gh = r.get("github") or {}
    lang = gh.get("language") or "—"
    ts = r.get("template_sync") or {}
    if ts.get("copier_answers_present"):
        cop = "yes"
    elif ts.get("error"):
        cop = "?"
    else:
        cop = "no"
    v = r.get("vault") or {}
    vk = v.get("project_key") or "—"
    if v.get("error"):
        vk = "?"
    a = r.get("agent_config") or {}
    if a.get("settings_json_present"):
        st = "yes"
    elif a.get("error"):
        st = "?"
    else:
        st = "no"
    pushed = _fmt_pushed(gh.get("pushed_at"))
    status = "ok"
    if gh.get("error"):
        status = "error"
    elif any(isinstance(b, dict) and b.get("error") for b in (ts, v, a)):
        status = "partial"
    return f"| {slug} | {dom} | {lang} | {cop} | {vk} | {st} | {pushed} | {status} |"


def render_index_with_table(repos: list[dict[str, Any]], template: str) -> str:
    if MARK_BEGIN not in template or MARK_END not in template:
        raise ValueError("fleet_inventory_refresh: index markers missing")
    header = (
        "| slug | domain | language | copier answers | vault key | Claude settings | "
        "pushed (UTC) | refresh |\n|------|--------|----------|----------------|-----------|"
        "-----------------|--------------|---------|\n"
    )
    rows = "\n".join(render_table_row(r) for r in repos)
    new_block = f"{MARK_BEGIN}\n{header}{rows}\n{MARK_END}"
    before, rest = template.split(MARK_BEGIN, 1)
    _, after = rest.split(MARK_END, 1)
    return before + new_block + after


def write_index(repos: list[dict[str, Any]]) -> None:
    template = INDEX_PATH.read_text(encoding="utf-8")
    INDEX_PATH.write_text(render_index_with_table(repos, template), encoding="utf-8")


def merge_from_fleet_py(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root_s = str(ROOT)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    from tools.process_miner.fleet import DEFAULT_FLEET_REPOS, domain_for_repo

    known = {r["slug"] for r in repos if isinstance(r, dict) and r.get("slug")}
    out = list(repos)
    for slug in DEFAULT_FLEET_REPOS:
        if slug in known:
            continue
        _owner, name = slug.split("/", 1)
        dom = domain_for_repo(slug) or "infra"
        out.append(
            {
                "slug": slug,
                "name": name,
                "domain": dom,
                "notes": "auto-added from tools/process_miner/fleet.py",
            }
        )
        known.add(slug)
    return out


def refresh_repos(
    repos: list[dict[str, Any]],
    token: str | None,
    fetcher: Callable[[str, str, str | None], dict[str, Any]],
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for entry in repos:
        slug = (entry.get("slug") or "").strip()
        if slug.count("/") != 1:
            updated.append(entry)
            continue
        owner, repo = slug.split("/", 1)
        snap = fetcher(owner, repo, token)
        merged = {**entry, **snap}
        if "activity" not in snap and "activity" in entry:
            merged["activity"] = entry["activity"]
        updated.append(merged)
    return updated


def _require_yaml() -> int | None:
    if yaml is None:
        print(
            "fleet_inventory_refresh: PyYAML is required. Install dev deps: "
            "pip install -e '.[dev]'",
            file=sys.stderr,
        )
        return 1
    return None


def _cli_flag_conflicts(args: argparse.Namespace) -> int | None:
    if args.only_index and args.dry_run:
        print(
            "fleet_inventory_refresh: --only-index cannot be combined with --dry-run",
            file=sys.stderr,
        )
        return 2
    if args.only_index and args.from_fleet_py:
        print(
            "fleet_inventory_refresh: --only-index cannot be combined with --from-fleet-py",
            file=sys.stderr,
        )
        return 2
    return None


def _parse_inventory_yaml(raw_yaml: str) -> tuple[dict[str, Any] | None, int | None]:
    """Parse inventory YAML and validate ``repos``. Return ``(data, None)`` or ``(None, code)``."""
    if yaml is None:
        return None, 1
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        print(f"fleet_inventory_refresh: error parsing {YAML_PATH}: {e}", file=sys.stderr)
        return None, 1
    if not isinstance(data, dict):
        print(
            "fleet_inventory_refresh: fleet_inventory.yml root must be a mapping",
            file=sys.stderr,
        )
        return None, 1
    repos = data.get("repos")
    if repos is None:
        print(
            "fleet_inventory_refresh: fleet_inventory.yml must contain a top-level "
            "'repos' list (missing or null would wipe inventory)",
            file=sys.stderr,
        )
        return None, 1
    if not isinstance(repos, list):
        print("fleet_inventory_refresh: repos must be a list", file=sys.stderr)
        return None, 1

    for i, entry in enumerate(repos):
        if not isinstance(entry, dict):
            print(
                f"fleet_inventory_refresh: repos[{i}] must be a mapping",
                file=sys.stderr,
            )
            return None, 1
        slug = (entry.get("slug") or "").strip()
        if slug.count("/") != 1 or not slug.split("/")[0] or not slug.split("/")[1]:
            print(
                f"fleet_inventory_refresh: repos[{i}].slug must be owner/name",
                file=sys.stderr,
            )
            return None, 1

    return data, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Print slugs; no file writes")
    ap.add_argument(
        "--only-index",
        action="store_true",
        help="Read YAML and regenerate _index.md table only (no API calls)",
    )
    ap.add_argument(
        "--from-fleet-py",
        action="store_true",
        help="Append repos from tools/process_miner/fleet.py before refresh",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    if (conflict := _cli_flag_conflicts(args)) is not None:
        return conflict

    if (bad := _require_yaml()) is not None:
        return bad

    if not YAML_PATH.is_file():
        print(f"fleet_inventory_refresh: missing {YAML_PATH}", file=sys.stderr)
        return 1

    token = _token()
    if not token and not args.only_index and not args.dry_run:
        print(
            "fleet_inventory_refresh: no GITHUB_TOKEN/GH_TOKEN — unauthenticated "
            "REST calls are limited to about 60/hour; a full fleet refresh uses "
            "roughly 4-5 requests per repo and may fail partway. Set a token for "
            "reliable runs.",
            file=sys.stderr,
        )

    raw_yaml = YAML_PATH.read_text(encoding="utf-8")
    data, perr = _parse_inventory_yaml(raw_yaml)
    if perr is not None:
        return perr
    assert data is not None
    repos = data["repos"]
    assert isinstance(repos, list)

    if args.from_fleet_py:
        data["repos"] = merge_from_fleet_py(list(repos))
        repos = data["repos"]

    if args.only_index:
        try:
            write_index(list(repos))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"Wrote {INDEX_PATH}")
        return 0

    if args.dry_run:
        for entry in repos:
            if isinstance(entry, dict) and entry.get("slug"):
                print(f"would refresh {entry['slug']}")
        return 0

    data["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["repos"] = refresh_repos(list(repos), token, fetch_repo_snapshot)
    yaml_text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    index_template = INDEX_PATH.read_text(encoding="utf-8")
    try:
        index_text = render_index_with_table(data["repos"], index_template)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    YAML_PATH.write_text(yaml_text, encoding="utf-8")
    INDEX_PATH.write_text(index_text, encoding="utf-8")
    print(f"Wrote {YAML_PATH} and {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
