"""Local Ollama HTTP debrief + rules fallback (issue #46).

Opt-in via ``AC_COPILOT_OLLAMA_ENABLE=1``. Default is off: no ``debrief`` field on
``coaching_response``. When enabled, the sidecar always attaches a ``debrief`` string
(rules-only if Ollama is unreachable).
"""

from __future__ import annotations

import http.client
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
_ENV_DEBRIEF_TIMEOUT = "AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC"

# Documented in WARP.md — tested against Ollama 0.5.x API; pin locally for support.
_DEFAULT_MODEL = "llama3.2"
_DEFAULT_HOST = "http://127.0.0.1:11434"
_DEFAULT_TEMPERATURE = 0.35
_DEFAULT_NUM_PREDICT = 320
_DEFAULT_TIMEOUT_SEC = 45.0
_DEFAULT_DEBRIEF_TIMEOUT_SEC = 12.0


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
    raw = (os.environ.get(_ENV_HOST) or "").strip()
    return (raw or _DEFAULT_HOST).rstrip("/")


def ollama_model() -> str:
    return (os.environ.get(_ENV_MODEL) or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def read_generation_options() -> tuple[float, int, float]:
    """temperature, num_predict, timeout_sec (generic upper bound)."""
    t = _float_env(_ENV_TEMP, _DEFAULT_TEMPERATURE)
    n = _int_env(_ENV_TOKENS, _DEFAULT_NUM_PREDICT)
    timeout = _float_env(_ENV_TIMEOUT, _DEFAULT_TIMEOUT_SEC)
    t = max(0.0, min(2.0, t))
    n = max(64, min(4096, n))
    timeout = max(5.0, min(300.0, timeout))
    return t, n, timeout


def read_debrief_ollama_timeout_sec() -> float:
    """Shorter cap for post-lap debrief so the sidecar answers before CSP coaching hold expires."""
    t = _float_env(_ENV_DEBRIEF_TIMEOUT, _DEFAULT_DEBRIEF_TIMEOUT_SEC)
    return max(2.0, min(45.0, t))


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
# Strip C0 controls except newline/tab (Lua ImGui text is sensitive to garbage bytes).
_CTRL_EXCEPT_NL_TAB = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MD_FENCE = re.compile(r"^```[a-zA-Z0-9]*\s*$", re.MULTILINE)


def _sanitize_debrief(text: str) -> str:
    t = text.strip().replace("\r\n", "\n").replace("\r", "\n")
    t = _CTRL_EXCEPT_NL_TAB.sub("", t)
    t = _MD_FENCE.sub("", t)
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
    raw = ""
    status: int | None = None
    try:
        base = base_url.rstrip("/")
        url = f"{base}/api/generate"
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"unsupported Ollama URL: {url!r}")
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
                # Round 9: pin model in Ollama memory for 30 minutes after
                # each call so subsequent lap_completes don't incur cold-load
                # latency (>30s). Default keep_alive is 5 min which can
                # expire mid-session if the user takes a break between laps.
                "keep_alive": "30m",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Local Ollama only; synchronous urllib (server runs this in asyncio.to_thread).
        # For heavy multi-client workloads, consider aiohttp/httpx async clients later.
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec B310
            status = resp.getcode()
            raw = resp.read().decode("utf-8", errors="replace")
    except (
        ValueError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
    ) as e:
        logger.info("ollama generate failed: %s", e)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        prefix = raw[:400].replace("\n", " ")
        logger.info(
            "ollama generate: invalid JSON (status=%s err=%s) body_prefix=%r",
            status,
            e,
            prefix,
        )
        return None
    if not isinstance(data, dict):
        logger.info(
            "ollama generate: expected JSON object, got %s",
            type(data).__name__,
        )
        return None
    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        logger.info(
            "ollama generate: missing/empty response field (status=%s keys=%s)",
            status,
            list(data.keys())[:8],
        )
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
    temp, n_pred, _ = read_generation_options()
    debrief_timeout = read_debrief_ollama_timeout_sec()
    prompt = build_llm_prompt(inbound, improvement_ranking)
    llm = call_ollama_generate(
        prompt,
        base_url=base,
        model=model,
        temperature=temp,
        num_predict=n_pred,
        timeout_sec=debrief_timeout,
    )
    if llm:
        return llm
    logger.info("ollama unreachable or empty; using rules debrief")
    return rules


def compose_corner_hint(
    corner: str,
    cur_kmh: float,
    ref_kmh: float,
    dist_m: float,
    car: str | None = None,
    track: str | None = None,
) -> str | None:
    """Round 10: real-time per-corner coaching hint (sub-1s).

    Called when the realtime engine detects the car transitioning to a new
    corner approach. Sends a TINY prompt to Ollama with just the corner
    label, current/target speeds, and distance — asks for one short
    actionable hint (max ~6 words). Total round-trip ~600-800ms with
    llama3.2:3b + keep_alive=30m (proven via direct benchmark: 631ms for
    "Reduce speed by 9 km/h.").

    Returns the hint text (short string, already sanitized) or None if
    Ollama failed. The Lua side falls back to the existing rules-engine
    secondary line when None.
    """
    if not debrief_feature_enabled():
        return None
    base = ollama_base_url()
    model = ollama_model()
    # Intentionally tight generation params for latency:
    # - num_predict = 20 (6-8 words max, trims eval_duration)
    # - temperature = 0.2 (more deterministic, fewer off-topic tokens)
    # - timeout = 10s (hard ceiling; 631ms is typical)
    delta = cur_kmh - ref_kmh
    abs_delta = abs(int(delta))
    over_under = "over" if delta > 0 else "under"
    prompt = (
        "You coach a driver in an Assetto Corsa race car. The car has ONE "
        "brake pedal that actuates all four wheels together. There is NO "
        "individual wheel control. Reply with ONE short racing command.\n"
        "\n"
        "RULES:\n"
        "- Max 8 words. Use UPPERCASE racing commands.\n"
        "- Use ONLY these verbs: BRAKE, LIFT, EASE, HOLD, TRAIL, CARRY, TURN, ACCELERATE.\n"
        "- NEVER mention front/rear/left/right brake (single pedal).\n"
        "- If current < target by 5+: tell them to ACCELERATE or HOLD THROTTLE.\n"
        "- If current > target by 5-15: BRAKE EARLIER or LIFT NOW.\n"
        "- If current > target by 15+: BRAKE HARD NOW.\n"
        "- If within 4 km/h of target: ON PACE or HOLD STEADY.\n"
        "\n"
        "EXAMPLES:\n"
        "T1 200m ahead, 140 km/h, target 149 (9 under) -> HOLD THROTTLE, ON PACE\n"
        "T3 80m ahead, 180 km/h, target 130 (50 over) -> BRAKE HARD NOW\n"
        "T4 150m ahead, 155 km/h, target 68 (87 over) -> BRAKE HARD, HEAVY STOP\n"
        "T6 100m ahead, 95 km/h, target 120 (25 under) -> ACCELERATE, BUILD SPEED\n"
        "T2 60m ahead, 152 km/h, target 149 (3 over) -> ON PACE, HOLD STEADY\n"
        "\n"
        f"NOW: {corner} {int(dist_m)}m ahead, {int(cur_kmh)} km/h, "
        f"target {int(ref_kmh)} ({abs_delta} {over_under}) ->"
    )
    text = call_ollama_generate(
        prompt,
        base_url=base,
        model=model,
        temperature=0.2,
        num_predict=20,
        timeout_sec=10.0,
    )
    if not text:
        return None
    # Round 10c: walk lines until we find one with actual content.
    # The model sometimes emits blank leading lines or punctuation-only
    # lines; we require >= 2 words before accepting.
    candidate = None
    for raw_line in text.strip().split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Strip common preambles
        for pre in ("Action:", "Reply:", "Command:", "ANSWER:", "->", "=>"):
            if line.upper().startswith(pre.upper()):
                line = line[len(pre) :].strip()
        # Cut on first period (keep one trailing period for emphasis)
        if "." in line:
            line = line.split(".", 1)[0].strip() + "."
        # Strip surrounding quotes
        line = line.strip("\"'")
        # Must have at least 2 words and >= 4 visible chars
        words = [w for w in line.split() if w]
        if len(words) >= 2 and len(line) >= 4:
            candidate = line
            break
    if not candidate:
        return None
    return candidate.upper()[:60]


def compose_llm_debrief_only(
    inbound: dict[str, Any],
    improvement_ranking: list[dict[str, Any]],
) -> str | None:
    """Only return LLM prose; returns None on any Ollama failure.

    Round 9: used by the background follow-up path in server.py so we
    only send a second `coaching_response` when there is ACTUAL LLM output
    to deliver. If Ollama timed out or errored, we skip the follow-up
    entirely (the immediate rules response already went out first).
    """
    if not debrief_feature_enabled():
        return None
    base = ollama_base_url()
    model = ollama_model()
    temp, n_pred, _ = read_generation_options()
    debrief_timeout = read_debrief_ollama_timeout_sec()
    prompt = build_llm_prompt(inbound, improvement_ranking)
    return call_ollama_generate(
        prompt,
        base_url=base,
        model=model,
        temperature=temp,
        num_predict=n_pred,
        timeout_sec=debrief_timeout,
    )
