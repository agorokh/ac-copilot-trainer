#!/usr/bin/env bash
# Invoked from Makefile `ci-secrets`. Scans every tracked path with null-delimited args.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
py="${PYTHON:-python3}"
git ls-files -z | xargs -0 "$py" -m detect_secrets.pre_commit_hook --baseline .secrets.baseline
