#!/usr/bin/env bash
# governance-hub delivery shim: scripts/post_merge_sync.sh (governance-hub#886). DO NOT EDIT.
# OWNER: @agorokh
#
# The post-merge logic lives in the governance hub, not in this repository. This file runs the
# hub's scripts/post_merge_sync.sh from ${FLEET_GOVERNANCE_ROOT:-~/.fleet-governance}, so a fix
# lands once in the hub and reaches every repository with the next hub refresh. Repo-specific
# settings go in scripts/post_merge_sync.conf (keys listed at the top of the hub file).
# Conformance byte-audits this file; refresh it with the hub's scripts/fleet_reshim.py.
set -u
hub="${FLEET_GOVERNANCE_ROOT:-${HOME:-}/.fleet-governance}"
impl="$hub/scripts/post_merge_sync.sh"
if [ ! -f "$impl" ]; then
  if [ -d "$hub" ]; then
    echo "error: the governance hub at $hub predates the hub-owned post-merge helper (no $impl)." >&2
    echo "       Refresh it (make -C \"$hub\" hub-refresh), then re-run." >&2
  else
    echo "error: governance hub not found at $hub." >&2
    echo "       Clone agorokh/governance-hub there (or set FLEET_GOVERNANCE_ROOT), then re-run." >&2
  fi
  exit 20
fi
POST_MERGE_SYNC_SHIM="$0" exec bash "$impl" "$@"
