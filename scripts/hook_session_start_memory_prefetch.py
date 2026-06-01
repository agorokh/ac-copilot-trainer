#!/usr/bin/env python3
"""SessionStart command hook — Tier-3 substrate prefetch + lockfile stamp.

This is the LOAD half of the memory contract
(``docs/00_Core/MEMORY_CONTRACT.md``):

1. Resolve the **active workspace** for this repo from
   ``ops/memory_manifest.yml`` (matched by ``vault_root`` containing the repo
   path, falling back to the workspace whose name matches the parent
   directory). The operator-owned ``ops/memory_manifest.local.yml`` extension is
   merged in too, so child-repo workspaces registered locally resolve here.
2. Issue an HTTP query against the workspace endpoint with a prompt derived
   from the current branch name (and optional ``CLAUDE_LOAD_PROMPT`` env).
3. Print a short, deterministic summary to stdout so Claude Code injects it
   into the agent's first turn.
4. **Stamp `.scratch/.last_memory_query`** with `{token, timestamp_utc,
   workspace, prompt}` so ``scripts/hook_memory_gate.py`` allows subsequent
   Edit/Write on code paths.

If no workspace is registered for this repo, the hook writes
``.scratch/.last_memory_query.missing`` instead so the gate degrades to
warn-only and the human sees the gap. If a top-level ``resolution_exceptions``
block (tracked or local manifest) lists this repo as a *known, accepted* gap,
the hook surfaces the tracking issue and degrades quietly so the agent does not
re-file a duplicate ``architectural-invariant-gap`` issue every session.

The script is **deterministic** (no LLM in the hook hot path; the upstream
MCP server may use one for extraction, but its call is a network request from
this script's perspective). Fail-open contract: any error → degrade to
"missing" marker → exit 0.

Environment knobs (rare):

* ``CLAUDE_MEMORY_PREFETCH=0`` — skip the entire hook (treated as "missing").
* ``CLAUDE_MEMORY_PREFETCH_TIMEOUT_S`` — HTTP timeout (default 30s; ~2× measured
  naive p100 headroom on the fleet — see ``DEFAULT_TIMEOUT_S``).
* ``CLAUDE_MEMORY_PREFETCH_MODE`` — LightRAG query mode for the prefetch
  (default ``naive``, ~14–18s measured on the fleet; ``local`` adds graph
  relevance but is ~34–40s — no faster than ``hybrid``/``mix`` — so it is not
  the prefetch default).
* ``CLAUDE_LOAD_PROMPT`` — override the auto-derived prompt.
* ``AGENTIC_MEMORY_BRIDGE_PROVENANCE_JSON`` / ``..._FILE`` — optional
  sanitized output from ``mcp__agentic-memory__get_bridge_provenance``. When
  present, a manifest LightRAG workspace must be visible and not disabled in
  the active bridge; otherwise the hook writes a blocking missing marker so
  ``hook_memory_gate.py`` fails fast instead of letting the agent silently query
  the wrong workspace universe.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Fleet probe contract (agorokh/workstation-ops#128, agorokh/template-repo#159,
# agorokh/agent-factory#291). The old 6s default falsely reported the substrate
# "unreachable" and hard-blocked edits fleet-wide, because real query latency is far
# higher. MEASURED on the fleet (M2PRO, 2026-05-30, two live workspaces):
#     naive  ~14–18s   |   local  ~34–40s   |   mix/hybrid  ~38–41s
# So ``local`` is NOT "a few seconds" — it is ~40s, no better than hybrid for a prefetch.
# Only ``naive`` returns materially faster, and the SessionStart prefetch only needs a
# relevance *stamp* (vector/keyword retrieval that mentions the work's tokens), not graph
# synthesis. Three-part fix: (1) prefetch uses ``naive``; (2) timeout raised to 30s
# (≈2× the measured naive p100 for headroom); (3) a *timeout* is warn-only (substrate
# slow, not down) — see main() / hook_memory_gate.py — never a hard block.
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_QUERY_MODE = "naive"
ERR_TIMEOUT = "timeout"
ERR_UNREACHABLE = "unreachable"
SUMMARY_TRUNCATE = 1200  # chars of summary stdout we surface to the agent
BRIDGE_PROVENANCE_LIMIT = 16_384  # bytes/chars; provenance should be small sanitized JSON
# Optional opt-in staleness guard for a file-sourced capture, in seconds. The
# default is **0 (disabled)**: an mtime TTL is the wrong validity signal because
# the capture is written once per *server launch*, not per Claude session, so a
# long-running bridge would have a still-accurate file that a TTL would wrongly
# drop — silently disabling the drift check (cursor-bot #172 review). Freshness
# is instead guaranteed at the source: the wrapper rewrites the file on every
# launch, and ``capture_bridge_provenance.py`` removes it when it cannot produce
# fresh provenance in a real launch. Operators who still want a backstop set
# ``AGENTIC_MEMORY_BRIDGE_PROVENANCE_MAX_AGE_S`` to a positive value.
DEFAULT_BRIDGE_PROVENANCE_MAX_AGE_S = 0  # disabled by default; opt-in only


def _repo_root() -> Path:
    """Resolve to the **main** working directory, even from a git worktree.

    Worktree layout: `.git` is a *file* containing `gitdir: .../worktrees/<slug>`.
    Walking up looking for `.git` stops at the worktree path, whose basename is
    a random slug that never matches manifest `match_repo_basenames`. The fix:
    once we find the `.git` marker (or ``CLAUDE_PROJECT_DIR``), ask git for
    ``--git-common-dir`` (the shared main ``.git``) and return its parent.
    """
    from hook_repo_root import normalize_to_main_worktree_dir

    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return normalize_to_main_worktree_dir(p)
    here = Path.cwd().resolve()
    candidate: Path | None = None
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            candidate = parent
            break
    if candidate is None:
        return here
    return normalize_to_main_worktree_dir(candidate)


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


def _query_mode() -> str:
    """LightRAG mode for the SessionStart prefetch.

    Defaults to ``naive`` (~14–18s measured on the fleet — the prefetch only needs a
    relevance stamp, not graph synthesis). Overridable via ``CLAUDE_MEMORY_PREFETCH_MODE``
    for operators who want ``local`` (slower, ~34–40s, more graph-local relevance) or,
    rarely, ``hybrid``/``mix``.
    """
    raw = os.environ.get("CLAUDE_MEMORY_PREFETCH_MODE", "").strip().lower()
    if not raw:
        return DEFAULT_QUERY_MODE
    valid_modes = ("local", "naive", "hybrid", "mix", "global")
    if raw in valid_modes:
        return raw
    sys.stderr.write(
        "WARN  hook_session_start_memory_prefetch: unrecognized "
        f"CLAUDE_MEMORY_PREFETCH_MODE {raw!r}; falling back to default "
        f"{DEFAULT_QUERY_MODE!r}. Accepted values: {valid_modes}\n"
    )
    return DEFAULT_QUERY_MODE


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


def _safe_load_yaml(path: Path, *, warn_on_problems: bool) -> dict | None:
    """Load a YAML mapping from ``path``; return ``None`` on any failure.

    ``warn_on_problems`` makes setup/parse defects **loud** on stderr — missing
    PyYAML, an unparseable file, or a non-mapping top level. Only the *tracked*
    manifest sets this: a malformed tracked manifest is operator misconfiguration
    that would otherwise silently route into the degraded "no workspace" /
    "accepted gap" paths and mask the real problem (Qodo review, PR #175). A
    missing or malformed *local* manifest is routine and stays quiet.
    """
    if not path.is_file():
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        if warn_on_problems:
            print(
                "WARNING: hook_session_start_memory_prefetch.py needs PyYAML — "
                "run `pip install -e '.[dev]'` or use the repo .venv python in "
                "SessionStart hooks (see .claude/settings.base.json).",
                file=sys.stderr,
            )
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        if warn_on_problems:
            print(
                f"WARNING: hook_session_start_memory_prefetch.py could not parse "
                f"{path.name} ({exc.__class__.__name__}); treating as no manifest. "
                "Fix the YAML to restore Tier-3 workspace resolution.",
                file=sys.stderr,
            )
        return None
    if data is not None and not isinstance(data, dict):
        if warn_on_problems:
            print(
                f"WARNING: hook_session_start_memory_prefetch.py: {path.name} top "
                f"level is {type(data).__name__}, not a mapping; treating as no "
                "manifest.",
                file=sys.stderr,
            )
        return None
    return data if isinstance(data, dict) else None


def _load_manifest(root: Path) -> dict | None:
    return _safe_load_yaml(root / "ops" / "memory_manifest.yml", warn_on_problems=True)


def _load_local_manifest(root: Path) -> dict | None:
    """Operator-owned, gitignored manifest extension (``memory_manifest.local.yml``).

    The committed manifest ships only a generic skeleton; child-repo workspaces
    and resolution exceptions this operator owns live here. The local example
    file (``ops/memory_manifest.local.example.yml``) has long documented that "a
    merge step at boot can concatenate the workspaces" — this is that merge.
    """
    return _safe_load_yaml(root / "ops" / "memory_manifest.local.yml", warn_on_problems=False)


def _gather_workspaces(manifest: dict | None) -> list[dict]:
    """Flatten ``hosts[].workspaces`` from a manifest dict."""
    if not isinstance(manifest, dict):
        return []
    hosts = manifest.get("hosts") or []
    if not isinstance(hosts, list):
        return []
    out: list[dict] = []
    for host in hosts:
        if not isinstance(host, dict):
            continue
        workspaces = host.get("workspaces")
        if not isinstance(workspaces, list):
            continue
        for ws in workspaces:
            if isinstance(ws, dict):
                out.append(ws)
    return out


def _name_match_keys(name: str) -> set[str]:
    """Hyphen/underscore aliases for workspace ↔ directory name matching."""
    lowered = name.lower()
    return {lowered, lowered.replace("-", "_"), lowered.replace("_", "-")}


def _resolve_workspace(
    root: Path, manifest: dict | None, local_manifest: dict | None
) -> dict | None:
    """Return the workspace dict that matches this repo, or None.

    Candidates are the tracked manifest's workspaces first, then the
    operator-owned ``memory_manifest.local.yml`` extension — so a tracked
    name-match wins, and operator child-repo rows registered locally are
    visible to SessionStart prefetch (previously only the agent-facing ladder
    consulted the local manifest; the deterministic hook ignored it).
    """
    candidates = _gather_workspaces(manifest) + _gather_workspaces(local_manifest)
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
                if vr_resolved.is_relative_to(root):
                    vault_matches.append(ws)
            except (OSError, ValueError):
                pass
    if len(vault_matches) == 1:
        return vault_matches[0]
    return None


def _resolve_exception(
    root: Path, manifest: dict | None, local_manifest: dict | None
) -> dict | None:
    """Return a recorded ``resolution_exceptions`` entry for this repo, or None.

    A ``resolution_exceptions`` block (top-level, in the tracked manifest or the
    local extension) maps a repo basename to ``{reason, tracking_issue}`` and
    declares the missing Tier-3 workspace a *known, accepted gap*. The prefetch
    surfaces it and degrades to warn-only so the agent does NOT file yet another
    duplicate ``architectural-invariant-gap`` issue each session (the recurring
    pain behind template-repo#145 / #167 / #169 / #172).

    **Local entries win** — checked source-by-source (local first, then tracked)
    rather than via a merged dict. A merged ``dict.update()`` only overwrites on
    *identical* keys, so a local ``foo_bar`` and a tracked ``foo-bar`` (both
    valid under the documented hyphen/underscore tolerance) would BOTH survive
    and tracked-first iteration would wrongly win (Qodo review, PR #175).
    """
    basename_keys = _name_match_keys(root.name)
    for man in (local_manifest, manifest):  # local precedence
        if not isinstance(man, dict):
            continue
        block = man.get("resolution_exceptions")
        if not isinstance(block, dict):
            continue
        for key, val in block.items():
            if (
                isinstance(key, str)
                and isinstance(val, dict)
                and _name_match_keys(key) & basename_keys
            ):
                return val
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


def _http_query_lightrag(
    endpoint: str, prompt: str, timeout: float, mode: str
) -> tuple[str, str | None]:
    """POST /query → ``(response_text, error_kind)``.

    ``error_kind`` is ``None`` on success, ``ERR_TIMEOUT`` when the substrate did not
    answer within ``timeout`` (healthy but slow — a cold hybrid query is ~40s), or
    ``ERR_UNREACHABLE`` for connection refused / DNS / other transport errors. The caller
    treats ``ERR_TIMEOUT`` as warn-only and ``ERR_UNREACHABLE`` as a genuine outage
    (agorokh/workstation-ops#128).
    """
    url = endpoint.rstrip("/") + "/query"
    payload = json.dumps({"query": prompt, "mode": mode}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed scheme
            body = resp.read().decode("utf-8", errors="replace")
    except TimeoutError:  # socket.timeout is an alias of TimeoutError (py3.10+)
        return "", ERR_TIMEOUT
    except urllib.error.URLError as exc:
        # urlopen wraps a read/connect timeout in URLError(reason=TimeoutError).
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            return "", ERR_TIMEOUT
        return "", ERR_UNREACHABLE
    except OSError:
        return "", ERR_UNREACHABLE
    # LightRAG returns {"response": "...prose..."} or plain text; surface the field if present.
    try:
        data = json.loads(body)
        if isinstance(data, dict) and isinstance(data.get("response"), str):
            return data["response"], None
    except (json.JSONDecodeError, ValueError):
        pass
    return body, None


def _default_bridge_provenance_file() -> Path:
    """Canonical capture path written by ``scripts/mcp/capture_bridge_provenance.py``.

    Kept identical to that script's ``default_provenance_path`` (sans the env
    override, which ``_load_bridge_provenance`` handles separately) so the
    wrapper-side writer and this reader agree without an env handshake. Parity is
    pinned by ``tests/test_capture_bridge_provenance.py``.
    """
    cache_home = os.environ.get("XDG_CACHE_HOME", "").strip() or str(Path.home() / ".cache")
    return Path(cache_home) / "agentic-memory" / "bridge_provenance.json"


def _bridge_provenance_max_age_s() -> float:
    raw = os.environ.get("AGENTIC_MEMORY_BRIDGE_PROVENANCE_MAX_AGE_S", "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(DEFAULT_BRIDGE_PROVENANCE_MAX_AGE_S)


def _read_bridge_provenance_file(path: Path) -> str:
    """Read a provenance capture, honouring the staleness + size bounds.

    Returns "" (treated as "no assertion") when the file is absent, too large,
    or older than the max-age guard. A non-positive max age disables the guard.
    """
    max_age = _bridge_provenance_max_age_s()
    try:
        if max_age > 0:
            age = time.time() - path.stat().st_mtime
            if age > max_age:
                return ""
        with path.open("r", encoding="utf-8") as f:
            raw = f.read(BRIDGE_PROVENANCE_LIMIT + 1)
    except OSError:
        return ""
    if len(raw) > BRIDGE_PROVENANCE_LIMIT:
        return ""
    return raw


def _load_bridge_provenance() -> dict | None:
    """Return optional agentic-memory bridge provenance supplied by the host.

    The MCP tool itself is not callable from this deterministic SessionStart
    hook, but ``scripts/mcp/agentic-memory.sh`` captures the sanitized
    ``get_bridge_provenance`` payload to a well-known file before launching the
    server (issue #172). Resolution order: inline ``..._JSON`` env →
    ``..._FILE`` env → the canonical capture file. Absence means "no assertion
    available" rather than failure; malformed payloads fail open so a bad shell
    export does not wedge startup.
    """
    raw = os.environ.get("AGENTIC_MEMORY_BRIDGE_PROVENANCE_JSON", "").strip()
    if len(raw) > BRIDGE_PROVENANCE_LIMIT:
        return None
    if not raw:
        fp = os.environ.get("AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE", "").strip()
        path = Path(os.path.expanduser(fp)) if fp else _default_bridge_provenance_file()
        raw = _read_bridge_provenance_file(path)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        try:
            data = json.loads(data["result"])
        except (json.JSONDecodeError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def _bridge_workspace_problem(ws: dict, provenance: dict | None) -> tuple[str | None, str | None]:
    """Return ``(code, message)`` when bridge provenance contradicts manifest.

    Only live LightRAG rows are checked. Graphiti rows are offline-only or
    placeholders per ``MEMORY_SUBSTRATE.md`` and intentionally do not appear on
    the agent read path.
    """
    if not provenance:
        return None, None
    workspace = ws.get("name")
    if not isinstance(workspace, str) or not workspace:
        return None, None
    backend = str(ws.get("backend") or "").lower()
    if backend != "lightrag":
        return None, None

    visible_raw = provenance.get("visible_workspace_ids")
    disabled_raw = provenance.get("disabled_workspace_ids")
    visible = [str(x) for x in visible_raw] if isinstance(visible_raw, list) else []
    disabled = [str(x) for x in disabled_raw] if isinstance(disabled_raw, list) else []
    registry = provenance.get("registry_path") or "<unknown registry>"

    if workspace in disabled:
        return (
            "bridge_workspace_disabled",
            f"manifest workspace {workspace!r} is disabled in active agentic-memory "
            f"bridge registry {registry}; visible_workspace_ids={visible}",
        )
    if visible and workspace not in visible:
        return (
            "bridge_workspace_not_visible",
            f"manifest workspace {workspace!r} is not visible in active agentic-memory "
            f"bridge registry {registry}; visible_workspace_ids={visible}",
        )
    return None, None


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
    reason: str | None = None,
    gate_policy: str = "allow",
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
    if reason:
        payload["reason"] = reason
    if ok:
        out = scratch / ".last_memory_query"
        # Best-effort delete of any stale "missing" marker
        try:
            (scratch / ".last_memory_query.missing").unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    else:
        out = scratch / ".last_memory_query.missing"
        payload["hint"] = workspace or "no workspace registered for this repo"
        payload["gate_policy"] = gate_policy
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
        if workspace:
            sys.stdout.write(
                "  result: (substrate unreachable or empty; gate will block "
                "code-path edits until Tier-3 prefetch succeeds)\n"
            )
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
        _stamp_lock(root, workspace=None, prompt=prompt, ok=False, response_body="")
        return 0
    manifest = _load_manifest(root)
    local_manifest = _load_local_manifest(root)
    ws = _resolve_workspace(root, manifest, local_manifest)
    if ws is None:
        exception = _resolve_exception(root, manifest, local_manifest)
        if exception is not None:
            why = str(exception.get("reason") or "accepted Tier-3 gap").strip()
            tracking = str(exception.get("tracking_issue") or "").strip()
            # An accepted gap is semantically "no workspace registered, but known"
            # — it must behave like the generic no-workspace path: gate_policy
            # defaults to "allow" (workspace=None), so hook_memory_gate.py's
            # no-workspace branch allows code edits UNCONDITIONALLY, independent of
            # any leftover .last_memory_query lock. Do NOT use gate_policy="warn"
            # here: that policy is for the timeout case (a *registered* workspace
            # whose leftover fresh lock should still enforce relevance), and a
            # coexisting fresh lock (best-effort unlink failed, or timestamp tie)
            # would then fall through to relevance checks and wrongly block edits
            # despite a recorded resolution_exceptions gap (Cursor Bugbot, PR #175).
            _stamp_lock(
                root,
                workspace=None,
                prompt=prompt,
                ok=False,
                response_body="",
                reason="accepted_gap",
            )
            msg = f"NOTE: accepted Tier-3 gap for this repo ({why})"
            if tracking:
                msg += f"; tracked in {tracking}"
            msg += (
                ". Gate allows code-path edits (degraded, like an unregistered "
                "workspace); do NOT file a new architectural-invariant-gap issue "
                "(recorded in resolution_exceptions).\n"
            )
            sys.stdout.write(msg)
            return 0
        _stamp_lock(root, workspace=None, prompt=prompt, ok=False, response_body="")
        sys.stdout.write(
            "WARNING: no Tier-3 workspace registered for this repo in "
            "ops/memory_manifest.yml; gate degrades to warn-only on code paths "
            "(see docs/00_Core/MEMORY_CONTRACT.md § Recovery).\n"
        )
        return 0
    workspace_name = ws.get("name") or ""
    raw_backend = ws.get("backend")
    if raw_backend is None or str(raw_backend).strip() == "":
        sys.stderr.write(
            f"WARN  hook_session_start_memory_prefetch: workspace {workspace_name!r} "
            "omits backend; skipping Tier-3 HTTP prefetch (set backend explicitly in "
            "ops/memory_manifest.yml — see MEMORY_SUBSTRATE.md).\n"
        )
        backend = ""
    else:
        backend = str(raw_backend).lower()
        if backend not in ("lightrag", "graphiti"):
            sys.stderr.write(
                f"WARN  hook_session_start_memory_prefetch: workspace {workspace_name!r} "
                f"has unknown backend={raw_backend!r}; skipping Tier-3 HTTP prefetch.\n"
            )
    bridge_problem, bridge_message = _bridge_workspace_problem(ws, _load_bridge_provenance())
    if bridge_problem:
        _stamp_lock(
            root,
            workspace=workspace_name,
            prompt=prompt,
            ok=False,
            response_body="",
            reason=bridge_problem,
            gate_policy="block",
        )
        sys.stdout.write(
            "ERROR: Tier-3 workspace mismatch: "
            f"{bridge_message}. Do not query a different workspace; run "
            "mcp__agentic-memory__get_bridge_provenance and fix the bridge "
            "registry/allowlist before code-path edits.\n"
        )
        return 0
    body = ""
    if backend == "graphiti":
        sys.stdout.write(
            "NOTE: workspace declares backend=graphiti (offline-only per sunset ADR); "
            "SessionStart prefetch does not query Graphiti on the agent read path. "
            "Registered-workspace code edits stay blocked until backend is lightrag "
            "and the endpoint is live.\n"
        )
    prefetch_ok = backend == "lightrag"
    if prefetch_ok:
        from hook_memory_manifest import resolve_memory_endpoints

        timeout_s = _timeout_s()
        mode = _query_mode()
        # Probe reachable endpoints in priority order (env-bridge ts.net →
        # consumer-registry HTTPS → loopback) instead of the old loopback-only
        # SSRF guard + single manifest endpoint, so a non-central tailnet host can
        # reach the same substrate the MCP read path uses rather than dead
        # loopback (template-repo#180 / workstation-ops#170). The resolver applies
        # its own allowlist (registry-named or Tailscale-shaped host; HTTPS for
        # non-loopback), so the loopback-only _endpoint_allowed guard is retired.
        candidates = resolve_memory_endpoints(workspace_name, ws, env=dict(os.environ))
        saw_timeout = False
        for candidate in candidates:
            body, err = _http_query_lightrag(candidate.url, prompt, timeout_s, mode)
            if err is None and body.strip():
                break
            if err == ERR_TIMEOUT:
                # A timeout on ONE candidate doesn't prove the substrate is merely
                # slow — it may be a stale bridge/blackholed registry host while a
                # later candidate (e.g. manifest loopback) answers. Keep probing;
                # only treat it as slow-not-down if nothing answers (#187 review).
                saw_timeout = True
            body = ""
        if not body.strip() and saw_timeout:
            # Substrate is healthy but slow (a cold LightRAG query can take ~40s).
            # A mere timeout must NEVER hard-block edits (ws-ops#128 rec 2): write a
            # warn-only missing marker so the gate degrades instead of bricking the
            # session, even though the workspace is registered.
            _stamp_lock(
                root,
                workspace=workspace_name,
                prompt=prompt,
                ok=False,
                response_body="",
                reason=(
                    f"prefetch timed out after {timeout_s:g}s (substrate slow, not down); "
                    "warn-only — raise CLAUDE_MEMORY_PREFETCH_TIMEOUT_S or query manually"
                ),
                gate_policy="warn",
            )
            sys.stdout.write(
                f"WARNING: Tier-3 prefetch timed out after {timeout_s:g}s for workspace "
                f"{workspace_name!r} (mode={mode}); substrate is slow, not down. "
                "Gate degrades to warn-only this session; run "
                "mcp__agentic-memory__query_knowledge_graph manually to ground edits.\n"
            )
            return 0
        if not body.strip():
            prefetch_ok = False
    # TODO(PR-D+): handle backend == "graphiti" via its HTTP API once finalized.
    _stamp_lock(
        root,
        workspace=workspace_name,
        prompt=prompt,
        ok=prefetch_ok,
        response_body=body,
    )
    _print_summary(workspace=workspace_name, prompt=prompt, body=body)
    return 0


def _workspace_name_for_failure(root: Path) -> str | None:
    """Best-effort registered workspace id for fail-open missing markers."""
    try:
        manifest = _load_manifest(root)
        local_manifest = _load_local_manifest(root)
        ws = _resolve_workspace(root, manifest, local_manifest)
        if not ws:
            return None
        name = str(ws.get("name") or "").strip()
        return name or None
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — fail-open
        # On total failure, still stamp the missing marker. If a registered
        # workspace can be resolved, the gate blocks code edits; otherwise this
        # remains the no-workspace bootstrap warning path.
        try:
            root = _repo_root()
            _stamp_lock(
                root,
                workspace=_workspace_name_for_failure(root),
                prompt="(prefetch error)",
                ok=False,
                response_body="",
            )
        except Exception:  # noqa: BLE001
            pass
        sys.stderr.write(f"WARN  hook_session_start_memory_prefetch: {exc}\n")
        sys.exit(0)
