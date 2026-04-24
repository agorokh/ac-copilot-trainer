"""LLM distillation helpers (#78)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import TracebackType
from unittest.mock import patch

import pytest

from tools.process_miner.distill import (
    DISTILL_PROMPT_VERSION,
    _distill_profile_token,
    _payload_fingerprint,
    build_cluster_payloads_for_distillation,
    distill_api_key,
    distill_cache_path,
    distill_universal_with_cache,
    read_distill_cache,
    run_distillation,
    write_distill_cache,
)


def test_payload_fingerprint_stable() -> None:
    p = [{"a": 1, "b": "x"}]
    assert _payload_fingerprint(p) == _payload_fingerprint([{"b": "x", "a": 1}])


def test_payload_fingerprint_order_independent_rows() -> None:
    a = {
        "title_key": "a",
        "repos": ["x"],
        "severity": "nit",
        "representative_snippets": [],
        "affected_file_samples": [],
    }
    b = {
        "title_key": "b",
        "repos": ["y"],
        "severity": "bug",
        "representative_snippets": [],
        "affected_file_samples": [],
    }
    assert _payload_fingerprint([a, b]) == _payload_fingerprint([b, a])


def test_payload_fingerprint_includes_representative_snippets() -> None:
    base = {
        "title_key": "t",
        "repos": ["z/z"],
        "severity": "nit",
        "affected_file_samples": [],
    }
    a = {**base, "representative_snippets": ["snippet-a"]}
    b = {**base, "representative_snippets": ["snippet-b"]}
    assert _payload_fingerprint([a]) != _payload_fingerprint([b])


def test_payload_fingerprint_sorts_repo_lists() -> None:
    base = {
        "severity": "nit",
        "representative_snippets": [],
        "affected_file_samples": [],
    }
    row_a = {"title_key": "t", "repos": ["z/z", "a/a"], **base}
    row_b = {"title_key": "t", "repos": ["a/a", "z/z"], **base}
    assert _payload_fingerprint([row_a]) == _payload_fingerprint([row_b])


def test_distill_profile_token_ignores_chat_completions_suffix(monkeypatch) -> None:
    monkeypatch.delenv("DISTILL_MODEL", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "https://api.example.com/v1")
    a = _distill_profile_token()
    monkeypatch.setenv("DISTILL_BASE_URL", "https://api.example.com/v1/chat/completions")
    b = _distill_profile_token()
    assert a == b


def test_distill_api_key_unknown_host_never_uses_provider_keys(monkeypatch) -> None:
    """Unrecognized DISTILL_BASE_URL must not receive OPENROUTER_/OPENAI_ keys (#81)."""
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "https://custom-proxy.example/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-should-not-be-used")  # pragma: allowlist secret
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-be-used")  # pragma: allowlist secret
    assert distill_api_key() is None


def test_distill_api_key_explicit_override_wins_on_unknown_host(monkeypatch) -> None:
    monkeypatch.setenv("DISTILL_API_KEY", "explicit-override")  # pragma: allowlist secret
    monkeypatch.setenv("DISTILL_BASE_URL", "https://custom-proxy.example/v1")
    assert distill_api_key() == "explicit-override"


def test_distill_api_key_openai_host_uses_openai_key(monkeypatch) -> None:
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")  # pragma: allowlist secret
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert distill_api_key() == "sk-openai-test"


def test_distill_api_key_openrouter_substring_in_path_not_trusted(monkeypatch) -> None:
    """Hostname must be OpenRouter, not a substring in the path (Sourcery #81)."""
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "https://evil.example/v1/mirror/openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-should-not-send")  # pragma: allowlist secret
    assert distill_api_key() is None


def test_distill_api_key_openrouter_lookalike_hostname_rejected(monkeypatch) -> None:
    """Suffix ``openrouter.ai`` alone must not match ``evilopenrouter.ai`` (Bugbot #81)."""
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "https://evilopenrouter.ai/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-should-not-send")  # pragma: allowlist secret
    assert distill_api_key() is None


def test_distill_api_key_subdomain_openrouter_accepted(monkeypatch) -> None:
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "https://api.openrouter.ai/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-ok")  # pragma: allowlist secret
    assert distill_api_key() == "sk-or-ok"


def test_distill_api_key_scheme_less_openrouter_host(monkeypatch) -> None:
    """Scheme-less ``DISTILL_BASE_URL`` must still resolve OpenRouter (CodeRabbit #81)."""
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.setenv("DISTILL_BASE_URL", "openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-schemeless")  # pragma: allowlist secret
    assert distill_api_key() == "sk-or-schemeless"


def test_resolved_base_url_prepends_https_when_scheme_missing(monkeypatch) -> None:
    from tools.process_miner.distill import _resolved_base_url

    monkeypatch.setenv("DISTILL_BASE_URL", "api.openrouter.ai/v1")
    assert _resolved_base_url(None) == "https://api.openrouter.ai/v1"


def test_read_distill_cache_non_object_is_miss(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    assert read_distill_cache(path) is None


def test_read_distill_cache_invalid_utf8_is_miss(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe lone \xed\xa0\xbd")
    assert read_distill_cache(path) is None


def test_distill_cache_roundtrip(tmp_path) -> None:
    payload = [
        {
            "title_key": "k",
            "repos": ["o/r"],
            "severity": "nit",
            "representative_snippets": ["s"],
            "affected_file_samples": ["f.py"],
        }
    ]
    path = distill_cache_path(tmp_path, payload=payload)
    write_distill_cache(path, {"cached": True})
    assert read_distill_cache(path) == {"cached": True}


def test_build_cluster_payloads_shapes() -> None:
    from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment

    cl = CommentCluster(
        cluster_id=0,
        title="cache / invalidation",
        count=3,
        comments=[
            ReviewComment(
                id="1", body="x", author="b", author_type="bot", bot_name="t", pr_number=1
            )
        ],
        affected_files=["src/x.py"],
        severity="bug",
        preventability="guideline",
        distinct_pr_count=1,
        representative_examples=["snippet one"],
    )
    ar = AnalysisResult(
        prs=[
            PRData(
                number=1,
                title="p",
                author="a",
                created_at=datetime.now(UTC),
                merged_at=None,
                body="",
            )
        ],
        clusters=[cl],
        ci_failures=[],
        churned_files=[],
        stats={},
    )
    per_repo = {"agorokh/r": ar}
    titles = ["cache / invalidation"]
    tr = {"cache / invalidation": {"agorokh/r"}}
    rows = build_cluster_payloads_for_distillation(titles, tr, per_repo)
    assert len(rows) == 1
    assert rows[0]["title_key"] == "cache / invalidation"
    assert rows[0]["severity"] == "bug"
    assert "agorokh/r" in rows[0]["repos"]
    assert rows[0]["pr_refs"] == ["agorokh/r#1"]
    assert rows[0]["distinct_pr_count"] == 1


def test_build_cluster_payloads_lowercases_title_to_repos_lookup() -> None:
    from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment

    cl = CommentCluster(
        cluster_id=0,
        title="cache / invalidation",
        count=1,
        comments=[
            ReviewComment(
                id="1", body="x", author="b", author_type="bot", bot_name="t", pr_number=1
            )
        ],
        affected_files=[],
        severity="bug",
        preventability="guideline",
        distinct_pr_count=1,
        representative_examples=[],
    )
    ar = AnalysisResult(
        prs=[
            PRData(
                number=1,
                title="p",
                author="a",
                created_at=datetime.now(UTC),
                merged_at=None,
                body="",
            )
        ],
        clusters=[cl],
        ci_failures=[],
        churned_files=[],
        stats={},
    )
    per_repo = {"agorokh/r": ar}
    titles = ["Cache / Invalidation"]
    tr = {"cache / invalidation": {"agorokh/r"}}
    rows = build_cluster_payloads_for_distillation(titles, tr, per_repo)
    assert len(rows) == 1
    assert rows[0]["repos"] == ["agorokh/r"]


def test_build_cluster_payloads_picks_worse_severity_across_repos() -> None:
    from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment

    def one_cluster(sev: str, slug_suffix: str) -> AnalysisResult:
        cl = CommentCluster(
            cluster_id=0,
            title="shared title",
            count=1,
            comments=[
                ReviewComment(
                    id=slug_suffix,
                    body="x",
                    author="b",
                    author_type="bot",
                    bot_name="t",
                    pr_number=1,
                )
            ],
            affected_files=[],
            severity=sev,
            preventability="guideline",
            distinct_pr_count=1,
            representative_examples=[],
        )
        return AnalysisResult(
            prs=[
                PRData(
                    number=1,
                    title="p",
                    author="a",
                    created_at=datetime.now(UTC),
                    merged_at=None,
                    body="",
                )
            ],
            clusters=[cl],
            ci_failures=[],
            churned_files=[],
            stats={},
        )

    # Use canonical :data:`SEVERITY_ORDER` labels (not unknown fallbacks).
    per_repo = {
        "o/maint": one_cluster("maintainability", "a"),
        "o/sec": one_cluster("security", "b"),
    }
    titles = ["shared title"]
    tr = {"shared title": {"o/maint", "o/sec"}}
    rows = build_cluster_payloads_for_distillation(titles, tr, per_repo)
    assert rows[0]["severity"] == "security"


def test_build_cluster_payloads_prefers_higher_comment_volume_under_cap() -> None:
    from tools.process_miner.schemas import AnalysisResult, CommentCluster, PRData, ReviewComment

    def ar_for(title: str, count: int) -> AnalysisResult:
        cl = CommentCluster(
            cluster_id=0,
            title=title,
            count=count,
            comments=[
                ReviewComment(
                    id=f"{title}-{i}",
                    body="x " * 40,
                    author="b",
                    author_type="bot",
                    bot_name="t",
                    pr_number=i,
                )
                for i in range(count)
            ],
            affected_files=[],
            severity="nit",
            preventability="guideline",
            distinct_pr_count=count,
            representative_examples=[],
        )
        return AnalysisResult(
            prs=[
                PRData(
                    number=1,
                    title="p",
                    author="a",
                    created_at=datetime.now(UTC),
                    merged_at=None,
                    body="",
                )
            ],
            clusters=[cl],
            ci_failures=[],
            churned_files=[],
            stats={},
        )

    per_repo = {
        "o/a": ar_for("low vol", 2),
        "o/b": ar_for("high vol", 9),
    }
    titles = ["low vol", "high vol"]
    tr = {"low vol": {"o/a"}, "high vol": {"o/b"}}
    rows = build_cluster_payloads_for_distillation(titles, tr, per_repo, max_clusters=1)
    assert len(rows) == 1
    assert rows[0]["title_key"] == "high vol"


def test_run_distillation_skips_json_object_on_unknown_host(monkeypatch) -> None:
    monkeypatch.delenv("DISTILL_JSON_OBJECT", raising=False)
    bodies: list[dict] = []

    class Inner:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "clusters": {
                                            "k": {
                                                "verdict": "noise",
                                                "confidence": 0.1,
                                                "lesson": "",
                                            }
                                        }
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    def capture_urlopen(req: object, timeout: float = 0) -> Ctx:
        assert req is not None
        data = getattr(req, "data", None)
        assert isinstance(data, bytes)
        bodies.append(json.loads(data.decode()))
        return Ctx()

    monkeypatch.setattr(
        "tools.process_miner.distill.urllib.request.urlopen",
        capture_urlopen,
    )
    run_distillation(
        [{"title_key": "k"}],
        api_key="dummy-api-key",  # pragma: allowlist secret
        base_url="https://unknown-distill-host.example/v1",
    )
    assert bodies
    assert "response_format" not in bodies[0]


def test_run_distillation_adds_json_object_for_openrouter(monkeypatch) -> None:
    monkeypatch.delenv("DISTILL_JSON_OBJECT", raising=False)
    bodies: list[dict] = []

    class Inner:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "clusters": {
                                            "k": {
                                                "verdict": "noise",
                                                "confidence": 0.1,
                                                "lesson": "",
                                            }
                                        }
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    def capture_urlopen(req: object, timeout: float = 0) -> Ctx:
        assert req is not None
        data = getattr(req, "data", None)
        assert isinstance(data, bytes)
        bodies.append(json.loads(data.decode()))
        return Ctx()

    monkeypatch.setattr(
        "tools.process_miner.distill.urllib.request.urlopen",
        capture_urlopen,
    )
    run_distillation(
        [{"title_key": "k"}],
        api_key="dummy-api-key",  # pragma: allowlist secret
        base_url="https://openrouter.ai/api/v1",
    )
    assert bodies[0].get("response_format") == {"type": "json_object"}


def _minimal_distill_payload() -> list[dict]:
    return [
        {
            "title_key": "k",
            "repos": ["o/r"],
            "severity": "nit",
            "representative_snippets": [],
            "affected_file_samples": [],
        }
    ]


def test_distill_universal_with_cache_hit(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    payload = _minimal_distill_payload()
    path = distill_cache_path(tmp_path, payload=payload)
    write_distill_cache(
        path,
        {
            "source": "live",
            "cache_path": str(path),
            "fingerprint": "x",
            "prompt_version": DISTILL_PROMPT_VERSION,
            "result": {"parsed": {"clusters": {}}, "model": "m", "base_url": "u"},
        },
    )
    out = distill_universal_with_cache(tmp_path, payload, force_refresh=False)
    assert out["source"] == "cache"
    assert out["cache_path"] == str(path)
    assert out["result"]["parsed"] == {"clusters": {}}


def test_distill_universal_with_cache_miss_calls_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DISTILL_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    payload = _minimal_distill_payload()
    api_result = {
        "raw_api": {},
        "parsed": {"clusters": {"k": {"verdict": "noise", "confidence": 1, "lesson": "z"}}},
        "model": "gpt-4o-mini",
        "base_url": "https://example/v1/chat/completions",
        "prompt_version": DISTILL_PROMPT_VERSION,
    }
    with patch("tools.process_miner.distill.run_distillation", return_value=api_result) as m:
        out = distill_universal_with_cache(tmp_path, payload, force_refresh=True)
    m.assert_called_once()
    assert out["source"] == "live"
    assert out["result"]["parsed"]["clusters"]["k"]["verdict"] == "noise"


def test_distill_universal_with_cache_missing_key_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DISTILL_API_KEY", raising=False)
    monkeypatch.delenv("DISTILL_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="No API key for distillation"):
        distill_universal_with_cache(tmp_path, _minimal_distill_payload(), force_refresh=True)


def test_run_distillation_strips_json_markdown_fence() -> None:
    inner = json.dumps({"clusters": {"k": {"verdict": "noise", "confidence": 0.5, "lesson": ""}}})
    api_body = {
        "choices": [{"message": {"content": f"```json\n{inner}\n```"}}],
    }

    class InnerReader:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> InnerReader:
            return InnerReader()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()):
        out = run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )
    assert out["parsed"]["clusters"]["k"]["verdict"] == "noise"


def test_run_distillation_parses_response() -> None:
    api_body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"clusters": {"k": {"verdict": "noise", "confidence": 0.9, "lesson": "x"}}}
                    )
                }
            }
        ]
    }

    class Inner:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()):
        out = run_distillation([{"title_key": "k"}], api_key="sk-test")
    assert "parsed" in out
    assert out["parsed"]["clusters"]["k"]["verdict"] == "noise"


def test_run_distillation_rejects_non_object_http_json() -> None:
    api_body = "[1, 2, 3]"

    class Inner:
        def read(self) -> bytes:
            return api_body.encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with (
        patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()),
        pytest.raises(RuntimeError, match="must be an object"),
    ):
        run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )


def test_run_distillation_rejects_non_object_json() -> None:
    api_body = {"choices": [{"message": {"content": "[]"}}]}

    class Inner:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with (
        patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()),
        pytest.raises(RuntimeError, match="must be an object"),
    ):
        run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )


def test_run_distillation_rejects_non_object_cluster_entry() -> None:
    api_body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"clusters": {"k": []}}),
                }
            }
        ]
    }

    class Inner:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with (
        patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()),
        pytest.raises(RuntimeError, match="must be an object"),
    ):
        run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )


def test_run_distillation_rejects_string_pr_in_canonical_citations() -> None:
    """v2 citations must use int ``pr`` per schema (Bugbot #81)."""
    inner = {
        "verdict": "signal",
        "confidence": 0.5,
        "conceptual_mistake": "mistake",
        "preventive_rule": "rule",
        "canonical_citations": [{"pr": "owner/repo#1", "path": "a.py", "note": "n"}],
        "applicability": "universal",
    }
    api_body = {"choices": [{"message": {"content": json.dumps({"clusters": {"k": inner}})}}]}

    class Inner:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with (
        patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()),
        pytest.raises(RuntimeError, match=r"citation\[0\]\.pr must be a numeric"),
    ):
        run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )


def test_run_distillation_coerces_numeric_string_pr_in_canonical_citations() -> None:
    """LLMs sometimes emit PR numbers as JSON strings; normalize to int (Gemini #81)."""
    inner = {
        "verdict": "signal",
        "confidence": 0.5,
        "conceptual_mistake": "mistake",
        "preventive_rule": "rule",
        "canonical_citations": [{"pr": " 42 ", "path": "a.py", "note": "n"}],
        "applicability": "universal",
    }
    api_body = {"choices": [{"message": {"content": json.dumps({"clusters": {"k": inner}})}}]}

    class Inner:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()):
        out = run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )
    pr = out["parsed"]["clusters"]["k"]["canonical_citations"][0]["pr"]
    assert pr == 42
    assert isinstance(pr, int)


@pytest.mark.parametrize("bad_clusters", [None, []])
def test_run_distillation_rejects_non_dict_clusters(bad_clusters: object) -> None:
    api_body = {"choices": [{"message": {"content": json.dumps({"clusters": bad_clusters})}}]}

    class Inner:
        def read(self) -> bytes:
            return json.dumps(api_body).encode()

    class Ctx:
        def __enter__(self) -> Inner:
            return Inner()

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return None

    with (
        patch("tools.process_miner.distill.urllib.request.urlopen", return_value=Ctx()),
        pytest.raises(RuntimeError, match="clusters' object"),
    ):
        run_distillation(
            [{"title_key": "k"}],
            api_key="dummy-api-key",  # pragma: allowlist secret
        )
