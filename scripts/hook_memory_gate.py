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
  * **Bridge mismatch:** when that missing marker says ``gate_policy=block``
    (for example manifest workspace disabled or not visible in the active
    agentic-memory bridge provenance), the gate blocks code-path edits.

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

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ---------------------------------------------------------------------------
# Path policy
# ---------------------------------------------------------------------------

# Canonical default code-dir classification lives in hook_memory_manifest.py
# (single source of truth, shared with the prefetch). The gate reads per-repo
# overrides from the ``repo:`` block in ``ops/memory_manifest.yml`` — moved out
# of code so propagation can't clobber each child's project-specific dirs
# (council #180 fix; closes the wave-introduced enforcement regression).
# These module-level constants remain as ULTIMATE FALLBACK if manifest load
# fails entirely. ``noqa: E402`` — the import must follow the sys.path tweak
# above so hook_memory_manifest can be imported when this script is invoked
# directly by Claude Code's PreToolUse hook (not via ``python -m``).
from hook_memory_manifest import (  # noqa: E402
    DEFAULT_CODE_DIR_TOP_LEVEL,
    DEFAULT_CODE_PATH_PREFIXES,
    DEFAULT_CODE_PATH_TOP_LEVEL,
)

_CODE_PATH_PREFIXES: tuple[str, ...] = DEFAULT_CODE_PATH_PREFIXES
_CODE_PATH_TOP_LEVEL: frozenset[str] = DEFAULT_CODE_PATH_TOP_LEVEL
_CODE_DIR_TOP_LEVEL: frozenset[str] = DEFAULT_CODE_DIR_TOP_LEVEL

# NON-OVERRIDABLE gated paths — these always classify as "code" regardless of
# per-repo `repo.code_dirs` overrides. Qodo PR #194 security HIGH: an attacker
# (or careless override) could otherwise set `code_dirs: ["src"]` (omitting
# `ops/`) and editing `ops/memory_manifest.yml` (the gate's own config) would
# become ungated → exact Mistral bypass, reintroduced via overrides. Always-
# gating these closes that hole: the gate's own configuration files and CI
# workflows stay protected even if every other override is hostile.
_ALWAYS_GATED_PATHS: frozenset[str] = frozenset(
    {
        "ops/memory_manifest.yml",
        "ops/memory_manifest.local.yml",
        ".pre-commit-config.yaml",
    }
)
_ALWAYS_GATED_PREFIXES: tuple[str, ...] = (
    ".github/workflows/",  # CI config controls what runs on PRs
    ".github/actions/",
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
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)
# Top-level shell operators that separate commands in a compound line.
# Used by ``_bash_copy_move_destinations_any`` so a ``cp``/``mv`` that's not the
# very first token still gets caught (e.g. ``cd /tmp && cp foo scripts/bar``).
# Imperfect on operators inside quoted strings — false negatives there only mean
# the gate misses the segment, never over-blocks (issue #180 follow-up: the
# previous over-broad ``\bcp\b`` substring regex matched at quote boundaries
# inside ``--jq '"cp ..."'`` and false-blocked read-only commands).
_BASH_SEGMENT_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\||\bthen\b|\bdo\b|\bfi\b|\bdone\b)\s*")


# Common command-launcher wrappers that PREFIX the real command. We need to
# skip them so ``sudo cp foo bar`` / ``env cp foo bar`` / ``/bin/cp foo bar``
# still parse as cp (Qodo PR #194 HIGH + Cursor LOW — closing the wrapper
# bypass). Each wrapper may take its own flags before the real command.
_BASH_LEADING_WRAPPERS: frozenset[str] = frozenset(
    {
        "sudo",
        "env",
        "command",
        "exec",
        "nice",
        "ionice",
        "nohup",
        "time",
        "stdbuf",
        "doas",
        "xargs",  # `xargs cp ...` (with -I) — over-detect is OK, only triggers a stamp check
    }
)


def _bash_command_basename(token: str) -> str:
    """Return the basename of a command token, lowercased.

    ``/bin/cp`` → ``cp``; ``cp`` → ``cp``; ``/usr/bin/env`` → ``env``. Empty
    token → ``""``. Used so wrapper-skipping + cp/mv detection work on absolute
    paths as well as bare names (Qodo PR #194 HIGH).
    """
    if not token:
        return ""
    # Handle both / and \ for cross-platform robustness.
    return token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()


def _bash_copy_move_destinations(cmd: str) -> list[str]:
    """Return destination operand(s) for ``cp``/``mv`` (flags-aware, including ``-t``).

    Operates on a single segment. Strips leading wrappers (``sudo``, ``env``,
    ``command``, ``/usr/bin/env``, …) and matches on the BASENAME of the first
    real command token, so ``sudo cp …``, ``/bin/cp …``, and ``env -i cp …`` all
    resolve to ``cp`` (Qodo PR #194 / Cursor LOW). For compound commands
    (``cd /tmp && cp foo bar``), see ``_bash_copy_move_destinations_any`` which
    splits on top-level operators.
    """
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        return []
    if not parts:
        return []
    # Strip leading wrappers (sudo, env, …) and their own flags until we find
    # the real command name.
    i = 0
    while i < len(parts):
        basename = _bash_command_basename(parts[i])
        if basename in ("cp", "mv"):
            # Normalize: rewrite the first token to the bare basename so the
            # downstream logic doesn't need to re-strip wrappers/paths.
            parts = [basename] + parts[i + 1 :]
            break
        if basename in _BASH_LEADING_WRAPPERS:
            i += 1
            # Skip wrapper-level flags (e.g. ``sudo -E -u user``,
            # ``env -i FOO=bar``). Stop at first non-flag token (which is the
            # next loop iteration's command-name candidate).
            while i < len(parts) and parts[i].startswith("-"):
                i += 1
            # ``env`` accepts ``VAR=value`` before the command name — skip too.
            if basename == "env":
                while i < len(parts) and "=" in parts[i] and not parts[i].startswith("-"):
                    i += 1
            continue
        # Not a wrapper, not cp/mv — give up (this segment doesn't begin with
        # a cp/mv invocation we can analyze).
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


def _bash_copy_move_destinations_any(cmd: str) -> list[str]:
    """Collect ``cp``/``mv`` destinations from EVERY segment of a compound command.

    Splits on top-level shell operators (``;``, ``&&``, ``||``, ``|``) and runs the
    leading-token ``cp``/``mv`` parser on each segment. Replaces the prior
    ``_BASH_COPY_MOVE_VERB_RE = r"\\b(?:cp|mv)\\b"`` substring matcher whose
    word boundaries matched at quote characters and over-blocked benign reads
    like ``gh api --jq '... "cp" ...'`` (#180 / #188 hardening).
    """
    out: list[str] = []
    for segment in _BASH_SEGMENT_SPLIT_RE.split(cmd):
        seg = segment.strip()
        if not seg:
            continue
        out.extend(_bash_copy_move_destinations(seg))
    return out


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
_BASH_SYNTHETIC_CODE_PATH = "scripts/.bash_memory_gate_edit"

# ---------------------------------------------------------------------------
# Indirect-exec MUTATION detection (#180 / #188 council fix — only gate
# indirect-exec that actually MUTATES, so read-only one-liners like
# ``python -c "import json; print(json.load(open('x.json')))"`` don't brick
# agents on every repo. The prior "block all indirect-exec" policy was
# operationally too aggressive; the gate's purpose is forcing memory-grounding
# before *file mutations*, not arbitrary read computation.
# ---------------------------------------------------------------------------
_BASH_INDIRECT_EXEC_PIPE_TO_SHELL_RE = re.compile(
    r"(?:curl|wget|fetch)\s+[^|]*\|\s*(?:bash|sh|zsh|python3?)\b",
    re.IGNORECASE,
)
# Shell-context indirect-exec — the -c arg / heredoc body IS shell, so the
# shell-mutation regex applies (`>` redirects, `rm`, `mkdir`, etc. are mutations).
_BASH_INDIRECT_EXEC_SHELL_CONTEXT_RE = re.compile(
    r"""
    (?:
      \bbash\s+-c\b
    | \bzsh\s+-c\b
    | \bsh\s+-c\b
    | \beval\s+["'$]
    | <<\s*['"]?(?:EOF|PY|SH|BASH|HEREDOC)\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)
# Language-context mutation patterns (Python/Node/Deno/Perl/Ruby API surface).
# Applies to ANY indirect-exec. Distinct from shell patterns so the Python
# expression ``print(1 > 0)`` doesn't trigger the `>` redirect pattern (Cursor
# PR #194 HIGH) and the string method ``"x".replace("a","b")`` doesn't trigger
# the Path.replace pattern (Cursor PR #194 MEDIUM).
_INDIRECT_EXEC_LANG_MUTATION_RE = re.compile(
    r"""(?ix)
    (?:
      # ---- File-open in write/append/exclusive mode.
      # Positional: ``open(filename, 'w')`` / ``open('x', 'a+')``. REQUIRE the
      # comma so ``open("x")`` (read-only default) doesn't match — without the
      # comma, ``"x"`` looks like a single-char mode under the char class.
      \bopen\s*\([^,)]+,\s*['"][awx][+]?b?t?['"]
      # Keyword: ``open(filename, mode='w')`` / ``open(path, mode="a+")``.
    | \bopen\s*\([^)]*\bmode\s*=\s*['"][awx]
      # Perl-specific: ``open(F, ">file")`` / ``open(F, ">>file")`` — perl
      # encodes write mode with a leading ``>`` in the second arg. Distinct
      # from Python's ``print(1 > 0)`` because the perl form requires
      # ``open(`` first.
    | \bopen\s*\([^,)]+,\s*['"]>>?
      # ---- Python pathlib / file mutators.
      # NOTE: ``\.replace\s*\(`` is intentionally NOT here — it would match
      # ``str.replace()`` (extremely common). ``Path.replace()`` users should
      # use ``os.replace(...)`` (covered below by the os.* alternation).
    | \.write_text\s*\(
    | \.write_bytes\s*\(
    | \.writelines\s*\(
    | \.write\s*\(
    | \.touch\s*\(
    | \.mkdir\s*\(
    | \.unlink\s*\(
    | \.rename\s*\(
    | \.rmdir\s*\(
    | \.chmod\s*\(
    | \.symlink_to\s*\(
    | \.hardlink_to\s*\(
      # ---- os / shutil / tempfile mutators
    | \bos\.(?:remove|unlink|rename|replace|mkdir|makedirs|rmdir|chmod
            |symlink|link|truncate|fdopen|write)\s*\(
    | \bshutil\.(?:copy(?:[2y]|file|tree)?|move|rmtree|chown|copyfileobj)\s*\(
    | \btempfile\.(?:NamedTemporaryFile|mkstemp|mkdtemp)\s*\(
    | \bjson\.dump\s*\(
    | \bpickle\.dump\s*\(
    | \byaml\.dump\s*\(
      # ---- Dynamic-exec / evasion (we can't analyze further → conservative block).
      # Use negative lookbehind ``(?<!\.)`` on ``compile``/``eval``/``exec`` so
      # method calls (``re.compile(...)``, ``engine.execute(...)``, ``.eval(...)``
      # on numpy/pandas/sqlalchemy objects) DON'T false-match. Cursor PR #194
      # MEDIUM: ``re.compile(r"\\d+")`` was being blocked because ``\b`` fires
      # between ``.`` and ``c``. The Python builtins are bare (no leading dot);
      # the negative lookbehind preserves their detection without the false
      # positives on ubiquitous module-method calls.
    | \bsubprocess\.(?:run|call|Popen|check_call|check_output)\s*\(
    | \bos\.system\s*\(
    | \bos\.popen\s*\(
    | \b__import__\s*\(
    | (?<!\.)\bcompile\s*\(
    | (?<!\.)\beval\s*\(
    | (?<!\.)\bexec\s*\(
      # ---- Node.js fs writers. Match the METHOD name (without ``fs.`` prefix)
      # so ``require("fs").writeFileSync(...)`` is caught — ``fs.`` is not
      # contiguous when fs is imported inline.
    | \b(?:writeFile|writeFileSync|appendFile|appendFileSync
          |unlinkSync|rmSync|rmdirSync|mkdirSync|mkdirpSync
          |renameSync|copyFile|copyFileSync|symlinkSync|truncateSync
          |chmodSync|chownSync)\s*\(
    | \bDeno\.write(?:Text)?File(?:Sync)?\s*\(
    | \bDeno\.remove(?:Sync)?\s*\(
    )
    """,
)
# Shell-context mutation primitives — ONLY applied when the indirect-exec is in
# shell context (bash/zsh/sh -c, heredoc, or eval). Not applied to language
# -c/-e content because e.g. ``perl -e 'print 1 if $x > 5'`` is a comparison.
_INDIRECT_EXEC_SHELL_MUTATION_RE = re.compile(
    r"""(?ix)
    (?:
      # Redirection target must be PATH-LIKE — starts with /, ., or word char,
      # AND contains at least one path separator or extension dot. Excludes
      # bare numeric/word comparisons like ``> 0`` or ``> 5``.
      >[>]?\s*(?:["']?(?:/|\./|\.{1,2}/|[\w-]+\.[\w/.-]+|[\w/-]+/[\w/.-]+)|/dev/)
    | \brm\s+(?:-[a-zA-Z]+\s+)*\S+
    | \bmkdir\b\s+\S+
    | \btouch\b\s+\S+
    | \btee\b\s+
    | \bcp\b\s+\S+\s+\S+
    | \bmv\b\s+\S+\s+\S+
    | \bln\b\s+(?:-\S+\s+)?\S+\s+\S+
    | \bchmod\b\s+
    | \bchown\b\s+
    | \bsed\s+-i
    )
    """,
)


def _indirect_exec_is_mutation(cmd: str) -> bool:
    """Heuristic: True if the indirect-exec command appears to MUTATE state.

    The gate's purpose is forcing memory-grounding before file *mutations*;
    pure read-only one-liners (``python -c "import json; print(...)"``,
    ``node -e "1+1"``, ``perl -e 'print 1'``) shouldn't brick agents.
    Council #180/#188 / Mistral + Cursor PR #194 reviews: only gate indirect-
    exec that actually mutates, and distinguish SHELL context from LANGUAGE
    context so ``python -c "print(1 > 0)"`` isn't false-blocked by the shell
    redirect regex.

    Three paths to ``True``:

    * Pipe-to-shell (``curl … | bash``, ``wget … | sh``): remote content can
      do anything, so it is treated as mutation by default — bias toward
      blocking ambient remote-exec.
    * The command matches a LANGUAGE-API mutation primitive (file-open in
      write/append mode, ``.write_*``, ``os.remove``, ``shutil.copy``,
      Node ``fs.writeFile*``, dynamic-exec like ``eval`` / ``exec`` /
      ``__import__`` / ``subprocess.*`` / ``os.system``).
    * The command is in SHELL context (``bash -c``, ``zsh -c``, ``sh -c``,
      ``eval "…"``, or a heredoc) AND its content contains a shell mutation
      pattern (``>`` redirect to a path-like target, ``rm``, ``mkdir``, etc.).

    Shell-context detection is what lets ``python -c "print(1 > 0)"`` pass
    (no SHELL context → shell `>` regex never runs against it) while
    ``bash -c "rm scripts/x.py"`` still blocks.

    Bias: when in doubt about a dynamic-exec form, block — these are the routes
    a coding agent under pressure would use to bypass Edit/Write tools.
    """
    if _BASH_INDIRECT_EXEC_PIPE_TO_SHELL_RE.search(cmd):
        return True
    if _INDIRECT_EXEC_LANG_MUTATION_RE.search(cmd):
        return True
    if _BASH_INDIRECT_EXEC_SHELL_CONTEXT_RE.search(cmd) and (
        _INDIRECT_EXEC_SHELL_MUTATION_RE.search(cmd)
    ):
        return True
    return False


_DEFAULT_TTL_SECONDS = 1800  # 30 minutes
_LOCK_NAME = ".last_memory_query"
_LOCK_MISSING_NAME = ".last_memory_query.missing"


def _repo_root() -> Path:
    """Resolve to the main working directory, even from a git worktree.

    In a worktree, ``.git`` is a *file*, and ``Path.cwd()`` walks to the worktree
    path whose basename is a random slug — never matching manifest
    ``match_repo_basenames``. After locating any ``.git`` (or ``CLAUDE_PROJECT_DIR``),
    ask git for ``--git-common-dir`` so the workspace match in
    ``ops/memory_manifest.yml`` succeeds for both main and worktree sessions.
    Both ``hook_session_start_memory_prefetch.py`` and this gate must agree on
    the same root, since prefetch stamps and gate reads
    ``.scratch/.last_memory_query``.
    """
    from hook_repo_root import normalize_to_main_worktree_dir

    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        candidate_env = Path(env_root)
        if candidate_env.is_dir():
            return normalize_to_main_worktree_dir(candidate_env)
    here = Path.cwd().resolve()
    candidate: Path | None = None
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            candidate = parent
            break
    if candidate is None:
        return here
    return normalize_to_main_worktree_dir(candidate)


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


def _classify(
    path: str,
    *,
    root: Path | None = None,
    code_prefixes: tuple[str, ...] | None = None,
    code_top_level: frozenset[str] | None = None,
    code_dir_top_level: frozenset[str] | None = None,
) -> str:
    """Return ``"doc"``, ``"code"``, or ``"other"`` for a repo-relative path.

    The three ``code_*`` arguments override the module defaults — used by
    ``main()`` to pass per-repo overrides from the ``repo:`` block in
    ``ops/memory_manifest.yml``. ``None`` (the default) means "use module
    defaults" so callers/tests can keep the simple signature.
    """
    cp_prefixes = code_prefixes if code_prefixes is not None else _CODE_PATH_PREFIXES
    cp_top = code_top_level if code_top_level is not None else _CODE_PATH_TOP_LEVEL
    cd_top = code_dir_top_level if code_dir_top_level is not None else _CODE_DIR_TOP_LEVEL
    norm = _normalize_rel_path(path, root=root)
    if not norm:
        return "other"
    # Non-overridable gated paths take precedence over per-repo overrides
    # (Qodo PR #194 security HIGH — close the "shrink the allowlist" bypass).
    if norm in _ALWAYS_GATED_PATHS:
        return "code"
    for prefix in _ALWAYS_GATED_PREFIXES:
        if norm.startswith(prefix):
            return "code"
    # Top-level exact matches take precedence.
    if "/" not in norm:
        if norm in _DOC_PATH_TOP_LEVEL:
            return "doc"
        if norm in cp_top or norm in cd_top:
            return "code"
        # Other top-level files (e.g. ad-hoc scripts) — be conservative and treat as doc.
        return "doc"
    for prefix in _DOC_PATH_PREFIXES:
        if norm.startswith(prefix):
            return "doc"
    for prefix in cp_prefixes:
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


def _classify_root_for(touched_path: str, *, main_root: Path) -> Path:
    """Resolve the classification root for a single touched path.

    The memory gate normalizes its **lockfile** path to the main worktree (so
    SessionStart and the gate agree on one ``.scratch/.last_memory_query``).
    But path **classification** must happen against the file's OWN worktree
    root — an absolute path inside a linked git worktree (e.g. Claude Code's
    ``.claude/worktrees/<name>/scripts/foo.py``) cannot relativize to the main
    root, so ``_to_repo_relative`` falls back to the absolute string and
    ``_classify`` returns ``"other"`` → the gate skips a real code edit
    (Codex P1 finding from the #180 wave bot review; agent-factory
    ``worktree-memory-prefetch-bug-2026-05-19``).

    Relative paths and paths with no ``.git`` ancestor fall back to
    ``main_root``.
    """
    try:
        from hook_repo_root import worktree_root_for
    except ImportError:
        return main_root
    try:
        p = Path(touched_path)
    except (ValueError, OSError):
        return main_root
    if not p.is_absolute():
        return main_root
    wt = worktree_root_for(p)
    return wt if wt is not None else main_root


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
        # Drop the file extension: `gate.py` → `gate`.
        parts[-1] = parts[-1].rsplit(".", 1)[0]
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
        # Council #180/#188: only gate indirect-exec that actually MUTATES.
        # Allow read-only one-liners (``python -c "import json; print(...)"``);
        # block when the command has mutation primitives or pipes remote content
        # to a shell.
        indirect_exec_detected = bool(_BASH_INDIRECT_EXEC_RE.search(cmd))
        indirect_exec = indirect_exec_detected and _indirect_exec_is_mutation(cmd)
        # Compound-aware cp/mv detection — replaces the prior loose substring
        # regex that matched ``cp``/``mv`` inside quoted arguments and falsely
        # blocked benign read commands like ``gh api --jq '... "cp" ...'``.
        copy_dests = _bash_copy_move_destinations_any(cmd)
        copy_move = bool(copy_dests)
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

    root = _repo_root()  # main worktree — drives lockfile path
    # Classify each touched path against its OWN worktree root so an absolute
    # path inside a linked git worktree (Claude Code's
    # ``.claude/worktrees/<name>/scripts/foo.py``) is correctly classified as
    # ``"code"`` instead of falling back to ``"other"`` (Codex P1 from #180 wave).
    # Per-repo manifest data drives the code_dirs allowlist (council #180 fix)
    # so propagation can't clobber each child's project-specific dirs. Cache
    # the classifier overrides per worktree root within this single invocation.
    classifier_cache: dict[Path, tuple[tuple[str, ...], frozenset[str], frozenset[str]]] = {}

    def _classifier_for(
        classify_root: Path,
    ) -> tuple[tuple[str, ...], frozenset[str], frozenset[str]]:
        cached = classifier_cache.get(classify_root)
        if cached is not None:
            return cached
        try:
            from hook_memory_manifest import (
                load_manifest,
                repo_code_dir_top_level,
                repo_code_path_prefixes,
                repo_code_path_top_level,
            )

            manifest = load_manifest(classify_root)
            triple = (
                repo_code_path_prefixes(manifest),
                repo_code_path_top_level(manifest),
                repo_code_dir_top_level(manifest),
            )
        except Exception:  # noqa: BLE001 — fall back to hardcoded defaults
            triple = (_CODE_PATH_PREFIXES, _CODE_PATH_TOP_LEVEL, _CODE_DIR_TOP_LEVEL)
        classifier_cache[classify_root] = triple
        return triple

    code_paths: list[str] = []
    for raw_path in paths:
        classify_root = _classify_root_for(raw_path, main_root=root)
        rel = _to_repo_relative(raw_path, classify_root)
        cp_prefixes, cp_top, cd_top = _classifier_for(classify_root)
        if (
            _classify(
                rel,
                root=classify_root,
                code_prefixes=cp_prefixes,
                code_top_level=cp_top,
                code_dir_top_level=cd_top,
            )
            == "code"
        ):
            code_paths.append(rel)
    if not code_paths:
        return 0  # all touches are doc/other — allowed

    lock_path, missing_path = _lock_paths(root)
    lock = _read_lock(lock_path)
    missing = _read_lock(missing_path)

    # Degraded mode: no manifest workspace is a bootstrap warning, but a
    # registered workspace that failed prefetch is a hard memory-gate failure.
    if missing:
        ws = missing.get("workspace") if isinstance(missing, dict) else None
        registered_ws = ws.strip() if isinstance(ws, str) else ""
        gate_policy = missing.get("gate_policy") if isinstance(missing, dict) else None
        # A timeout-origin marker (gate_policy == "warn") means the substrate is healthy
        # but slow — never hard-block on a mere prefetch timeout, even for a registered
        # workspace (agorokh/workstation-ops#128 rec 2). A genuine outage (registered_ws
        # with no warn policy) or a bridge mismatch (gate_policy == "block") still blocks.
        if gate_policy != "warn" and (registered_ws or gate_policy == "block"):
            return _emit_block(
                root=root,
                paths=code_paths,
                workspace_hint=registered_ws or _maybe_workspace_hint(lock, missing),
                reason=(
                    str(missing.get("reason") or "registered Tier-3 workspace is unavailable")
                    + ". Fix the active agentic-memory registry/allowlist before code-path edits."
                ),
            )
        if gate_policy == "warn":
            # Stale warn marker can coexist if unlink failed after a later successful
            # prefetch — honor a fresh lock instead of skipping relevance checks.
            # But if the warn marker is newer than the lock, the most recent prefetch
            # timed out, so we degrade to warn-only even if the leftover lock is within TTL.
            warn_is_newer = lock and str(missing.get("timestamp_utc", "")) > str(
                lock.get("timestamp_utc", "")
            )
            if not lock or not _lock_is_fresh(lock, _ttl_seconds()) or warn_is_newer:
                sys.stderr.write(
                    "WARN  hook_memory_gate.py: degraded (warn-only) — Tier-3 prefetch "
                    f"timed out for {root}: {missing.get('reason') or 'substrate slow'}. "
                    "Code-path edits allowed; query Tier-3 manually to ground this session.\n"
                )
                return 0
        elif str(missing.get("reason") or "") == "accepted_gap":
            # A recorded resolution_exceptions gap is known and accepted — the
            # SessionStart NOTE already surfaced the tracking issue. Degrade
            # *quietly* (no "register or provision" nudge) per the manifest
            # contract, so it does not become recurring noise (Qodo review,
            # PR #175). Code-path edits allowed.
            sys.stderr.write(
                "WARN  hook_memory_gate.py: accepted Tier-3 gap (see SessionStart "
                f"NOTE) for {root}; code-path edits allowed.\n"
            )
            return 0
        else:
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
