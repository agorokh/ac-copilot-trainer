#!/usr/bin/env python3
"""PreToolUse hook for ``Edit``/``Write``/``Bash`` — Tier-3 memory gate.

Enforces the LOAD half of the memory contract
(``docs/00_Core/MEMORY_CONTRACT.md``) without putting an LLM in the hook
hot path (template invariant — see ``tests/test_hook_scripts.py``).

Behavior:
  * Reads the Claude Code hook JSON payload from stdin.
  * Resolves the tool name and the target file/command path.
  * If the touched path is a **code path** (``src/``, ``scripts/``,
    ``tests/``, ``ops/``, ``.github/``, ``tools/``, or a top-level
    ``pyproject.toml`` / ``Makefile`` / ``setup.py``), the hook requires a
    **fresh** ``.scratch/.last_memory_query`` stamp (default TTL 30 min via
    ``CLAUDE_MEMORY_GATE_TTL_SECONDS``).
  * **Doc paths** (``docs/``, ``*.md`` at root, ``.scratch/``,
    ``.claude/skills/``, ``.claude/agents/``, ``.cursor/``,
    ``.github/ISSUE_TEMPLATE/``) are always allowed.
  * **Kill switch:** ``CLAUDE_MEMORY_GATE=0`` bypasses the gate entirely
    (unset defaults to **enabled** — set ``0`` to disable).
  * **Degraded mode:** when the SessionStart prefetch wrote
    ``.scratch/.last_memory_query.missing`` (no Tier-3 workspace registered
    for this repo), the gate warns once on stderr and allows.

Fail-open contract (same shape as the other deterministic hooks):
  * Malformed JSON → exit 0.
  * Missing tool name / fields → exit 0.
  * Unexpected exception → exit 0 (last-resort fail-open).

Exit codes:
  * ``0`` — allow.
  * ``2`` — block (Claude Code stops the tool call and surfaces stderr).

The gate's purpose is to catch **prompt-drift**: an agent that ignores the
memory contract in its system prompt cannot bypass the runtime check. See
``docs/00_Core/MEMORY_CONTRACT.md`` for the full contract.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path policy
# ---------------------------------------------------------------------------

_CODE_PATH_PREFIXES: tuple[str, ...] = (
    "src/",
    "scripts/",
    "tests/",
    "ops/",
    ".github/workflows/",
    ".github/actions/",
    "tools/",
)
_CODE_PATH_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "Makefile",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "requirements-dev.txt",
        ".pre-commit-config.yaml",
    }
)
_CODE_DIR_TOP_LEVEL: frozenset[str] = frozenset(
    {"src", "scripts", "tests", "ops", "tools", ".github"}
)

# Anything under these matches "documentation / prompt" and is allowed.
_DOC_PATH_PREFIXES: tuple[str, ...] = (
    "docs/",
    ".scratch/",
    ".claude/skills/",
    ".claude/agents/",
    ".claude/rules/",
    ".cursor/",
    ".github/ISSUE_TEMPLATE/",
    ".github/PULL_REQUEST_TEMPLATE/",
)
_DOC_PATH_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "CLAUDE.md",
        "AGENTS.md",
        "AGENT_CORE_PRINCIPLES.md",
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        ".gitignore",
    }
)

# Bash commands that look like file edits (we still want to gate these on code paths).
_CODE_TOP_FOR_REDIRECT = "|".join(re.escape(n) for n in _CODE_PATH_TOP_LEVEL)
_BASH_FILE_EDIT_RE = re.compile(
    rf"""
    (?:
      \bsed\s+-i
    | \bsed\s+(?:-[^\s]+\s+)*-i(?:\.\w+)?
    | \btee\s+
    | cat\s*>>?\s*
    | >>\s*[\w./\-]+\.(?:py|sh|yml|yaml|json|toml|md)\b
    | >\s*[\w./\-]+\.(?:py|sh|yml|yaml|json|toml|md)\b
    | >>\s*["'][\w./\-]+\.(?:py|sh|yml|yaml|json|toml|md)["']
    | >\s*["'][\w./\-]+\.(?:py|sh|yml|yaml|json|toml|md)["']
    | >>\s*(?:scripts|src|tests|ops|tools|\.github)/[\w./\-]+
    | >\s*(?:scripts|src|tests|ops|tools|\.github)/[\w./\-]+
    | >>\s*["'](?:scripts|src|tests|ops|tools|\.github)/[^"']+["']
    | >\s*["'](?:scripts|src|tests|ops|tools|\.github)/[^"']+["']
    | >>\s*(?:{_CODE_TOP_FOR_REDIRECT})\b
    | >\s*(?:{_CODE_TOP_FOR_REDIRECT})\b
    | >>\s*["'](?:{_CODE_TOP_FOR_REDIRECT})["']
    | >\s*["'](?:{_CODE_TOP_FOR_REDIRECT})["']
    | \b(?:cp|mv)\s+\S+\s+\S+
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)
_BASH_COPY_MOVE_VERB_RE = re.compile(r"\b(?:cp|mv)\b", re.IGNORECASE)


def _bash_copy_move_destinations(cmd: str) -> list[str]:
    """Return destination operand(s) for ``cp``/``mv`` (flags-aware, including ``-t``)."""
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        return []
    if not parts or parts[0].lower() not in ("cp", "mv"):
        return []
    args = parts[1:]
    dest: str | None = None
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--target-directory="):
            dest = a.split("=", 1)[1]
            i += 1
            continue
        if a.startswith("-t") and len(a) > 2:
            dest = a[2:]
            i += 1
            continue
        if a in ("-t", "--target-directory"):
            if i + 1 < len(args):
                dest = args[i + 1]
            i += 2
            continue
        if a == "--":
            i += 1
            break
        if a.startswith("-") and not a[1:].isdigit():
            i += 1
            continue
        break
    if dest is None:
        rest = args[i:]
        if len(rest) >= 2:
            dest = rest[-1]
    return [dest] if dest else []


# Issue #115 council review (Mistral bypass #2, #4): indirect-execution write
# paths the agent can use to mutate code without triggering Edit/Write tools.
# Conservative: treat ANY interpreter eval (-c / -e) and any `<scheme> | sh`
# pipeline as a code-path edit. Operators can bypass via CLAUDE_MEMORY_GATE=0
# if they explicitly need these (e.g. one-shot debug command).
_BASH_INDIRECT_EXEC_RE = re.compile(
    r"""
    (?:
      \bpython3?\s+-c\b
    | \bnode\s+(?:-e|--eval)\b
    | \bdeno\s+eval\b
    | \bperl\s+-[ne]\b
    | \bruby\s+-e\b
    | \bbash\s+-c\b
    | \bzsh\s+-c\b
    | \bsh\s+-c\b
    | \beval\s+["'$]
    | (?:curl|wget|fetch)\s+[^|]*\|\s*(?:bash|sh|zsh|python3?)\b
    | <<\s*['"]?(?:EOF|PY|SH|BASH|HEREDOC)\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)
_BASH_SYNTHETIC_CODE_PATH = "scripts/bash_memory_gate_edit"

_DEFAULT_TTL_SECONDS = 1800  # 30 minutes
_LOCK_NAME = ".last_memory_query"
_LOCK_MISSING_NAME = ".last_memory_query.missing"


def _repo_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        candidate = Path(env_root)
        if candidate.is_dir():
            return candidate.resolve()
    # Fall back to git rev-parse equivalent.
    here = Path.cwd().resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here


def _gate_enabled() -> bool:
    """``CLAUDE_MEMORY_GATE`` must be truthy (or unset → default ON)."""
    val = os.environ.get("CLAUDE_MEMORY_GATE")
    if val is None:
        return True  # default ON
    return val.strip().lower() in ("1", "true", "yes", "on")


def _ttl_seconds() -> int:
    raw = os.environ.get("CLAUDE_MEMORY_GATE_TTL_SECONDS", "")
    try:
        v = int(raw)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return _DEFAULT_TTL_SECONDS


def _normalize_rel_path(path: str, *, root: Path | None = None) -> str:
    """Normalize to a repo-relative POSIX path; collapse ``..`` when ``root`` given."""
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    norm = norm.removeprefix("/")
    if root is None:
        return norm
    try:
        candidate = Path(norm)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        rel = resolved.relative_to(root.resolve())
        return str(rel).replace("\\", "/")
    except (ValueError, OSError):
        # Traversal escapes the repo — treat as code so the gate still fires.
        return norm


def _classify(path: str, *, root: Path | None = None) -> str:
    """Return ``"doc"``, ``"code"``, or ``"other"`` for a repo-relative path."""
    norm = _normalize_rel_path(path, root=root)
    if not norm:
        return "other"
    # Top-level exact matches take precedence.
    if "/" not in norm:
        if norm in _DOC_PATH_TOP_LEVEL:
            return "doc"
        if norm in _CODE_PATH_TOP_LEVEL or norm in _CODE_DIR_TOP_LEVEL:
            return "code"
        # Other top-level files (e.g. ad-hoc scripts) — be conservative and treat as doc.
        return "doc"
    for prefix in _DOC_PATH_PREFIXES:
        if norm.startswith(prefix):
            return "doc"
    for prefix in _CODE_PATH_PREFIXES:
        if norm.startswith(prefix):
            return "code"
    return "other"


def _to_repo_relative(path: str, root: Path) -> str:
    try:
        p = Path(path)
        if p.is_absolute():
            return str(p.resolve().relative_to(root))
    except (ValueError, OSError):
        pass
    return path


def _lock_paths(root: Path) -> tuple[Path, Path]:
    scratch = root / ".scratch"
    return scratch / _LOCK_NAME, scratch / _LOCK_MISSING_NAME


def _read_lock(lock_path: Path) -> dict | None:
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _lock_is_fresh(lock: dict, ttl: int) -> bool:
    ts = lock.get("timestamp_utc")
    if not isinstance(ts, str):
        return False
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(UTC)
    delta = (now - when).total_seconds()
    return 0 <= delta <= ttl


# Tokens shorter than this are too common to be useful as file-relevance
# signals (e.g. "py", "sh", "md"). Council insight (Gemini): require ≥1
# substantive token from the file path to appear in the substrate response.
_TOKEN_MIN_LEN = 3
_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")

# Top-level / well-known basenames that are themselves substantive even at <3
# chars. Today empty; extend as real false-negatives surface.
_TOKEN_ALLOWLIST: frozenset[str] = frozenset()


def _file_tokens(rel_path: str) -> list[str]:
    """Extract substantive tokens from a repo-relative path.

    `scripts/hook_memory_gate.py` → ``["scripts", "hook", "memory", "gate"]``
    (the `.py` extension is dropped). Tokens are lowercased and filtered to
    length ≥ 3 chars unless explicitly allowlisted. Used by the file-relevance
    check that closes Mistral bypass #3 (memory query spam).
    """
    if not rel_path:
        return []
    # Strip extension for the basename only — keep extensions for directories
    # like `.github/` since they are semantically substantive.
    parts = rel_path.split("/")
    if parts and "." in parts[-1]:
        base = parts[-1]
        # Leading-dot basenames (``.bash_edit``) are not ``name.ext``.
        if not (base.startswith(".") and base.count(".") == 1):
            # Drop the file extension: `gate.py` → `gate`.
            parts[-1] = base.rsplit(".", 1)[0]
    out: list[str] = []
    for segment in parts:
        for tok in _TOKEN_SPLIT_RE.split(segment):
            tok = tok.lower()
            if not tok:
                continue
            if len(tok) >= _TOKEN_MIN_LEN or tok in _TOKEN_ALLOWLIST:
                out.append(tok)
    return out


def _body_mentions_any(body: str, tokens: list[str]) -> bool:
    """True if any ``token`` appears in ``body`` (case-insensitive substring).

    Substring match is intentional: an agent who queries `"hook memory gate"`
    and gets back prose mentioning `hook_memory_gate.py` succeeds.
    """
    if not body or not tokens:
        return False
    lower = body.lower()
    return any(tok in lower for tok in tokens)


def _lock_is_relevant(lock: dict, code_paths: list[str]) -> tuple[bool, str]:
    """Verify the lockfile's response_body is relevant to the code paths.

    Returns ``(is_relevant, reason)``. Closes Mistral bypass #3 (memory query
    spam) + addresses ChatGPT's "ritual not cognition" diagnosis: the gate
    now requires the substrate response to actually mention something tied
    to the file being edited, not just that *some* query happened.

    Degrades gracefully:
      * Lock without ``response_body`` field (older format) → relevant (so
        in-flight sessions don't break on a hook upgrade).
      * Lock with ``response_body_len`` field present but body empty → not
        relevant (substrate was unreachable or returned nothing).
    """
    if "response_body" not in lock:
        # Pre-issue-#115 lockfile format; allow.
        return True, "lockfile has no response_body field (older format)"
    body = lock.get("response_body")
    if not isinstance(body, str):
        return False, "lockfile response_body is not a string"
    if not body.strip():
        return False, (
            "lockfile response_body is empty — substrate returned no relevant "
            "context. Refine your prompt and re-query."
        )
    for rel in code_paths:
        tokens = _file_tokens(rel)
        if tokens and _body_mentions_any(body, tokens):
            return True, ""
    # No code path's tokens appeared in the response body.
    return False, (
        "lockfile response_body has no token overlap with the file(s) being "
        "edited — query memory with a prompt that references the target file(s)"
    )


def _extract_touched_paths(tool_name: str, tool_input: dict) -> list[str]:
    out: list[str] = []
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        fp = tool_input.get("file_path") or tool_input.get("notebook_path")
        if isinstance(fp, str) and fp:
            out.append(fp)
    elif tool_name == "MultiEdit":
        fp = tool_input.get("file_path")
        if isinstance(fp, str) and fp:
            out.append(fp)
    elif tool_name == "Bash":
        cmd = tool_input.get("command")
        if not isinstance(cmd, str):
            return out
        direct_edit = bool(_BASH_FILE_EDIT_RE.search(cmd))
        indirect_exec = bool(_BASH_INDIRECT_EXEC_RE.search(cmd))
        copy_dests = _bash_copy_move_destinations(cmd)
        copy_move = bool(copy_dests) or bool(_BASH_COPY_MOVE_VERB_RE.search(cmd))
        if direct_edit or indirect_exec or copy_move:
            for dest in copy_dests:
                out.append(dest)
            # Indirect-execution surfaces (`python -c`, `curl|bash`, heredocs)
            # write to "somewhere" the agent controls — we cannot extract a
            # specific target. Always treat as a synthetic code path so the
            # gate fires even when the command also contains parseable file
            # tokens (e.g. `curl https://x/install.sh | bash` has install.sh
            # which is not the actual write target).
            if indirect_exec:
                out.append(_BASH_SYNTHETIC_CODE_PATH)
            # Greedy: extract any *.py/*.sh/... tokens; if none parse, treat as
            # a single synthetic "bash-edit" code path so the gate fires.
            tokens = re.findall(r"[\w./\-]+\.(?:py|sh|yml|yaml|json|toml|md)", cmd)
            tokens += re.findall(r'["\']([\w./\-]+\.(?:py|sh|yml|yaml|json|toml|md))["\']', cmd)
            if not tokens:
                tokens = re.findall(
                    rf"(?:scripts|src|tests|ops|tools|\.github)/[\w./\-]+"
                    rf"|{_CODE_TOP_FOR_REDIRECT}",
                    cmd,
                )
                tokens += re.findall(
                    r'["\']((?:scripts|src|tests|ops|tools|\.github)/[^"\']+)["\']',
                    cmd,
                )
                tokens += re.findall(
                    rf'["\']({_CODE_TOP_FOR_REDIRECT})["\']',
                    cmd,
                )
            if tokens:
                out.extend(tokens)
            else:
                # Unparsed edit target — treat as code-path so the gate still fires.
                # Issue #115 / Mistral bypass #2: `python -c "open(...)"` and
                # `curl | bash` patterns reach this branch — no parseable file
                # name, but the indirect-exec regex matched, so we gate.
                out.append(_BASH_SYNTHETIC_CODE_PATH)
    return out


def _emit_block(
    *,
    root: Path,
    paths: list[str],
    workspace_hint: str | None,
    reason: str | None = None,
) -> int:
    """Emit the standard BLOCK message on stderr and exit 2."""
    headline = (
        "BLOCK: hook_memory_gate.py — Tier-3 substrate query is missing, stale, "
        "or not relevant to the file being edited"
    )
    lines = [headline]
    if reason:
        lines.append(f"  Reason: {reason}")
    for p in paths:
        lines.append(f"  Touched path: {p}")
    lines.append(
        "  Required: call "
        "mcp__agentic-memory__query_knowledge_graph(prompt=<task-specific>, workspace=<workspace>) "
        "with a prompt that names the target file or its substantive symbols"
    )
    if workspace_hint:
        lines.append(f"  Workspace (from ops/memory_manifest.yml): {workspace_hint}")
    else:
        lines.append(
            "  Workspace: not resolved — see ops/memory_manifest.yml and "
            "docs/00_Core/MEMORY_CONTRACT.md § What happens when something goes wrong"
        )
    lines.append("  Kill-switch: set CLAUDE_MEMORY_GATE=0 (surface why in vault SAVE)")
    sys.stderr.write("\n".join(lines) + "\n")
    return 2


def _maybe_workspace_hint(lock: dict | None, missing_marker: dict | None) -> str | None:
    if isinstance(lock, dict) and isinstance(lock.get("workspace"), str):
        return lock["workspace"]
    if isinstance(missing_marker, dict) and isinstance(missing_marker.get("hint"), str):
        return missing_marker["hint"]
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 — fail-open
        return 0
    if not _gate_enabled():
        return 0
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_name = payload.get("tool_name") or payload.get("name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    paths = _extract_touched_paths(tool_name, tool_input)
    if not paths:
        return 0  # no file/path → nothing to gate (e.g. `gh pr view`)

    root = _repo_root()
    rel_paths = [_to_repo_relative(p, root) for p in paths]
    code_paths = [p for p in rel_paths if _classify(p, root=root) == "code"]
    if not code_paths:
        return 0  # all touches are doc/other — allowed

    lock_path, missing_path = _lock_paths(root)
    lock = _read_lock(lock_path)
    missing = _read_lock(missing_path)

    # Degraded mode: SessionStart prefetch said no workspace registered for this
    # repo. Warn once on stderr and allow — the right fix is to register the
    # workspace via PR C, not to break developer flow.
    if missing:
        sys.stderr.write(
            "WARN  hook_memory_gate.py: degraded — Tier-3 prefetch unavailable "
            f"for {root} (see ops/memory_manifest.yml). "
            "Code-path edits allowed; register or provision the workspace.\n"
        )
        return 0

    workspace_hint = _maybe_workspace_hint(lock, missing)

    if not lock:
        return _emit_block(
            root=root,
            paths=code_paths,
            workspace_hint=workspace_hint,
            reason="no lockfile — SessionStart prefetch did not run",
        )

    if not _lock_is_fresh(lock, _ttl_seconds()):
        return _emit_block(
            root=root,
            paths=code_paths,
            workspace_hint=workspace_hint,
            reason=(
                "lockfile is stale (older than CLAUDE_MEMORY_GATE_TTL_SECONDS, "
                f"default {_DEFAULT_TTL_SECONDS}s)"
            ),
        )

    # Issue #115 council review: lockfile must certify cognition, not just
    # ritual. Verify the substrate response body has token overlap with the
    # file(s) being edited; an agent who queried `"x"` and got nothing back
    # cannot pass this check.
    relevant, why_not = _lock_is_relevant(lock, code_paths)
    if not relevant:
        return _emit_block(
            root=root,
            paths=code_paths,
            workspace_hint=workspace_hint,
            reason=why_not,
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — last-resort fail-open
        sys.exit(0)
