#!/usr/bin/env bash
# Baseline copilot harness smoke (issue #154 Part C) — the council-grade "baseline" check.
#
# Boots a loopback ai_sidecar, drives it with the headless harness client, and asserts the
# deterministic coaching rubric (reference lap -> no improvementRanking; slower lap ->
# ordered improvementRanking). Cleans up the sidecar on exit. Exit 0 = PASS.
#
# No Assetto Corsa, no Windows box, no human: this is the agent's L1 self-test of the
# sidecar coaching contract. Run via `make ci-drive`.
set -euo pipefail

PYTHON="${PYTHON:-python3}"
PORT="${AC_HARNESS_PORT:-8771}"
URL="ws://127.0.0.1:${PORT}"

# Deterministic coaching: keep the Ollama debrief OFF so the wire payload is stable.
unset AC_COPILOT_OLLAMA_ENABLE 2>/dev/null || true

echo "[baseline] starting sidecar on ${URL}"
"${PYTHON}" -m tools.ai_sidecar --host 127.0.0.1 --port "${PORT}" &
SIDECAR_PID=$!

cleanup() {
  kill "${SIDECAR_PID}" 2>/dev/null || true
  wait "${SIDECAR_PID}" 2>/dev/null || true
}
trap cleanup EXIT

# The harness client retries the initial connect, so no explicit readiness probe is
# needed; a brief head start just keeps the logs tidy.
sleep 0.5

echo "[baseline] injecting scenario via harness client"
if "${PYTHON}" -m tools.ai_sidecar.harness_client --url "${URL}" --inject baseline; then
  echo "[baseline] PASS"
  exit 0
fi
echo "[baseline] FAIL"
exit 1
