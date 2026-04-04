"""Local Ollama HTTP debrief + rules fallback (issue #46).

Opt-in via ``AC_COPILOT_OLLAMA_ENABLE=1``. Default is off: no ``debrief`` field on
``coaching_response``. When enabled, the sidecar always attaches a ``debrief`` string
(rules-only if Ollama is unreachable).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_ENV_ENABLE = "AC_COPILOT_OLLAMA_ENABLE"
_ENV_HOST = "AC_COPILOT_OLLAMA_HOST"
_ENV_MODEL = "AC_COPILOT_OLLAMA_MODEL"
_ENV_TEMP = "AC_COPILOT_OLLAMA_TEMPERATURE"
_ENV_TOKENS = "AC_COPILOT_OLLAMA_NUM_PREDICT"
_ENV_TIMEOUT = "AC_COPILOT_OLLAMA_TIMEOUT_SEC"

# Documented in WARP.md — tested against Ollama 0.5.x API; pin locally for support.
_DEFAULT_MODEL = "llama3.2"
_DEFAULT_HOST = "http://127.0.0.1:11434"
_DEFAULT_TEMPERATURE = 0.35
_DEFAULT_NUM_PREDICT = 320
_DEFAULT_TIMEOUT_SEC = 45.0


def debrief_feature_enabled() -> bool:
    v = (os.environ.get(_ENV_ENABLE) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def ollama_base_url() -> str:
    return (os.environ.get(_ENV_HOST) or _DEFAULT_HOST).strip().rstrip("/")


def ollama_model() -> str:
    return (os.environ.get(_ENV_MODEL) or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def read_generation_options() -> tuple[float, int, float]:
    """temperature, num_predict, timeout_sec."""
    t = _float_env(_ENV_TEMP, _DEFAULT_TEMPERATURE)
    n = _int_env(_ENV_TOKENS, _DEFAULT_NUM_PREDICT)
    timeout = _float_env(_ENV_TIMEOUT, _DEFAULT_TIMEOUT_SEC)
    t = max(0.0, min(2.0, t))
    n = max(64, min(4096, n))
    timeout = max(5.0, min(300.0, timeout))
    return t, n, timeout


def _lap_time_s(lap_time_ms: Any) -> str | None:
    if lap_time_ms is None or isinstance(lap_time_ms, bool):
        return None
    try:
        ms = int(lap_time_ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return f"{ms / 1000:.3f}"


def _hints_lines(inbound: dict[str, Any]) -> list[str]:
    raw = inbound.get("coachingHints")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= 8:
            break
    return out


def rules_fallback_debrief(
    inbound: dict[str, Any],
    improvement_ranking: list[dict[str, Any]],
) -> str:
    """Deterministic paragraph(s) from lap metadata + ranking + hints."""
    lap = inbound.get("lap")
    lap_s = _lap_time_s(inbound.get("lapTimeMs"))
    parts: list[str] = []
    head = "Post-lap debrief"
    if lap is not None and lap_s:
        head = f"Post-lap debrief (lap {lap}, {lap_s} s)"
    elif lap is not None:
        head = f"Post-lap debrief (lap {lap})"
    elif lap_s:
        head = f"Post-lap debrief ({lap_s} s)"

    hints = _hints_lines(inbound)
    if hints:
        parts.append(
            f"{head}. Focus areas from on-track coaching: "
            + "; ".join(hints[:3])
            + ("." if len(hints) <= 3 else " …")
        )
    else:
        parts.append(
            f"{head}. Keep building consistent laps; add telemetry-rich laps so the sidecar "
            "can rank corners against your session reference."
        )

    if improvement_ranking:
        top = improvement_ranking[:3]
        lines = [str(item.get("suggestion") or "").strip() for item in top]
        lines = [x for x in lines if x]
        if lines:
            parts.append(
                "Compared with your best analyzed lap in this connection, priority gaps: "
                + "; ".join(lines)
                + "."
            )
    else:
        parts.append(
            "No corner-level delta vs session reference yet — send laps with corner telemetry "
            "for ranked improvement hints alongside this debrief."
        )

    text = "\n\n".join(parts)
    return _sanitize_debrief(text)


_WS_RE = re.compile(r"\s+")


def _sanitize_debrief(text: str) -> str:
    t = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in t.split("\n"):
        lines.append(_WS_RE.sub(" ", line.strip()))
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def build_llm_prompt(inbound: dict[str, Any], improvement_ranking: list[dict[str, Any]]) -> str:
    """Structured prompt for Ollama (no chain-of-thought; concise instructions)."""
    lap = inbound.get("lap")
    lap_s = _lap_time_s(inbound.get("lapTimeMs"))
    hints = _hints_lines(inbound)
    rank_lines = [
        str(item.get("suggestion") or "").strip()
        for item in improvement_ranking[:6]
        if str(item.get("suggestion") or "").strip()
    ]
    payload = {
        "lap": lap,
        "lap_time_s": lap_s,
        "coaching_hints": hints,
        "improvement_suggestions": rank_lines,
    }
    rules = rules_fallback_debrief(inbound, improvement_ranking)
    return (
        "You are a concise sim-racing coach for Assetto Corsa practice laps.\n"
        "Use ONLY the JSON facts below. Write one or two short paragraphs "
        "(no bullet lists, no markdown headings). Be constructive and specific.\n\n"
        f"FACTS_JSON:\n{json.dumps(payload, indent=2)}\n\n"
        f"If facts are thin, you may restate this fallback summary in smoother prose:\n{rules}\n"
    )


def call_ollama_generate(
    prompt: str,
    *,
    base_url: str,
    model: str,
    temperature: float,
    num_predict: int,
    timeout_sec: float,
) -> str | None:
    """POST /api/generate; returns assistant text or None on failure."""
    url = f"{base_url}/api/generate"
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Local Ollama only; URL from AC_COPILOT_OLLAMA_HOST (default 127.0.0.1:11434).
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec B310
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.info("ollama generate failed: %s", e)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("ollama generate: invalid JSON response")
        return None
    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        return None
    return _sanitize_debrief(text)


def compose_debrief(
    inbound: dict[str, Any],
    improvement_ranking: list[dict[str, Any]],
) -> str | None:
    """Full debrief for ``coaching_response`` when feature enabled; else None."""
    if not debrief_feature_enabled():
        return None
    rules = rules_fallback_debrief(inbound, improvement_ranking)
    base = ollama_base_url()
    model = ollama_model()
    temp, n_pred, timeout = read_generation_options()
    prompt = build_llm_prompt(inbound, improvement_ranking)
    llm = call_ollama_generate(
        prompt,
        base_url=base,
        model=model,
        temperature=temp,
        num_predict=n_pred,
        timeout_sec=timeout,
    )
    if llm:
        return llm
    logger.info("ollama unreachable or empty; using rules debrief")
    return rules
