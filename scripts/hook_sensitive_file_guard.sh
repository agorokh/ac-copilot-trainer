#!/usr/bin/env bash
# PreToolUse:Edit|Write flow-control hook. Blocks edits to sensitive files.
#
# Input (stdin): Claude Code hook JSON: { "tool_input": { "file_path": "..." }, ... }
# Exit: 0 = allow; 2 = block.
#
# Blocked: .env (not .env.example), lockfiles, archive/, secrets/, private keys.
set -u

raw=$(cat)

PY=$(command -v python3 || command -v python || true)
[ -z "$PY" ] && exit 0

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
file_path=$(printf '%s' "$raw" | "$PY" "$HERE/hook_json_field.py" tool_input.file_path 2>/dev/null) || exit 0

[ -z "$file_path" ] && exit 0

# Normalize separators so Windows-style paths also match.
norm=$(printf '%s' "$file_path" | tr '\\' '/')
basename=${norm##*/}
# Case-insensitive match (Windows / mixed-case paths).
norm_lc=$(printf '%s' "$norm" | tr '[:upper:]' '[:lower:]')
basename_lc=$(printf '%s' "$basename" | tr '[:upper:]' '[:lower:]')

# 1. .env but not .env.example / .env.sample / .env.template
case "$basename_lc" in
  .env)
    printf 'BLOCK: %s is a secrets file\n' "$file_path" >&2
    exit 2
    ;;
  .env.example|.env.sample|.env.template)
    : # allow
    ;;
  .env.*)
    printf 'BLOCK: %s looks like an environment secrets file\n' "$file_path" >&2
    exit 2
    ;;
esac

# 2. Lockfiles (agents should regenerate via package manager).
case "$basename_lc" in
  poetry.lock|package-lock.json|pnpm-lock.yaml|yarn.lock|cargo.lock|pipfile.lock|uv.lock|\
  composer.lock|gemfile.lock|mix.lock|bun.lockb|pubspec.lock|go.sum|packages.lock.json|\
  npm-shrinkwrap.json|shrinkwrap.yaml)
    printf 'BLOCK: %s is a lockfile; regenerate via the package manager\n' "$file_path" >&2
    exit 2
    ;;
esac

# 3. SSH/PGP private keys.
case "$basename_lc" in
  id_rsa|id_ed25519|id_ecdsa)
    printf 'BLOCK: %s looks like an SSH private key\n' "$file_path" >&2
    exit 2
    ;;
esac
case "$basename_lc" in
  *.pem|*.key|*.pfx|*.p12)
    printf 'BLOCK: %s looks like a private key / certificate\n' "$file_path" >&2
    exit 2
    ;;
esac
# PGP armor under key material locations (avoid blocking AsciiDoc ``*.asc`` in docs).
case "$norm_lc" in
  */.gnupg/*.asc|.gnupg/*.asc|*/.ssh/*.asc|*/keys/*.asc|keys/*.asc)
    printf 'BLOCK: %s looks like armored key material\n' "$file_path" >&2
    exit 2
    ;;
esac
case "$basename_lc" in
  secring.asc|secring.gpg)
    printf 'BLOCK: %s looks like a secret keyring\n' "$file_path" >&2
    exit 2
    ;;
esac

# 4. Immutable archive / secrets directories.
case "$norm_lc" in
  */archive/*|archive/*|*/secrets/*|secrets/*|*/.secrets/*|.secrets/*|*/.ssh/*|.ssh/*)
    printf 'BLOCK: %s is under an immutable/secrets directory\n' "$file_path" >&2
    exit 2
    ;;
esac

exit 0
