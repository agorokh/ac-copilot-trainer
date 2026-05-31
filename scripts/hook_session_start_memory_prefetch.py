#!/usr/bin/env python3
"""SessionStart command hook — Tier-3 substrate prefetch + lockfile stamp.

This is the LOAD half of the memory contract
(``docs/00_Core/MEMORY_CONTRACT.md``):

1. Resolve the **active workspace** for this repo from
   ``ops/memory_manifest.yml`` (matched by repo path under ``vault_root`` when
   name matching fails, else the workspace whose name matches the repo
   directory).
2. Issue an HTTP query against the workspace endpoint with a prompt derived
   from the current branch name (and optional ``CLAUDE_LOAD_PROMPT`` env).
3. Print a short, deterministic summary to stdout so Claude Code injects it
   into the agent's first turn.
4. **Stamp `.scratch/.last_memory_query`** with `{token, timestamp_utc,
   workspace, prompt}` so ``scripts/hook_memory_gate.py`` allows subsequent
   Edit/Write on code paths.

If no workspace is registered for this repo, the hook writes
``.scratch/.last_memory_query.missing`` instead so the gate degrades to
warn-only and the human sees the gap.

The script is **deterministic** (no LLM in the hook hot path; the upstream
MCP server may use one for extraction, but its call is a network request from
this script's perspective). Fail-open contract: any error → degrade to
"missing" marker → exit 0.

Environment knobs (rare):

* ``CLAUDE_MEMORY_PREFETCH=0`` — skip the entire hook (treated as "missing").
* ``CLAUDE_MEMORY_PREFETCH_TIMEOUT_S`` — HTTP timeout (default 6s).
* ``CLAUDE_LOAD_PROMPT`` — override the auto-derived prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

# Fleet probe contract (ws-ops#128/template#159): measured naive ~14-18s,
# hybrid ~40s; prefetch needs a relevance stamp, so naive + 30s.
DEFAULT_TIMEOUT_S = 30.0
SUMMARY_TRUNCATE = 1200  # chars of summary stdout we surface to the agent


def _repo_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p.resolve()
    here = Path.cwd().resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here


def _enabled() -> bool:
    val = os.environ.get("CLAUDE_MEMORY_PREFETCH")
    if val is None:
        return True
    return val.strip().lower() in ("1", "true", "yes", "on")


def _timeout_s() -> float:
    raw = os.environ.get("CLAUDE_MEMORY_PREFETCH_TIMEOUT_S", "")
    try:
        v = float(raw)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return DEFAULT_TIMEOUT_S


def _ttl_seconds() -> int:
    raw = os.environ.get("CLAUDE_MEMORY_GATE_TTL_SECONDS", "")
    try:
        v = int(raw)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 1800


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_branch(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
            timeout=4,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _derive_prompt(root: Path) -> str:
    override = os.environ.get("CLAUDE_LOAD_PROMPT", "").strip()
    if override:
        return override[:200]
    branch = _current_branch(root)
    # branch like feat/issue-115-foo → "issue 115 foo"; default to repo name
    if branch:
        cleaned = re.sub(r"^(?:feat|fix|chore|docs|cursor|claude)/", "", branch)
        cleaned = cleaned.replace("-", " ").replace("_", " ")
        if cleaned:
            return cleaned[:200]
    return root.name


def _load_manifest(root: Path) -> dict | None:
    path = root / "ops" / "memory_manifest.yml"
    if not path.is_file():
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        print(
            "WARNING: hook_session_start_memory_prefetch.py needs PyYAML — "
            "run `pip install -e '.[dev]'` or use the repo .venv python in "
            "SessionStart hooks (see .claude/settings.base.json).",
            file=sys.stderr,
        )
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _name_match_keys(name: str) -> set[str]:
    """Hyphen/underscore aliases for workspace ↔ directory name matching."""
    lowered = name.lower()
    return {lowered, lowered.replace("-", "_"), lowered.replace("_", "-")}


def _resolve_workspace(root: Path, manifest: dict | None) -> dict | None:
    """Return the workspace dict that matches this repo, or None."""
    if not isinstance(manifest, dict):
        return None
    hosts = manifest.get("hosts") or []
    if not isinstance(hosts, list):
        return None
    candidates: list[dict] = []
    for host in hosts:
        if not isinstance(host, dict):
            continue
        for ws in host.get("workspaces") or []:
            if isinstance(ws, dict):
                candidates.append(ws)
    if not candidates:
        return None
    # Prefer workspace name (repo basename) over vault_root path heuristics.
    basename_keys = _name_match_keys(root.name)
    for ws in candidates:
        ws_name = ws.get("name")
        if isinstance(ws_name, str) and _name_match_keys(ws_name) & basename_keys:
            return ws
    vault_matches: list[dict] = []
    for ws in candidates:
        vr = ws.get("vault_root")
        if isinstance(vr, str):
            try:
                vr_resolved = _resolve_vault_root(vr, root)
                if root.is_relative_to(vr_resolved):
                    vault_matches.append(ws)
            except (OSError, ValueError):
                pass
    if len(vault_matches) == 1:
        return vault_matches[0]
    return None


def _endpoint_allowed(endpoint: str) -> tuple[bool, str | None]:
    """Allow only local HTTP or HTTPS substrate endpoints (SSRF guard)."""
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False, "unparseable endpoint URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported scheme {parsed.scheme!r}"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "missing hostname"
    if host not in ("127.0.0.1", "localhost", "::1"):
        return False, "substrate endpoints must use loopback hosts only"
    return True, None


def _resolve_vault_root(vr: str, root: Path) -> Path:
    """Resolve manifest ``vault_root`` against the repo, not process cwd."""
    expanded = Path(os.path.expanduser(vr))
    if expanded.is_absolute():
        return expanded.resolve()
    return (root / expanded).resolve()


def _http_query_lightrag(endpoint: str, prompt: str, timeout: float) -> str:
    """POST /query → response text. Empty on failure."""
    url = endpoint.rstrip("/") + "/query"
    payload = json.dumps({"query": prompt, "mode": "naive"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed scheme
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return ""
    # LightRAG returns {"response": "...prose..."} or plain text; surface the field if present.
    try:
        data = json.loads(body)
        if isinstance(data, dict) and isinstance(data.get("response"), str):
            return data["response"]
    except (json.JSONDecodeError, ValueError):
        pass
    return body


# Maximum chars of substrate response body persisted into the lockfile.
# Large enough for semantic-coupling checks in hook_memory_gate.py; bounded so
# the gate's grep stays fast and the on-disk file stays diff-able for humans.
RESPONSE_BODY_LIMIT = 8192


def _stamp_lock(
    root: Path,
    *,
    workspace: str | None,
    prompt: str,
    ok: bool,
    response_body: str = "",
    provisioned: bool,
) -> Path:
    """Write the gate lockfile.

    Issue #115 council review (Gemini's pick / closes Mistral's "query spam"
    bypass + ChatGPT's "lockfile certifies ritual not cognition" diagnosis):
    the lockfile must carry the **actual Tier-3 substrate response body** so
    ``hook_memory_gate.py`` can verify the agent's memory query was
    semantically coupled to the file being edited — not just that *some*
    query happened.

    The body is truncated to ``RESPONSE_BODY_LIMIT`` characters. Bytes stripped
    of NUL / control characters that would break JSON encoding.
    """
    scratch = root / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    timestamp = _now_iso()
    token = hashlib.sha256(f"{timestamp}|{workspace}|{prompt}".encode()).hexdigest()

    # Clean + truncate response body so the lockfile stays small and parseable.
    safe_body = response_body.replace("\x00", "").strip()
    if len(safe_body) > RESPONSE_BODY_LIMIT:
        safe_body = safe_body[:RESPONSE_BODY_LIMIT] + "…(truncated)"

    payload = {
        "token": token,
        "timestamp_utc": timestamp,
        "workspace": workspace,
        "prompt": prompt,
        "ttl_seconds": _ttl_seconds(),
        "prefetch_ok": ok,
        "response_body": safe_body if ok else "",
        "response_body_len": len(safe_body) if ok else 0,
    }
    if provisioned:
        out = scratch / ".last_memory_query"
        if not ok:
            payload["hint"] = (
                "Tier-3 prefetch did not return a response body — issue an "
                "mcp__agentic-memory__query_knowledge_graph call before code edits"
            )
        try:
            (scratch / ".last_memory_query.missing").unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    else:
        out = scratch / ".last_memory_query.missing"
        payload["hint"] = workspace or "no workspace registered for this repo"
        try:
            (scratch / ".last_memory_query").unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _print_summary(*, workspace: str | None, prompt: str, body: str) -> None:
    sys.stdout.write("---\n")
    sys.stdout.write("Memory contract LOAD (Tier-3 substrate prefetch):\n")
    if workspace:
        sys.stdout.write(f"  workspace: {workspace}\n")
    sys.stdout.write(f"  prompt:    {prompt}\n")
    if body:
        snippet = body.strip().replace("\r", "")
        if len(snippet) > SUMMARY_TRUNCATE:
            snippet = snippet[:SUMMARY_TRUNCATE] + "…(truncated)"
        sys.stdout.write(f"  result:\n{snippet}\n")
    else:
        sys.stdout.write(
            "  result: (substrate unreachable or empty; gate will allow "
            "code-path edits in degraded mode)\n"
        )
    sys.stdout.write("---\n")


_AUDIT_TAIL_BYTES = 65_536


def _read_audit_tail_text(path: Path) -> str:
    """Read the tail of the audit log without loading unbounded history."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > _AUDIT_TAIL_BYTES:
                f.seek(-_AUDIT_TAIL_BYTES, os.SEEK_END)
                f.readline()  # align to JSONL line boundary
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _last_drift_score(root: Path) -> dict | None:
    """Return the most recent 'scored' record from ``.scratch/memory_audit.jsonl``.

    Closes the conversational-agent feedback loop (Gemini's "super-ego" design,
    issue #115 follow-up). The previous session's ``hook_stop_drift_audit.py``
    logged a drift_score; this session prepends a WARNING to turn-1 stdout when
    that score is high, so the agent enters the session aware of prior drift.

    Returns the most recent record whose ``reason == "scored"``. Earlier
    skip/skipped entries are ignored — they don't carry a useful score.
    """
    path = root / ".scratch" / "memory_audit.jsonl"
    if not path.is_file():
        return None
    text = _read_audit_tail_text(path)
    if not text:
        return None
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict) and record.get("reason") == "scored":
            return record
    return None


def _print_super_ego_prefix(root: Path) -> None:
    """If the last session was scored as drifting, warn at turn-1.

    The threshold (default 0.5) is intentionally moderate — we want the
    feedback signal to fire often enough to matter, not just on extreme
    drift. Tunable via ``CLAUDE_MEMORY_DRIFT_WARNING_THRESHOLD``.
    """
    threshold_raw = os.environ.get("CLAUDE_MEMORY_DRIFT_WARNING_THRESHOLD", "")
    try:
        threshold = float(threshold_raw) if threshold_raw else 0.5
    except (TypeError, ValueError):
        threshold = 0.5

    record = _last_drift_score(root)
    if record is None:
        return
    try:
        ds = float(record.get("drift_score", 0.0))
    except (TypeError, ValueError):
        return
    if ds < threshold:
        return

    sub = record.get("substantive_count", "?")
    cited = record.get("cited_count", "?")
    ts = record.get("timestamp_utc", "?")
    sys.stdout.write("---\n")
    sys.stdout.write(
        "WARNING: previous session memory-drift audit:\n"
        f"  drift_score: {ds:.2f} (threshold {threshold:.2f}) -- "
        f"{cited}/{sub} substantive responses cited substrate content\n"
        f"  recorded: {ts}\n"
        "  This session: explicitly cite substrate findings "
        "(vault paths, mcp__agentic-memory__ tool results, MEMORY_CONTRACT.md) "
        "in substantive responses so the next audit reflects grounded reasoning.\n"
    )
    sys.stdout.write("---\n")


def _drift_audit_enabled() -> bool:
    """Mirror ``hook_stop_drift_audit.py`` kill switch for super-ego warnings."""
    val = os.environ.get("CLAUDE_MEMORY_DRIFT_AUDIT")
    if val is None:
        return True
    return val.strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    root = _repo_root()
    if _drift_audit_enabled():
        _print_super_ego_prefix(root)
    prompt = _derive_prompt(root)
    if not _enabled():
        _stamp_lock(
            root,
            workspace=None,
            prompt=prompt,
            ok=False,
            response_body="",
            provisioned=False,
        )
        return 0
    manifest = _load_manifest(root)
    ws = _resolve_workspace(root, manifest)
    if ws is None:
        _stamp_lock(
            root,
            workspace=None,
            prompt=prompt,
            ok=False,
            response_body="",
            provisioned=False,
        )
        sys.stdout.write(
            "WARNING: no Tier-3 workspace registered for this repo in "
            "ops/memory_manifest.yml; gate degrades to warn-only on code paths "
            "(see docs/00_Core/MEMORY_CONTRACT.md § Recovery).\n"
        )
        return 0
    workspace_name = ws.get("name") or ""
    endpoint = ws.get("endpoint") or ""
    backend = (ws.get("backend") or "lightrag").lower()
    body = ""
    prefetch_ok = bool(endpoint and backend == "lightrag")
    if prefetch_ok:
        allowed, reason = _endpoint_allowed(endpoint)
        if not allowed:
            prefetch_ok = False
            sys.stderr.write(
                f"WARN  hook_session_start_memory_prefetch: blocked endpoint "
                f"({reason}): {endpoint}\n"
            )
        else:
            body = _http_query_lightrag(endpoint, prompt, _timeout_s())
            if not body.strip():
                prefetch_ok = False
    # Graphiti has no SessionStart HTTP prefetch yet. Stamping a provisioned lock
    # with an empty response_body hard-blocks the gate with no recovery path
    # (MCP queries do not refresh `.last_memory_query` today).
    provisioned = backend != "graphiti"
    if backend == "graphiti":
        sys.stdout.write(
            "WARNING: graphiti workspace — SessionStart HTTP prefetch is not "
            "implemented yet; gate degrades to warn-only. Call "
            "mcp__agentic-memory__query_knowledge_graph for context until "
            "graphiti HTTP prefetch or MCP lockfile refresh lands.\n"
        )
    # TODO(PR-D+): handle backend == "graphiti" via its HTTP API once finalized.
    _stamp_lock(
        root,
        workspace=workspace_name,
        prompt=prompt,
        ok=prefetch_ok,
        response_body=body,
        provisioned=provisioned,
    )
    _print_summary(workspace=workspace_name, prompt=prompt, body=body)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — fail-open
        # On total failure, still stamp the missing marker so the gate degrades
        # to warn-only and the session can proceed.
        try:
            root = _repo_root()
            _stamp_lock(
                root,
                workspace=None,
                prompt="(prefetch error)",
                ok=False,
                response_body="",
                provisioned=False,
            )
        except Exception:  # noqa: BLE001
            pass
        sys.stderr.write(f"WARN  hook_session_start_memory_prefetch: {exc}\n")
        sys.exit(0)
