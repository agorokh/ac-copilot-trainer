"""Model HTTP debrief + rules fallback (issue #46, #854).

Opt-in via ``AC_COPILOT_OLLAMA_ENABLE=1``. Default is off: no ``debrief`` field on
``coaching_response``. When enabled, the sidecar always attaches a ``debrief`` string
(rules-only if the model service is unreachable). The service is loopback, or an
exact HTTPS origin the operator approved in ``AC_COPILOT_INFERENCE_REMOTE_ORIGINS``.
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ENV_ENABLE = "AC_COPILOT_OLLAMA_ENABLE"
_ENV_HOST = "AC_COPILOT_OLLAMA_HOST"
_ENV_MODEL = "AC_COPILOT_OLLAMA_MODEL"
_ENV_TEMP = "AC_COPILOT_OLLAMA_TEMPERATURE"
_ENV_TOKENS = "AC_COPILOT_OLLAMA_NUM_PREDICT"
_ENV_TIMEOUT = "AC_COPILOT_OLLAMA_TIMEOUT_SEC"
_ENV_DEBRIEF_TIMEOUT = "AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC"
# Remote service contract (#854): exact operator-approved HTTPS origins, an optional
# OpenAI-protocol reasoning switch (thinking models spend the token cap otherwise) and
# an optional bearer token. The token is only ever sent to an approved URL.
_ENV_REMOTE_ORIGINS = "AC_COPILOT_INFERENCE_REMOTE_ORIGINS"
_ENV_REASONING_EFFORT = "AC_COPILOT_INFERENCE_REASONING_EFFORT"
_ENV_API_KEY = "AC_COPILOT_INFERENCE_API_KEY"  # pragma: allowlist secret (env var name)
_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high"})

# Documented in WARP.md — tested against Ollama 0.5.x API; pin locally for support.
_DEFAULT_MODEL = "llama3.2"
_DEFAULT_HOST = "http://127.0.0.1:11434"
_DEFAULT_TEMPERATURE = 0.35
_DEFAULT_NUM_PREDICT = 64
_DEFAULT_TIMEOUT_SEC = 8.0
_DEFAULT_DEBRIEF_TIMEOUT_SEC = 8.0


def debrief_feature_enabled() -> bool:
    v = (
        os.environ.get("AC_COPILOT_INFERENCE_ENABLE", os.environ.get(_ENV_ENABLE, ""))
        .strip()
        .lower()
    )
    return v in ("1", "true", "yes", "on")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value
    except ValueError as exc:
        raise ValueError(f"invalid inference setting {name}") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid inference setting {name}") from exc


def ollama_base_url() -> str:
    raw = os.environ.get("AC_COPILOT_INFERENCE_BASE_URL", os.environ.get(_ENV_HOST, "")).strip()
    return (raw or _DEFAULT_HOST).rstrip("/")


def ollama_model() -> str:
    return (
        os.environ.get(
            "AC_COPILOT_INFERENCE_MODEL", os.environ.get(_ENV_MODEL, _DEFAULT_MODEL)
        ).strip()
        or _DEFAULT_MODEL
    )


def read_generation_options() -> tuple[float, int, float]:
    """temperature, num_predict, timeout_sec (generic upper bound)."""
    t = _float_env(_ENV_TEMP, _DEFAULT_TEMPERATURE)
    n = _int_env(_ENV_TOKENS, _DEFAULT_NUM_PREDICT)
    timeout = _float_env(_ENV_TIMEOUT, _DEFAULT_TIMEOUT_SEC)
    t = max(0.0, min(2.0, t))
    n = max(1, min(128, n))
    timeout = max(0.1, min(12.0, timeout))
    return t, n, timeout


def read_debrief_ollama_timeout_sec() -> float:
    """Shorter cap for post-lap debrief so the sidecar answers before CSP coaching hold expires."""
    t = _float_env(_ENV_DEBRIEF_TIMEOUT, _DEFAULT_DEBRIEF_TIMEOUT_SEC)
    return max(0.1, min(12.0, t))


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
            out.append(item.strip()[:400])
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
        str(item.get("suggestion") or "").strip()[:400]
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


# The legacy name remains a compatibility entrypoint. All providers pass this
# same boundary, so callers cannot accidentally create concurrent generations.
_generation_lock = threading.Lock()
_status_lock = threading.Lock()
_generation_status: dict[str, Any] = {"ready": False, "fallback_reason": "not_checked"}


def _set_generation_status(**values: Any) -> None:
    with _status_lock:
        _generation_status.update(values)


def inference_status() -> dict[str, Any]:
    """Cached readback only: /health must never block the WebSocket event loop."""
    with _status_lock:
        status = dict(_generation_status)
    status.update(
        enabled=debrief_feature_enabled(),
        model=ollama_model(),
        provider=inference_provider(),
        remote=_remote_origin(ollama_base_url()) is not None,
    )
    checked = status.get("checked_at")
    if not isinstance(checked, (float, int)) or time.time() - checked > 5:
        status.update(ready=False, fallback_reason="not_checked_or_stale")
    return status


def inference_provider() -> str:
    return os.environ.get("AC_COPILOT_INFERENCE_PROVIDER", "ollama").strip().lower()


def _local_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "http"
        and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _remote_origin(url: str) -> str | None:
    """Return the URL's origin when it is an exact operator-approved HTTPS origin."""
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    origin = f"https://{parsed.hostname.lower()}" + (f":{port}" if port else "")
    raw = os.environ.get(_ENV_REMOTE_ORIGINS, "")
    approved = {item.strip().rstrip("/").lower() for item in raw.split(",") if item.strip()}
    return origin if origin in approved else None


def _approved_url(url: str) -> bool:
    return _local_url(url) or _remote_origin(url) is not None


_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _trim_truncated(text: str) -> str:
    """Drop a trailing fragment cut by the token cap; keep text without a full sentence.

    Only a terminator followed by whitespace ends a sentence, so decimals such as
    lap times are not mistaken for one.
    """
    ends = [match.end() for match in _SENTENCE_END.finditer(text)]
    return text[: ends[-1]] if ends else text


def _placement_ready(model: str, deadline: float) -> bool:
    required_gpu = os.environ.get("AC_COPILOT_INFERENCE_GPU_UUID", "").strip()
    if not required_gpu:
        return True  # Explicit non-rig compatibility: no GPU placement claim.
    health_url = os.environ.get("AC_COPILOT_INFERENCE_HEALTH_URL", "").strip()
    if not _local_url(health_url):
        raise ValueError("a loopback placement health endpoint is required")
    with urllib.request.urlopen(
        health_url, timeout=min(0.5, max(0.01, deadline - time.monotonic()))
    ) as resp:  # nosec B310
        health = json.loads(resp.read(65537))
    epoch = health.get("utc_epoch") if isinstance(health, dict) else None
    placement = health.get("placement") if isinstance(health, dict) else None
    ready = (
        isinstance(health, dict)
        and health.get("ready") is True
        and health.get("gpu_uuid") == required_gpu
        and health.get("model") == model
        and isinstance(placement, list)
        and bool(placement)
        and all(isinstance(row, dict) and row.get("gpu_uuid") == required_gpu for row in placement)
        and isinstance(epoch, (int, float))
        and not isinstance(epoch, bool)
        and math.isfinite(epoch)
        and -2 <= time.time() - epoch <= 5
    )
    if ready:
        _set_generation_status(backend_provider=health.get("provider"))
    return ready


def call_ollama_generate(
    prompt: str,
    *,
    base_url: str,
    model: str,
    temperature: float,
    num_predict: int,
    timeout_sec: float,
    deadline: float | None = None,
) -> str | None:
    """Generate through native Ollama or the common chat API; finite and fail closed.

    A deadline starts at request receipt when supplied. A socket timeout is not
    proof of cancellation in the model server; the supervised host admission
    service must keep its slot until the real backend finishes.
    """
    now = time.monotonic()
    deadline = min(deadline, now + timeout_sec) if deadline is not None else now + timeout_sec
    provider = inference_provider()
    if not _generation_lock.acquire(blocking=False):
        _set_generation_status(ready=False, fallback_reason="busy", checked_at=time.time())
        return None
    try:
        effort = os.environ.get(_ENV_REASONING_EFFORT, "").strip().lower()
        if (
            provider not in ("ollama", "openai")
            or not _approved_url(base_url)
            or (effort and effort not in _REASONING_EFFORTS)
            or not model.strip()
            or len(model) > 256
            or not all(math.isfinite(x) for x in (temperature, timeout_sec, deadline))
            or not 0 <= temperature <= 2
            or not 1 <= num_predict <= 128
            or not 0 < timeout_sec <= 12
        ):
            raise ValueError("invalid inference provider, approved URL or bounded profile")
        if deadline <= time.monotonic():
            _set_generation_status(ready=False, fallback_reason="expired", checked_at=time.time())
            return None
        if not _placement_ready(model, deadline):
            _set_generation_status(
                ready=False, fallback_reason="placement_unavailable", checked_at=time.time()
            )
            return None
        if provider == "openai":
            url = base_url.rstrip("/") + "/chat/completions"
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": temperature,
                "max_tokens": num_predict,
                "seed": 42,
            }
            if effort:
                body["reasoning_effort"] = effort
        else:
            url = base_url.rstrip("/") + "/api/generate"
            body = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "num_ctx": 4096,
                    "num_thread": 2,
                    "seed": 42,
                },
                "keep_alive": "30m",
            }
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(_ENV_API_KEY, "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body, allow_nan=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=remaining) as resp:  # nosec B310
            raw = resp.read().decode("utf-8", errors="replace")
        if time.monotonic() >= deadline:
            _set_generation_status(ready=False, fallback_reason="expired", checked_at=time.time())
            return None
        data = json.loads(raw)
        text = None
        truncated = False
        if isinstance(data, dict):
            if provider == "ollama":
                text = data.get("response")
                truncated = data.get("done_reason") == "length"
            else:
                served = data.get("model")
                if served is not None and served != model:
                    # The response must prove the configured model identity answered.
                    _set_generation_status(
                        ready=False, fallback_reason="model_mismatch", checked_at=time.time()
                    )
                    return None
                choices = data.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    message = choices[0].get("message")
                    truncated = choices[0].get("finish_reason") == "length"
                    if isinstance(message, dict):
                        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            _set_generation_status(
                ready=False, fallback_reason="invalid_response", checked_at=time.time()
            )
            return None
        _set_generation_status(ready=True, fallback_reason=None, checked_at=time.time())
        text = _sanitize_debrief(text)
        return (_trim_truncated(text) if truncated else text)[:2000]
    except (
        ValueError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
    ) as exc:
        logger.info("inference unavailable: %s", exc)
        _set_generation_status(
            ready=False, fallback_reason="request_failed", checked_at=time.time()
        )
        return None
    finally:
        _generation_lock.release()


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
    try:
        temp, n_pred, _ = read_generation_options()
        debrief_timeout = read_debrief_ollama_timeout_sec()
    except ValueError as exc:
        logger.warning("invalid inference configuration: %s", exc)
        _set_generation_status(
            ready=False, fallback_reason="invalid_configuration", checked_at=time.time()
        )
        return rules
    prompt = build_llm_prompt(inbound, improvement_ranking)
    llm = call_ollama_generate(
        prompt,
        base_url=base,
        model=model,
        temperature=temp,
        num_predict=n_pred,
        timeout_sec=debrief_timeout,
        deadline=inbound.get("_inference_deadline"),
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
    deadline: float | None = None,
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
        temperature=0.0,
        num_predict=20,
        timeout_sec=2.0,
        deadline=deadline,
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
    candidate = candidate.upper().rstrip(".!")
    if delta >= 15:
        allowed = {"BRAKE HARD NOW", "BRAKE HARD, HEAVY STOP"}
    elif delta >= 5:
        allowed = {"BRAKE EARLIER", "LIFT NOW"}
    elif delta <= -5:
        allowed = {"ACCELERATE, BUILD SPEED", "HOLD THROTTLE, ON PACE"}
    else:
        allowed = {"ON PACE", "HOLD STEADY", "ON PACE, HOLD STEADY"}
    if candidate not in allowed:
        _set_generation_status(fallback_reason="invalid_advice")
        return None
    return candidate


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
    try:
        temp, n_pred, _ = read_generation_options()
        debrief_timeout = read_debrief_ollama_timeout_sec()
    except ValueError as exc:
        logger.warning("invalid inference configuration: %s", exc)
        _set_generation_status(
            ready=False, fallback_reason="invalid_configuration", checked_at=time.time()
        )
        return None
    prompt = build_llm_prompt(inbound, improvement_ranking)
    return call_ollama_generate(
        prompt,
        base_url=base,
        model=model,
        temperature=temp,
        num_predict=n_pred,
        timeout_sec=debrief_timeout,
        deadline=inbound.get("_inference_deadline"),
    )
