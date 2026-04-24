"""stdin: Claude hook JSON; exit 0 allow, 2 block. Invoked by hook_protect_main.sh."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master", "refs/heads/main", "refs/heads/master"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPER_ONE_OFF = frozenset(
    {
        "-i",
        "--ignore-environment",
        "-E",
        "-H",
        "-P",
        "-S",
        "-n",
        "-A",
        "-b",
        "--preserve-env",
        "--login",
    }
)
# ``&`` alone is background; ``2>&1`` stays one shlex token. ``&&`` is a distinct token.
_CHAIN_TOKENS = frozenset({"&&", "||", "|", ";", "&"})
# ``bash -c 'git push …'`` must be inspected (Codex / PR #92).
_SHELL_BOOTSTRAP = frozenset({"bash", "sh", "dash", "zsh"})
_MAX_TEXT_DEPTH = 5
# Stay below outer hook budget (typically 5000ms) so symbolic-ref can finish cleanly.
_GIT_HEAD_TIMEOUT_SEC = 3
# ``echo ok;git`` / ``ok&&git`` / ``ok||git`` → one shlex token; split before path/git suffix.
_GLUE_BEFORE_GIT = re.compile(r"(?:;|\|\||&&)(?=.*\bgit\b)")
# Mid-argv bare ``git`` is a real command only when glued to prior text (not ``echo git`` words).
_LINE_GLUES_TO_GIT = re.compile(r"(?:;|\|\||&&)\s*git\b")
# ``bash -xc '…'`` == ``bash -x -c '…'``; ``-c`` must not require a standalone argv token.
_BUNDLED_SHELL_C = re.compile(r"^-[A-Za-z]*c$")


def _shell_git_executable_peeled(tok: str) -> str:
    r"""Strip subshell ``(``, ``$(``, or backtick-wrapped command starts so argv0 can be ``git``."""
    t = tok.strip().lstrip("(")
    if t.startswith("$("):
        t = t[2:].lstrip().lstrip("(")
    elif t.startswith("`"):
        t = t[1:].lstrip().lstrip("(")
    return t


def _normalize_shell_git_argv_edges(args: list[str]) -> None:
    r"""Normalize shlex edges for ``(git …)``, ``$(git …)``, and backtick-wrapped ``git``."""
    if not args:
        return
    args[0] = _shell_git_executable_peeled(args[0])
    args[-1] = args[-1].rstrip(")").rstrip("`")


def _apply_export_segment(tokens: list[str], env: dict[str, str]) -> bool:
    """Handle ``export VAR=val`` segments so later ``git`` sees the same env (Codex)."""
    if not tokens or tokens[0] != "export":
        return False
    for raw in tokens[1:]:
        if raw in ("-n", "-p", "-f"):
            continue
        if ASSIGN_RE.match(raw):
            k, _, v = raw.partition("=")
            env[k] = v
    return True


def _odd_trailing_backslashes(line: str) -> bool:
    """True when the line ends with an odd count of ``\\`` (last one escapes the newline)."""
    s = line.rstrip()
    k = 0
    while s.endswith("\\"):
        s = s[:-1]
        k += 1
    return k % 2 == 1


def _merge_shell_continuations(text: str) -> str:
    """Join bash line continuations; even trailing ``\\`` means no join (Codex)."""
    parts = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(parts):
        cur = parts[i]
        while _odd_trailing_backslashes(cur) and i + 1 < len(parts):
            i += 1
            cur = cur.rstrip()[:-1] + parts[i].lstrip()
        out.append(cur)
        i += 1
    return "\n".join(out)


def _logical_shell_lines(text: str) -> list[str]:
    """Split on newlines outside quotes so ``bash -c '…\\n…'`` stays one line (Codex)."""
    lines: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    in_single = in_double = False
    escape = False
    while i < n:
        ch = text[i]
        if escape:
            buf.append(ch)
            escape = False
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == "\\":
                escape = True
                buf.append(ch)
                i += 1
                continue
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
        elif ch == '"':
            in_double = True
            buf.append(ch)
        elif ch == "\n":
            piece = "".join(buf).strip()
            if piece:
                lines.append(piece)
            buf.clear()
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        lines.append(tail)
    return lines


def _expand_glue_before_git_tokens(tokens: list[str]) -> list[str]:
    """Split tokens where ``;``, ``&&``, or ``||`` hides a later ``…git…`` path (Codex / Bugbot)."""
    out: list[str] = []
    for t in tokens:
        if not _GLUE_BEFORE_GIT.search(t):
            out.append(t)
            continue
        start = 0
        for m in _GLUE_BEFORE_GIT.finditer(t):
            chunk = t[start : m.start()].strip()
            if chunk:
                try:
                    out.extend(shlex.split(chunk))
                except ValueError:
                    out.append(chunk)
            start = m.end()
        tail = t[start:].lstrip()
        if tail:
            try:
                out.extend(shlex.split(tail))
            except ValueError:
                out.append(tail)
    return out


def _peel_shell_prefix(tokens: list[str], env: dict[str, str]) -> list[str]:
    """Interleaved VAR=value, env/sudo wrappers, and common flags until argv0 is `git`."""
    t = list(tokens)
    while t:
        if ASSIGN_RE.match(t[0]):
            k, _, v = t[0].partition("=")
            env[k] = v
            t.pop(0)
            continue
        if t[0] in ("sudo", "nice", "env", "command", "time"):
            t.pop(0)
            continue
        if t[0] in ("-u", "--user") and len(t) >= 2:
            t = t[2:]
            continue
        if t[0] in _WRAPPER_ONE_OFF:
            t.pop(0)
            continue
        break
    return t


def _shell_argv0_basename(argv0: str) -> str:
    return os.path.basename(argv0).lower()


def _token_looks_like_git_executable(tok: str) -> bool:
    r"""True when token is (or begins with) a ``git`` executable after shell peels."""
    t = _shell_git_executable_peeled(tok).rstrip(")").rstrip("`")
    return _shell_argv0_basename(t) == "git"


def _shell_command_segments(tokens: list[str]) -> list[list[str]]:
    """Split shlex tokens on common shell chain operators (one segment ≈ one command)."""
    segs: list[list[str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            segs.append(buf[:])
            buf.clear()

    for t in tokens:
        if t in _CHAIN_TOKENS:
            flush()
            continue
        # Do not split on ``;`` inside a single shlex token (quoted ``git -c "a;b"``).
        # Only peel ``word;`` glue (e.g. ``echo hi;`` → ``hi`` then break segment).
        if len(t) > 1 and t.endswith(";"):
            piece = t[:-1].strip()
            if piece:
                buf.append(piece)
            flush()
            continue
        buf.append(t)
    flush()
    return [s for s in segs if s]


def _after_git_globals(args: list[str], git_idx: int) -> int:
    j = git_idx + 1
    n = len(args)
    while j < n:
        tok = args[j]
        if tok in ("-C", "-c"):
            if j + 1 >= n:
                return j
            j += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:
            j += 1
            continue
        if tok.startswith("-c") and len(tok) > 2:
            j += 1
            continue
        if tok.startswith(("--git-dir=", "--work-tree=", "--namespace=")):
            j += 1
            continue
        if tok in ("--git-dir", "--work-tree", "--namespace"):
            if j + 1 >= n:
                return j
            j += 2
            continue
        if tok.startswith("-"):
            j += 1
            continue
        break
    return j


def _push_refs_start(tail: list[str]) -> int:
    """Skip git-push options; return index of first ref-ish token."""
    i = 0
    n = len(tail)
    while i < n:
        a = tail[i]
        if a == "--":
            return i + 1
        if not a.startswith("-"):
            break
        if "=" in a:
            i += 1
            continue
        # Value-taking options that exist on `git push` (avoid phantom flags).
        if a in ("-o", "--push-option", "--repo") and i + 1 < n:
            i += 2
            continue
        i += 1
    return i


def _first_token_is_remote_repository(refs: list[str]) -> bool:
    """True when argv shape is ``git push <remote> <refspec>...`` (not all-refspec form).

    A remote named ``main``/``master`` must not be scanned as a push target; only
    refspec tokens after the repository token are checked for protected refs.
    """
    if len(refs) < 2:
        return False
    first = refs[0]
    if ":" not in first:
        return True
    if "://" in first or first.startswith("git@"):
        return True
    return False


def _single_arg_is_repository_without_refspec(tok: str) -> bool:
    """True for lone ``git push git@host:path`` / ``https://...`` (not ``src:dst`` refspec)."""
    if "://" in tok or tok.startswith("git@"):
        return True
    if tok.endswith(".git") and (tok.startswith(("./", "../", "/", "~/")) or "/" in tok):
        return True
    return False


def _git_argv_has_alias_c(args: list[str], end: int) -> bool:
    """True when a ``-c`` value defines an ``alias.*`` (Codex)."""
    i = 1
    while i < end:
        if args[i] == "-c" and i + 1 < end:
            if "alias." in args[i + 1]:
                return True
            i += 2
            continue
        tok = args[i]
        if tok.startswith("-c") and len(tok) > 2 and "alias." in tok[2:]:
            return True
        i += 1
    return False


def _remoteish_git_push_target(tok: str) -> bool:
    return tok in ("origin", "upstream") or "://" in tok or tok.startswith("git@")


def _resolve_git_sub_with_inline_aliases(
    args: list[str], j: int, sub: str, tail: list[str]
) -> tuple[str, list[str]]:
    """Map ``git -c alias.*=…`` onto real subcommands for gating (Codex)."""
    if not _git_argv_has_alias_c(args, j):
        return sub, tail
    if sub in ("commit", "push"):
        return sub, tail
    if tail and (
        "-m" in tail
        or "--amend" in tail
        or "--no-edit" in tail
        or "--fixup" in tail
        or "--squash" in tail
    ):
        return "commit", tail
    if len(tail) >= 2 and not tail[0].startswith("-") and not tail[1].startswith("-"):
        return "push", tail
    if len(tail) >= 2 and _remoteish_git_push_target(tail[0]):
        return "push", tail
    return sub, tail


def _push_refspec_uncertain(tok: str) -> bool:
    """True when refspec may expand via shell, globs, or braces (Codex / #92)."""
    if "://" in tok or tok.startswith("git@"):
        return "$" in tok or "{" in tok
    if any(ch in tok for ch in "*?[{"):
        return True
    if "$" in tok or "{" in tok or "}" in tok:
        return True
    return False


def _inspect_one_shell_command(tokens: list[str], depth: int, shell_env: dict[str, str]) -> int:
    """Return 2 if this command segment must be blocked; 0 otherwise."""
    if depth > _MAX_TEXT_DEPTH:
        return 0
    args = _peel_shell_prefix(tokens, shell_env)
    if not args:
        return 0
    _normalize_shell_git_argv_edges(args)
    if not args or not args[0]:
        return 0

    base = _shell_argv0_basename(args[0])
    if base in _SHELL_BOOTSTRAP:
        for i in range(1, len(args) - 1):
            tok = args[i]
            if tok == "-c" or (
                tok.startswith("-") and not tok.startswith("--") and _BUNDLED_SHELL_C.match(tok)
            ):
                return _inspect_command_text(args[i + 1], depth=depth + 1, shell_env=shell_env)
        return 0

    if base != "git":
        return 0

    j = _after_git_globals(args, 0)
    if j >= len(args):
        return 0
    sub = args[j]
    tail = args[j + 1 :]
    if "$" in sub:
        sys.stderr.write(
            "BLOCK: refusing git with shell-expanded subcommand token (cannot resolve argv)\n"
        )
        return 2
    sub, tail = _resolve_git_sub_with_inline_aliases(args, j, sub, tail)

    git_head_argv = args[0:j] + ["symbolic-ref", "--short", "HEAD"]
    try:
        r = subprocess.run(
            git_head_argv,
            capture_output=True,
            text=True,
            timeout=_GIT_HEAD_TIMEOUT_SEC,
            env=shell_env,
        )
    except (FileNotFoundError, OSError) as exc:
        sys.stderr.write(
            f"BLOCK: unable to run git for HEAD probe ({exc}); refusing guarded git {sub}\n"
        )
        return 2
    branch = r.stdout.strip() if r.returncode == 0 else ""

    if branch in ("main", "master") and sub in ("commit", "push"):
        sys.stderr.write(f"BLOCK: refusing git {sub} while HEAD is on protected branch {branch}\n")
        return 2

    if sub != "push":
        return 0

    if any(f in tail for f in ("--all", "--mirror")):
        sys.stderr.write("BLOCK: refusing push with --all/--mirror (may update main/master)\n")
        return 2

    i = _push_refs_start(tail)
    refs = tail[i:]

    if not refs:
        sys.stderr.write("BLOCK: refusing git push without explicit destination refs\n")
        return 2
    if len(refs) == 1:
        r0 = refs[0]
        if ":" not in r0:
            sys.stderr.write(
                "BLOCK: refusing git push with a single remote-only ref (no explicit refspec)\n"
            )
            return 2
        if _single_arg_is_repository_without_refspec(r0):
            sys.stderr.write(
                "BLOCK: refusing git push with only a repository (no explicit refspec)\n"
            )
            return 2

    push_refs = refs[1:] if _first_token_is_remote_repository(refs) else refs
    for arg in push_refs:
        if _push_refspec_uncertain(arg):
            sys.stderr.write(
                "BLOCK: refusing push refspec with glob or shell variable "
                "(cannot prove destination is not main/master)\n"
            )
            return 2
        src, sep, dst = arg.partition(":")
        target = (dst if dst else src).lstrip("+")
        if target in PROTECTED:
            sys.stderr.write("BLOCK: refusing push targeting protected branch main/master\n")
            return 2

    return 0


def _segment_targets_git_commit(tokens: list[str], shell_env: dict[str, str], depth: int) -> bool:
    """True when this argv segment is (or recursively invokes) ``git … commit``."""
    if depth > _MAX_TEXT_DEPTH:
        return False
    args = _peel_shell_prefix(list(tokens), shell_env)
    if not args:
        return False
    _normalize_shell_git_argv_edges(args)
    if not args or not args[0]:
        return False
    base = _shell_argv0_basename(args[0])
    if base in _SHELL_BOOTSTRAP:
        for i in range(1, len(args) - 1):
            tok = args[i]
            if tok == "-c" or (
                tok.startswith("-") and not tok.startswith("--") and _BUNDLED_SHELL_C.match(tok)
            ):
                return command_includes_git_commit_intent(
                    args[i + 1], depth=depth + 1, shell_env=shell_env
                )
        return False
    if base != "git":
        return False
    j = _after_git_globals(args, 0)
    if j >= len(args):
        return False
    sub = args[j]
    tail = args[j + 1 :]
    sub, _tail = _resolve_git_sub_with_inline_aliases(args, j, sub, tail)
    return sub == "commit"


def _may_contain_embedded_git_invoke(seg: list[str]) -> bool:
    """True when argv0 can spawn nested commands (shell, git, etc.)."""
    if not seg:
        return False
    t0 = _shell_git_executable_peeled(seg[0]).rstrip(")").rstrip("`")
    p0 = _shell_argv0_basename(t0)
    return p0 in _SHELL_BOOTSTRAP or p0 == "git"


def _line_has_glued_git_command(line: str) -> bool:
    if _LINE_GLUES_TO_GIT.search(line):
        return True
    if "$(git" in line or "`git" in line:
        return True
    return False


def _git_token_needs_mid_invoke_scan(tok: str) -> bool:
    """Bare ``git`` as an argument to ``echo`` is not a command; ``$(git`` is (Codex)."""
    if not _token_looks_like_git_executable(tok):
        return False
    tn = tok.strip().strip("'\"")
    if tn == "git":
        return False
    return True


def command_includes_git_commit_intent(
    cmd: str, *, depth: int = 0, shell_env: dict[str, str] | None = None
) -> bool:
    """Orchestrator helper: true only when parsed argv includes a ``git commit`` (Qodo / #92)."""
    if depth > _MAX_TEXT_DEPTH:
        return False
    if shell_env is None:
        shell_env = dict(os.environ)
    cmd = _merge_shell_continuations(cmd)
    lines = _logical_shell_lines(cmd)
    if not lines:
        return False
    for line in lines:
        try:
            tokens = _expand_glue_before_git_tokens(shlex.split(line))
        except Exception:
            if "git" in line.casefold():
                sys.stderr.write(
                    "hook_protect_main: shlex.split failed (fail-open); command contains 'git'\n"
                )
            continue
        glued_git = _line_has_glued_git_command(line)
        for seg in _shell_command_segments(tokens):
            if _apply_export_segment(seg, shell_env):
                continue
            if _segment_targets_git_commit(seg, shell_env, depth):
                return True
            for i in range(1, len(seg)):
                if not _token_looks_like_git_executable(seg[i]):
                    continue
                if not (
                    _may_contain_embedded_git_invoke(seg)
                    or _git_token_needs_mid_invoke_scan(seg[i])
                    or (glued_git and _shell_argv0_basename(seg[i]) == "git")
                ):
                    continue
                if _segment_targets_git_commit(seg[i:], shell_env, depth):
                    return True
    return False


def _inspect_command_text(
    cmd: str, *, depth: int = 0, shell_env: dict[str, str] | None = None
) -> int:
    """Walk logical lines and segments; block if any subshell command hits protected git."""
    if depth > _MAX_TEXT_DEPTH:
        return 0
    if shell_env is None:
        shell_env = dict(os.environ)
    cmd = _merge_shell_continuations(cmd)
    lines = _logical_shell_lines(cmd)
    if not lines:
        return 0
    for line in lines:
        try:
            tokens = _expand_glue_before_git_tokens(shlex.split(line))
        except Exception:
            if "git" in line.casefold():
                sys.stderr.write(
                    "hook_protect_main: shlex.split failed (fail-open); command contains 'git'\n"
                )
            continue
        glued_git = _line_has_glued_git_command(line)
        for seg in _shell_command_segments(tokens):
            if _apply_export_segment(seg, shell_env):
                continue
            rc = _inspect_one_shell_command(seg, depth, shell_env)
            if rc == 2:
                return rc
            for i in range(1, len(seg)):
                if not _token_looks_like_git_executable(seg[i]):
                    continue
                if not (
                    _may_contain_embedded_git_invoke(seg)
                    or _git_token_needs_mid_invoke_scan(seg[i])
                    or (glued_git and _shell_argv0_basename(seg[i]) == "git")
                ):
                    continue
                rc2 = _inspect_one_shell_command(seg[i:], depth, shell_env)
                if rc2 == 2:
                    return rc2
    return 0


def main() -> int:
    raw = sys.stdin.read()
    try:
        d = json.loads(raw)
    except Exception:
        return 0
    cmd = (d.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return 0
    return _inspect_command_text(cmd, depth=0)


if __name__ == "__main__":
    sys.exit(main())
