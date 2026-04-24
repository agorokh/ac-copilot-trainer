"""LLM distillation of cross-repo cluster patterns (#78).

Uses an OpenAI-compatible ``/v1/chat/completions`` JSON API. Output is cached on disk
keyed by prompt version, distill profile (model + base URL), and payload fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.process_miner.analyze import more_severe_severity
from tools.process_miner.schemas import AnalysisResult, CommentCluster

# Selects cache path segment and validator contract (``distill_cache_path`` /
# ``_validate_distill_cluster_entries``). Live ``run_distillation`` always sends
# the v2 structured JSON prompt; ``distill-v1`` remains for reading legacy caches.
DISTILL_PROMPT_VERSION = os.environ.get("DISTILL_PROMPT_VERSION", "distill-v2")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# Sonnet is the cost-effective default; set DISTILL_MODEL=anthropic/claude-opus-4.6
# for higher-quality distillation on premium runs. OpenRouter slugs use dotted
# versions (e.g. anthropic/claude-sonnet-4.6), not hyphenated 4-6 (Bugbot/CodeRabbit #81).
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"


def _normalized_distill_base_url(explicit: str | None = None) -> str:
    """Strip and default ``DISTILL_BASE_URL``; prepend ``https://`` when scheme is omitted.

    Keeps :func:`distill_api_key` hostname resolution consistent with
    :func:`_resolved_base_url` (CodeRabbit #81).
    """
    raw = (
        explicit if explicit is not None else os.environ.get("DISTILL_BASE_URL")
    ) or DEFAULT_BASE_URL
    raw = raw.strip()
    if not raw:
        return DEFAULT_BASE_URL
    if "://" not in raw:
        raw = "https://" + raw
    return raw


def _distill_api_hostname() -> str:
    """Lowercase hostname for ``DISTILL_BASE_URL`` (or default), empty if unparseable."""
    raw = _normalized_distill_base_url(None)
    try:
        return (urllib.parse.urlparse(raw).hostname or "").lower()
    except ValueError:
        return ""


def distill_api_key() -> str | None:
    """Resolve API key from env, matching key to the target endpoint.

    ``DISTILL_API_KEY`` is checked first (explicit override). After that, the resolved
    base URL determines which provider key to prefer — ``OPENROUTER_API_KEY`` for
    OpenRouter endpoints, ``OPENAI_API_KEY`` for OpenAI endpoints. Unrecognized hosts
    return ``None`` so provider keys are never sent to arbitrary third-party URLs
    (use ``DISTILL_API_KEY`` for custom endpoints).
    """
    # Explicit override — always wins regardless of endpoint
    v = os.environ.get("DISTILL_API_KEY", "").strip()
    if v:
        return v
    # Match key to endpoint to prevent cross-provider credential leak.
    # No fallback loop: if the endpoint-matched key is absent, return None rather
    # than silently sending a different provider's credential (Sourcery #81).
    # Provider list is intentionally tiny; add explicit hostname branches for new hosts.
    host = _distill_api_hostname()
    # Require registrable boundary so ``evilopenrouter.ai`` does not match (Bugbot #81).
    if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return os.environ.get("OPENROUTER_API_KEY", "").strip() or None
    if host == "api.openai.com" or host.endswith(".openai.com"):
        return os.environ.get("OPENAI_API_KEY", "").strip() or None
    # Unknown host — do not guess provider keys (CodeRabbit/Sourcery #81).
    return None


def _payload_fingerprint(payload: list[dict[str, Any]]) -> str:
    def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
        tk = str(row.get("title_key", ""))
        repos = row.get("repos", [])
        if isinstance(repos, list):
            repos_s = json.dumps(sorted(repos), ensure_ascii=False)
        else:
            repos_s = json.dumps(repos, ensure_ascii=False, sort_keys=True)
        sev = str(row.get("severity", ""))
        return (tk, repos_s, sev)

    canonical = sorted(payload, key=row_key)
    normalized: list[dict[str, Any]] = []
    for row in canonical:
        d = dict(row)
        rlist = d.get("repos")
        if isinstance(rlist, list):
            d["repos"] = sorted(rlist)
        normalized.append(d)
    raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def distill_cache_path(
    repo_root: Path,
    *,
    prompt_version: str = DISTILL_PROMPT_VERSION,
    payload: list[dict[str, Any]],
) -> Path:
    h = _payload_fingerprint(payload)
    prof = _distill_profile_token()
    return repo_root / ".cache" / "process_miner_distill" / prompt_version / f"{prof}_{h}.json"


def _resolved_base_url(base_url: str | None) -> str:
    raw = _normalized_distill_base_url(base_url).rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme for distill endpoint: {parsed.scheme!r}")
    return raw


def _canonical_base_for_profile(base_url: str | None = None) -> str:
    """Normalize base URL so ``.../v1`` and ``.../v1/chat/completions`` share one cache profile."""
    b = _resolved_base_url(base_url)
    suffix = "/chat/completions"
    while b.endswith(suffix):
        b = b[: -len(suffix)].rstrip("/")
    return b.rstrip("/")


def _distill_profile_token() -> str:
    """Short stable token so cache files do not collide across model/base URL changes."""
    base = _canonical_base_for_profile(None)
    model = os.environ.get("DISTILL_MODEL") or DEFAULT_MODEL
    blob = f"{base}\n{model}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _chat_completions_url(base: str) -> str:
    b = base.rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return f"{b}/chat/completions"


def _strip_llm_json_markdown_fence(content: str) -> str:
    """Some providers wrap JSON in a fenced block even without strict JSON mode."""
    t = (content or "").strip()
    if not t.startswith("```"):
        return t
    t = re.sub(r"^```(?:json|JSON)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


# Hostnames (substring match) known to accept OpenAI-style ``response_format`` on chat completions.
_JSON_OBJECT_COMPAT_HOST_MARKERS: tuple[str, ...] = (
    "openai.com",
    "openai.azure.com",
    "groq.com",
    "together.xyz",
    "together.ai",
    "fireworks.ai",
    "deepinfra.com",
    "openrouter.ai",
    "perplexity.ai",
    "x.ai",
)


def _endpoint_supports_json_object_mode(chat_completions_url: str) -> bool:
    """Whether to send OpenAI-style ``response_format`` JSON mode (provider-dependent)."""
    raw = os.environ.get("DISTILL_JSON_OBJECT", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on", "force"):
        return True
    host = (urllib.parse.urlparse(chat_completions_url).hostname or "").lower()

    def host_allows_marker(m: str) -> bool:
        return host == m or host.endswith("." + m)

    return any(host_allows_marker(m) for m in _JSON_OBJECT_COMPAT_HOST_MARKERS)


def read_distill_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


_V2_REQUIRED_FIELDS: tuple[str, ...] = (
    "verdict",
    "confidence",
    "conceptual_mistake",
    "preventive_rule",
    "canonical_citations",
    "applicability",
)


def _validate_distill_cluster_entries(clusters: dict[str, Any], url: str) -> None:
    """Ensure each ``clusters[title_key]`` matches the v2 prompt contract.

    Accepts the v1 ``lesson`` field as a fallback for cached v1 results.
    """
    for title_key, entry in clusters.items():
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"distill clusters[{title_key!r}] must be an object from {url}, "
                f"got {type(entry).__name__}"
            )
        # v1 compat: accept "lesson" in place of v2 fields
        is_v1 = "lesson" in entry and "conceptual_mistake" not in entry
        required = ("verdict", "confidence", "lesson") if is_v1 else _V2_REQUIRED_FIELDS
        for field in required:
            if field not in entry:
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] missing {field!r} in response from {url}"
                )
        verdict = entry["verdict"]
        if verdict not in ("signal", "noise"):
            raise RuntimeError(
                f"distill clusters[{title_key!r}] invalid verdict {verdict!r} from {url}"
            )
        conf = entry["confidence"]
        if type(conf) is bool:
            raise RuntimeError(
                f"distill clusters[{title_key!r}] confidence must be numeric from {url}"
            )
        if isinstance(conf, str):
            try:
                float(conf)
            except ValueError as e:
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] confidence not numeric from {url}"
                ) from e
        elif not isinstance(conf, (int, float)):
            raise RuntimeError(
                f"distill clusters[{title_key!r}] confidence must be numeric from {url}"
            )
        if not is_v1:
            if not isinstance(entry["conceptual_mistake"], str):
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] conceptual_mistake must be string from {url}"
                )
            if not isinstance(entry["preventive_rule"], str):
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] preventive_rule must be string from {url}"
                )
            citations = entry["canonical_citations"]
            if not isinstance(citations, list):
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] canonical_citations must be array from {url}"
                )
            # Validate inner structure of each citation object (#16/#24)
            for ci, cit in enumerate(citations):
                if not isinstance(cit, dict):
                    raise RuntimeError(
                        f"distill clusters[{title_key!r}] citation[{ci}] must be object from {url}"
                    )
                for cf in ("pr", "path", "note"):
                    if cf not in cit:
                        raise RuntimeError(
                            f"distill clusters[{title_key!r}] citation[{ci}] missing "
                            f"{cf!r} from {url}"
                        )
                pr_val = cit["pr"]
                if isinstance(pr_val, str):
                    try:
                        pr_val = int(pr_val.strip())
                        cit["pr"] = pr_val
                    except ValueError:
                        pass
                if type(pr_val) is bool or not isinstance(pr_val, int):
                    raise RuntimeError(
                        f"distill clusters[{title_key!r}] citation[{ci}].pr must be a numeric "
                        f"GitHub PR id (integer), not owner/repo# or arbitrary text — put "
                        f"cross-repo refs in citation['note'] (from {url})"
                    )
                if not isinstance(cit["path"], str):
                    raise RuntimeError(
                        f"distill clusters[{title_key!r}] citation[{ci}].path must be string "
                        f"from {url}"
                    )
                if not isinstance(cit["note"], str):
                    raise RuntimeError(
                        f"distill clusters[{title_key!r}] citation[{ci}].note must be string "
                        f"from {url}"
                    )
            # Validate applicability type (#10/#15)
            if not isinstance(entry["applicability"], str):
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] applicability must be string from {url}"
                )
        else:
            if not isinstance(entry["lesson"], str):
                raise RuntimeError(
                    f"distill clusters[{title_key!r}] lesson must be a string from {url}"
                )


def write_distill_cache(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def build_cluster_payloads_for_distillation(
    universal_titles: list[str],
    title_to_repos: Mapping[str, set[str]],
    per_repo: Mapping[str, AnalysisResult],
    *,
    max_clusters: int = 40,
    snippets_per_cluster: int = 3,
) -> list[dict[str, Any]]:
    """Shape S0 / universal titles into JSON rows for the LLM."""
    clusters_by_slug_title: dict[tuple[str, str], list[CommentCluster]] = defaultdict(list)
    title_total_counts: dict[str, int] = defaultdict(int)
    for slug, res in per_repo.items():
        for cl in res.clusters:
            tk = cl.title.strip().lower()
            clusters_by_slug_title[(slug, tk)].append(cl)
            title_total_counts[tk] += cl.count

    ranked = sorted(
        universal_titles,
        key=lambda ti: (-title_total_counts.get(ti.strip().lower(), 0), ti.strip().lower()),
    )
    out: list[dict[str, Any]] = []
    for title in ranked[:max_clusters]:
        tkey = title.strip().lower()
        repos = sorted(title_to_repos.get(tkey, ()))
        snippets: list[str] = []
        affected: list[str] = []
        pr_ref_set: set[str] = set()
        severity: str | None = None
        for slug in repos:
            group = clusters_by_slug_title.get((slug, tkey))
            if not group:
                continue
            cl = group[0]
            if severity is None:
                severity = cl.severity
            else:
                severity = more_severe_severity(severity, cl.severity)
            for ex in cl.representative_examples[:snippets_per_cluster]:
                if not ex:
                    continue
                snip = ex[:800]
                if snip not in snippets:
                    snippets.append(snip)
            for p in cl.affected_files[:4]:
                if p not in affected:
                    affected.append(p)
            for c in cl.comments:
                if c.pr_number is not None:
                    pr_ref_set.add(f"{slug}#{c.pr_number}")
        out.append(
            {
                "title_key": title,
                "repos": repos,
                "severity": severity or "unknown",
                "representative_snippets": snippets[:snippets_per_cluster],
                "affected_file_samples": affected[:6],
                "pr_refs": sorted(pr_ref_set)[:10],
                "distinct_pr_count": len(pr_ref_set),
            }
        )
    return out


def run_distillation(
    clusters_payload: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Extract conceptual mistakes + preventive rules per cluster (distill-v2).

    For each cluster, outputs ``conceptual_mistake``, ``preventive_rule``,
    ``canonical_citations``, ``verdict``, ``confidence``, ``applicability``.
    """
    url = _chat_completions_url(_resolved_base_url(base_url))
    mdl = model or os.environ.get("DISTILL_MODEL") or DEFAULT_MODEL
    system = (
        "You are a principal engineer analyzing semantically clustered PR review findings "
        "from a fleet of repositories under common ownership. Each cluster represents "
        "multiple instances of a conceptually similar issue found across different PRs.\n\n"
        "For EACH cluster, determine:\n"
        "1. Whether it is actionable engineering signal or bot/process noise.\n"
        "2. If signal: the single conceptual mistake being repeated, in one sentence.\n"
        "3. A concrete preventive rule phrased as an imperative for implementers.\n"
        "4. Canonical citations: file paths and PR references that best exemplify the issue. "
        "Each cluster payload includes `pr_refs` like `owner/repo#123` — use those strings "
        "in citation notes when multiple repos appear so citations stay unambiguous.\n"
        "5. Applicability: 'universal' (any repo), or a domain like 'trading'.\n\n"
        'Respond with ONLY valid JSON: {"clusters": {<title_key>: <entry>, ...}}.\n'
        "Each entry MUST have:\n"
        '  "verdict": "signal" or "noise"\n'
        '  "confidence": number 0.0-1.0\n'
        '  "conceptual_mistake": string (one sentence; empty for noise)\n'
        '  "preventive_rule": string (imperative; empty for noise)\n'
        '  "canonical_citations": [{"pr": int, "path": string, "note": string}] '
        "(up to 3; empty array for noise)\n"
        '  "applicability": "universal" or domain string\n\n'
        "Do NOT produce generic advice. Every rule must reference the specific pattern."
    )
    user = json.dumps({"clusters": clusters_payload}, ensure_ascii=False)
    max_tok_raw = os.environ.get("DISTILL_MAX_TOKENS", "4096").strip()
    try:
        max_tokens = int(max_tok_raw)
    except ValueError:
        max_tokens = 4096
    max_tokens = max(256, min(max_tokens, 128_000))
    payload: dict[str, Any] = {
        "model": mdl,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if _endpoint_supports_json_object_mode(url):
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"distill invalid JSON in HTTP body from {url}: {raw_text[:500]!r}"
            ) from e
        if not isinstance(raw, dict):
            raise RuntimeError(
                f"distill HTTP JSON from {url} must be an object, got "
                f"{type(raw).__name__}: {raw_text[:300]!r}"
            ) from None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"distill HTTP {e.code} for {url}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"distill network error for {url}: {e}") from e
    try:
        content = raw["choices"][0]["message"]["content"]
        stripped = _strip_llm_json_markdown_fence(content)
        parsed = json.loads(stripped)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
        snippet = repr(raw)[:500]
        raise RuntimeError(f"distill unexpected response shape from {url}: {snippet}") from e
    if not isinstance(parsed, dict):
        snippet = repr(parsed)[:500]
        raise RuntimeError(f"distill response JSON from {url} must be an object, got: {snippet}")
    if not isinstance(parsed.get("clusters"), dict):
        snippet = repr(parsed)[:500]
        raise RuntimeError(f"distill response missing 'clusters' object from {url}: {snippet}")
    _validate_distill_cluster_entries(parsed["clusters"], url)
    return {
        "raw_api": raw,
        "parsed": parsed,
        "model": mdl,
        "base_url": url,
        "prompt_version": DISTILL_PROMPT_VERSION,
    }


def distill_universal_with_cache(
    repo_root: Path,
    clusters_payload: list[dict[str, Any]],
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return cached distillation or call API; persist to versioned cache path."""
    cache_path = distill_cache_path(repo_root, payload=clusters_payload)
    if not force_refresh:
        cached = read_distill_cache(cache_path)
        if cached is not None:
            return {**cached, "source": "cache", "cache_path": str(cache_path)}
    key = distill_api_key()
    if not key:
        raise ValueError(
            "No API key for distillation: set DISTILL_API_KEY, or match "
            "OPENROUTER_API_KEY / OPENAI_API_KEY to the configured DISTILL_BASE_URL host"
        )
    result = run_distillation(clusters_payload, api_key=key)
    envelope = {
        "source": "live",
        "cache_path": str(cache_path),
        "fingerprint": _payload_fingerprint(clusters_payload),
        "prompt_version": DISTILL_PROMPT_VERSION,
        "result": result,
    }
    write_distill_cache(cache_path, envelope)
    return envelope
